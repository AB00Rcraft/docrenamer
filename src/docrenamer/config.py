"""Загрузка и валидация конфигурации (раздел 56 ТЗ).

Конфиг читается только из локального файла. Никаких удалённых источников
настроек, лицензий или обновлений (раздел 3 ТЗ).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from docrenamer.paths import AppPaths, default_paths


class ConfigError(ValueError):
    """Ошибка конфигурации с русским описанием."""


def _clamp(value: float, low: float, high: float, name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ConfigError(f"Параметр «{name}» должен быть числом.")
    return max(low, min(high, float(value)))


def _as_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"Параметр «{name}» должен быть true или false.")
    return value


def _as_int(value: Any, name: str, low: int = 0, high: int = 10**9) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Параметр «{name}» должен быть целым числом.")
    return max(low, min(high, value))


@dataclass(slots=True)
class AIConfig:
    enabled: bool = True
    engine: str = "llama_cpp_cli"
    model_path: str = "./models/document-model.gguf"
    context_size: int = 8192
    max_output_tokens: int = 900
    temperature: float = 0.1
    timeout_seconds: int = 120
    threads: int = 0  # 0 — определить автоматически

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AIConfig:
        cfg = cls()
        if "enabled" in data:
            cfg.enabled = _as_bool(data["enabled"], "ai.enabled")
        if "engine" in data:
            engine = str(data["engine"])
            if engine != "llama_cpp_cli":
                raise ConfigError(
                    "Поддерживается только локальный движок «llama_cpp_cli». "
                    "Сетевые AI-движки запрещены (STRICT LOCAL MODE)."
                )
            cfg.engine = engine
        if "model_path" in data:
            cfg.model_path = str(data["model_path"])
        if "context_size" in data:
            cfg.context_size = _as_int(data["context_size"], "ai.context_size", 512, 1_048_576)
        if "max_output_tokens" in data:
            cfg.max_output_tokens = _as_int(
                data["max_output_tokens"], "ai.max_output_tokens", 64, 8192
            )
        if "temperature" in data:
            cfg.temperature = _clamp(data["temperature"], 0.0, 2.0, "ai.temperature")
        if "timeout_seconds" in data:
            cfg.timeout_seconds = _as_int(data["timeout_seconds"], "ai.timeout_seconds", 5, 3600)
        if "threads" in data:
            cfg.threads = _as_int(data["threads"], "ai.threads", 0, 256)
        return cfg


@dataclass(slots=True)
class OCRConfig:
    enabled: bool = True
    languages: list[str] = field(default_factory=lambda: ["rus", "eng"])
    pdf_max_pages: int = 12
    first_pages: int = 5
    last_pages: int = 3
    timeout_seconds: int = 60
    render_dpi: int = 200
    min_text_quality: float = 0.55

    @property
    def language_spec(self) -> str:
        """Строка языков для Tesseract, например ``rus+eng`` (раздел 16 ТЗ)."""
        return "+".join(self.languages) if self.languages else "rus+eng"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OCRConfig:
        cfg = cls()
        if "enabled" in data:
            cfg.enabled = _as_bool(data["enabled"], "ocr.enabled")
        if "languages" in data:
            langs = data["languages"]
            if not isinstance(langs, list) or not all(isinstance(x, str) for x in langs):
                raise ConfigError("Параметр «ocr.languages» должен быть списком строк.")
            cfg.languages = [x.strip() for x in langs if x.strip()] or ["rus", "eng"]
        if "pdf_max_pages" in data:
            cfg.pdf_max_pages = _as_int(data["pdf_max_pages"], "ocr.pdf_max_pages", 1, 1000)
        if "first_pages" in data:
            cfg.first_pages = _as_int(data["first_pages"], "ocr.first_pages", 0, 1000)
        if "last_pages" in data:
            cfg.last_pages = _as_int(data["last_pages"], "ocr.last_pages", 0, 1000)
        if "timeout_seconds" in data:
            cfg.timeout_seconds = _as_int(data["timeout_seconds"], "ocr.timeout_seconds", 5, 3600)
        if "render_dpi" in data:
            cfg.render_dpi = _as_int(data["render_dpi"], "ocr.render_dpi", 72, 600)
        if "min_text_quality" in data:
            cfg.min_text_quality = _clamp(
                data["min_text_quality"], 0.0, 1.0, "ocr.min_text_quality"
            )
        return cfg


@dataclass(slots=True)
class NamingConfig:
    max_filename_length: int = 160
    max_persons_in_filename: int = 2
    max_organizations_in_filename: int = 1
    confidence_threshold: float = 0.88
    separator: str = "_"
    allow_filesystem_date_fallback: bool = True
    preserve_good_names: bool = True
    #: Добавлять время в имя фотографий, видео и аудиозаписей. Время берётся
    #: только из метаданных съёмки: у документов и у снимков без EXIF его нет.
    include_capture_time: bool = True
    #: Предлагать имена и для вложенных папок.
    rename_folders: bool = True
    date_format: str = "DD.MM.YYYY"
    order: str = "type-first"
    max_segments: int = 3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NamingConfig:
        cfg = cls()
        if "max_filename_length" in data:
            cfg.max_filename_length = _as_int(
                data["max_filename_length"], "naming.max_filename_length", 24, 240
            )
        if "max_persons_in_filename" in data:
            cfg.max_persons_in_filename = _as_int(
                data["max_persons_in_filename"], "naming.max_persons_in_filename", 0, 10
            )
        if "max_organizations_in_filename" in data:
            cfg.max_organizations_in_filename = _as_int(
                data["max_organizations_in_filename"], "naming.max_organizations_in_filename", 0, 10
            )
        if "confidence_threshold" in data:
            cfg.confidence_threshold = _clamp(
                data["confidence_threshold"], 0.0, 1.0, "naming.confidence_threshold"
            )
        if "separator" in data:
            sep = str(data["separator"])
            if not sep or any(ch in sep for ch in '<>:"/\\|?*'):
                raise ConfigError("Параметр «naming.separator» содержит недопустимые символы.")
            cfg.separator = sep
        if "allow_filesystem_date_fallback" in data:
            cfg.allow_filesystem_date_fallback = _as_bool(
                data["allow_filesystem_date_fallback"], "naming.allow_filesystem_date_fallback"
            )
        if "date_format" in data:
            from docrenamer.naming.dates import DATE_FORMATS

            value = str(data["date_format"]).strip().upper()
            if value not in DATE_FORMATS:
                allowed = ", ".join(sorted(DATE_FORMATS))
                raise ConfigError(
                    f"Параметр «naming.date_format» допускает только: {allowed}."
                )
            cfg.date_format = value
        if "order" in data:
            from docrenamer.naming.builder import NAME_ORDERS

            value = str(data["order"]).strip().lower()
            if value not in NAME_ORDERS:
                allowed = ", ".join(sorted(NAME_ORDERS))
                raise ConfigError(f"Параметр «naming.order» допускает только: {allowed}.")
            cfg.order = value
        if "max_segments" in data:
            cfg.max_segments = _as_int(data["max_segments"], "naming.max_segments", 2, 8)
        if "rename_folders" in data:
            cfg.rename_folders = _as_bool(data["rename_folders"], "naming.rename_folders")
        if "include_capture_time" in data:
            cfg.include_capture_time = _as_bool(
                data["include_capture_time"], "naming.include_capture_time"
            )
        if "preserve_good_names" in data:
            cfg.preserve_good_names = _as_bool(
                data["preserve_good_names"], "naming.preserve_good_names"
            )
        return cfg


@dataclass(slots=True)
class MediaConfig:
    use_exif: bool = True
    use_ffprobe: bool = True
    include_device: bool = True
    include_gps_coordinates: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MediaConfig:
        cfg = cls()
        for name in ("use_exif", "use_ffprobe", "include_device", "include_gps_coordinates"):
            if name in data:
                setattr(cfg, name, _as_bool(data[name], f"media.{name}"))
        return cfg


@dataclass(slots=True)
class ArchivesConfig:
    inspect_only: bool = True
    max_entries_to_analyze: int = 500

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArchivesConfig:
        cfg = cls()
        if "inspect_only" in data:
            if not _as_bool(data["inspect_only"], "archives.inspect_only"):
                raise ConfigError(
                    "Распаковка архивов запрещена в MVP: «archives.inspect_only» "
                    "не может быть false."
                )
        if "max_entries_to_analyze" in data:
            cfg.max_entries_to_analyze = _as_int(
                data["max_entries_to_analyze"], "archives.max_entries_to_analyze", 1, 100_000
            )
        return cfg


@dataclass(slots=True)
class UpdateConfig:
    """Проверка обновлений (см. docrenamer_updater).

    Сама программа в сеть не выходит: она лишь запускает отдельный
    исполняемый файл обновления, и только по команде пользователя.
    """

    #: Показывать кнопку проверки обновлений.
    enabled: bool = True
    #: Проверять при запуске. По умолчанию выключено: без явной команды
    #: программа не обращается никуда.
    check_on_start: bool = False
    repository: str = "AB00Rcraft/docrenamer"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateConfig:
        cfg = cls()
        for name in ("enabled", "check_on_start"):
            if name in data:
                setattr(cfg, name, _as_bool(data[name], f"update.{name}"))
        if "repository" in data:
            value = str(data["repository"]).strip()
            if "/" not in value or " " in value:
                raise ConfigError(
                    "Параметр «update.repository» должен быть вида «владелец/репозиторий»."
                )
            cfg.repository = value
        return cfg


@dataclass(slots=True)
class LearningConfig:
    """Журнал обучения: на чём алгоритм имён ошибается.

    Пишется на диск в обезличенном виде и никуда не уходит сам. Отправку
    выполняет отдельная программа обновления и только по прямой команде
    человека.
    """

    #: Вести журнал.
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningConfig:
        cfg = cls()
        if "enabled" in data:
            cfg.enabled = _as_bool(data["enabled"], "learning.enabled")
        return cfg


@dataclass(slots=True)
class LimitsConfig:
    max_text_chars_for_ai: int = 24_000
    max_plaintext_file_mb: int = 50
    max_single_file_mb: int = 4096
    max_text_chars_total: int = 400_000
    subprocess_timeout_seconds: int = 120
    max_archive_entries: int = 5000

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LimitsConfig:
        cfg = cls()
        if "max_text_chars_for_ai" in data:
            cfg.max_text_chars_for_ai = _as_int(
                data["max_text_chars_for_ai"], "limits.max_text_chars_for_ai", 500, 1_000_000
            )
        if "max_plaintext_file_mb" in data:
            cfg.max_plaintext_file_mb = _as_int(
                data["max_plaintext_file_mb"], "limits.max_plaintext_file_mb", 1, 4096
            )
        if "max_single_file_mb" in data:
            cfg.max_single_file_mb = _as_int(
                data["max_single_file_mb"], "limits.max_single_file_mb", 1, 1_048_576
            )
        if "max_text_chars_total" in data:
            cfg.max_text_chars_total = _as_int(
                data["max_text_chars_total"], "limits.max_text_chars_total", 1000, 20_000_000
            )
        if "subprocess_timeout_seconds" in data:
            cfg.subprocess_timeout_seconds = _as_int(
                data["subprocess_timeout_seconds"], "limits.subprocess_timeout_seconds", 5, 3600
            )
        if "max_archive_entries" in data:
            cfg.max_archive_entries = _as_int(
                data["max_archive_entries"], "limits.max_archive_entries", 1, 1_000_000
            )
        return cfg


@dataclass(slots=True)
class Config:
    """Полная конфигурация приложения."""

    strict_local_mode: bool = True
    language: str = "ru-RU"
    internal_text_encoding: str = "utf-8"
    human_log_encoding: str = "utf-8"
    unicode_normalization: str = "NFC"
    recursive: bool = True
    dry_run_default: bool = True
    forensic_mode: bool = False
    allow_system_binaries: bool = True

    ai: AIConfig = field(default_factory=AIConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    naming: NamingConfig = field(default_factory=NamingConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    archives: ArchivesConfig = field(default_factory=ArchivesConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)

    #: Откуда конфиг был прочитан (для логов). Не участвует в fingerprint.
    source_file: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        if not isinstance(data, dict):
            raise ConfigError("Файл конфигурации должен содержать JSON-объект.")

        cfg = cls()
        if "strict_local_mode" in data:
            if not _as_bool(data["strict_local_mode"], "strict_local_mode"):
                raise ConfigError(
                    "STRICT LOCAL MODE нельзя отключить: программа не имеет "
                    "сетевой функциональности (раздел 3 ТЗ)."
                )
        if "language" in data:
            cfg.language = str(data["language"]) or "ru-RU"
        for name in ("internal_text_encoding", "human_log_encoding"):
            if name in data:
                enc = str(data[name]).lower()
                if enc not in {"utf-8", "utf-8-sig"}:
                    raise ConfigError(
                        f"Параметр «{name}» допускает только utf-8 или utf-8-sig "
                        "(раздел 14A.6 ТЗ)."
                    )
                setattr(cfg, name, enc)
        if "unicode_normalization" in data:
            norm = str(data["unicode_normalization"]).upper()
            if norm != "NFC":
                raise ConfigError(
                    "Допустима только нормализация NFC: NFKC разрушает «№», "
                    "кавычки и тире (раздел 14A.4 ТЗ)."
                )
        for name in ("recursive", "dry_run_default", "forensic_mode", "allow_system_binaries"):
            if name in data:
                setattr(cfg, name, _as_bool(data[name], name))

        cfg.ai = AIConfig.from_dict(data.get("ai", {}) or {})
        cfg.ocr = OCRConfig.from_dict(data.get("ocr", {}) or {})
        cfg.naming = NamingConfig.from_dict(data.get("naming", {}) or {})
        cfg.media = MediaConfig.from_dict(data.get("media", {}) or {})
        cfg.archives = ArchivesConfig.from_dict(data.get("archives", {}) or {})
        cfg.limits = LimitsConfig.from_dict(data.get("limits", {}) or {})
        cfg.update = UpdateConfig.from_dict(data.get("update", {}) or {})
        cfg.learning = LearningConfig.from_dict(data.get("learning", {}) or {})
        return cfg

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for f in fields(self):
            if f.name == "source_file":
                continue
            value = getattr(self, f.name)
            if is_dataclass(value) and not isinstance(value, type):
                result[f.name] = asdict(value)
            else:
                result[f.name] = value
        return result

    def fingerprint(self) -> str:
        """Стабильный отпечаток настроек для manifest (раздел 51 ТЗ)."""
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def save(self, path: Path) -> None:
        """Атомарная запись собственного служебного файла (раздел 84 ТЗ)."""
        write_json_atomic(path, self.to_dict())


def load_config(path: Path | None = None, paths: AppPaths | None = None) -> Config:
    """Прочитать конфигурацию.

    Отсутствующий файл — не ошибка: используются значения по умолчанию,
    совпадающие с примером из раздела 56 ТЗ.
    """
    app_paths = paths or default_paths()
    config_path = Path(path) if path else app_paths.config_file
    if not config_path.is_file():
        cfg = Config()
        cfg.source_file = ""
        return cfg
    try:
        raw = config_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"Не удалось прочитать файл конфигурации: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Файл конфигурации содержит некорректный JSON (строка {exc.lineno}): {exc.msg}"
        ) from exc
    cfg = Config.from_dict(data)
    cfg.source_file = str(config_path)
    return cfg


def write_json_atomic(path: Path, data: Any, encoding: str = "utf-8") -> None:
    """Атомарно записать собственный служебный JSON-файл.

    Последовательность раздела 84 ТЗ: ``.tmp`` → flush → fsync → atomic replace.
    ``os.replace`` здесь допустим: цель — служебный файл приложения, а не
    пользовательский документ (раздел 77 ТЗ).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def load_document_types(
    path: Path | None = None, paths: AppPaths | None = None
) -> list[dict[str, Any]]:
    """Прочитать расширяемый словарь типов документов (раздел 39 ТЗ)."""
    app_paths = paths or default_paths()
    types_path = Path(path) if path else app_paths.document_types_file
    if not types_path.is_file():
        return []
    try:
        data = json.loads(types_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Не удалось прочитать словарь типов документов: {exc}") from exc
    types = data.get("types") if isinstance(data, dict) else data
    if not isinstance(types, list):
        raise ConfigError("Словарь типов документов должен содержать список «types».")
    result: list[dict[str, Any]] = []
    for entry in types:
        if not isinstance(entry, dict) or not entry.get("canonical_name"):
            continue
        result.append(
            {
                "canonical_name": str(entry["canonical_name"]),
                "aliases": [str(a) for a in entry.get("aliases", []) if str(a).strip()],
                "markers": [str(m) for m in entry.get("markers", []) if str(m).strip()],
                "priority": int(entry.get("priority", 0)),
                "filename_abbreviation": str(
                    entry.get("filename_abbreviation") or entry["canonical_name"]
                ),
            }
        )
    return result
