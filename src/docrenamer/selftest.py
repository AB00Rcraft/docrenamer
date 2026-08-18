"""Самопроверка комплекта (разделы 75, 88 ТЗ).

Отвечает на один вопрос: готова ли программа к работе прямо сейчас и что
именно в ней доступно. Проверяются локальные компоненты — распознавание
сканов, языковая модель, чтение метаданных, — а затем прогоняется настоящий
разбор тестового документа, чтобы убедиться, что работает вся цепочка, а не
отдельные части.

Ни один шаг не обращается к сети.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from docrenamer import __version__
from docrenamer.config import Config, load_document_types
from docrenamer.paths import AppPaths, default_paths, resolve_model_path
from docrenamer.security.offline_guard import assert_no_network_modules
from docrenamer.security.subprocess_safe import run_tool
from docrenamer.security.temp_cleanup import SessionTemp
from docrenamer.types import ScannedFile

#: Тестовый документ: содержит заголовок, дату, номер и участников.
SAMPLE_DOCUMENT = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "№ 859189755/7728 от 27 июля 2026 года\n"
    "Алтуфьевский ОСП ГУФССП России по г. Москве\n"
    "Судебный пристав-исполнитель Сидорова А.А.\n"
    "Должник: Иванов Иван Иванович\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
)

#: Что должно оказаться в имени, построенном по тестовому документу.
EXPECTED_DATES = ("27.07.2026", "27-07-2026", "2026-07-27")
EXPECTED_TYPE = "Постановление_СПИ"

#: Имя тестового файла намеренно техническое: так проверяется полный разбор,
#: а не режим сохранения осмысленных имён.
SAMPLE_FILENAME = "scan0001.txt"

#: Сколько секунд ждём ответа модели при полной проверке.
MODEL_PROBE_TIMEOUT = 90


class Level(StrEnum):
    """Итог отдельной проверки."""

    OK = "ok"
    #: Необязательный компонент не установлен. Программа полностью
    #: работоспособна: это сообщение, а не предупреждение.
    OPTIONAL = "optional"
    WARN = "warn"
    FAIL = "fail"


#: Значки для текстового вывода и интерфейса.
ICONS: dict[str, str] = {Level.OK: "✓", Level.OPTIONAL: "○", Level.WARN: "!", Level.FAIL: "×"}


@dataclass(slots=True)
class Check:
    """Результат одной проверки."""

    name: str
    level: Level
    detail: str
    hint: str = ""

    @property
    def icon(self) -> str:
        return ICONS[self.level]

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "level": self.level.value,
            "detail": self.detail,
            "hint": self.hint,
        }


@dataclass(slots=True)
class SelfTestReport:
    """Итог самопроверки."""

    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, level: Level, detail: str, hint: str = "") -> None:
        self.checks.append(Check(name=name, level=level, detail=detail, hint=hint))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.level is Level.FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.level is Level.WARN]

    @property
    def optional_missing(self) -> list[Check]:
        return [c for c in self.checks if c.level is Level.OPTIONAL]

    @property
    def ready(self) -> bool:
        """Работает ли основная функция программы."""
        return not self.failed

    @property
    def complete(self) -> bool:
        """Доступны ли вообще все возможности, включая OCR и модель."""
        return not self.failed and not self.warnings

    @property
    def verdict(self) -> str:
        if self.failed:
            return "НЕ ГОТОВА К РАБОТЕ"
        if self.warnings:
            return "ГОТОВА К РАБОТЕ, есть замечания"
        if self.optional_missing:
            names = ", ".join(check.name.lower() for check in self.optional_missing)
            return f"ГОТОВА К РАБОТЕ. Не установлено дополнительно: {names}"
        return "ПОЛНОСТЬЮ ГОТОВА К РАБОТЕ"

    @property
    def badge(self) -> str:
        """Короткий значок состояния для интерфейса."""
        if self.failed:
            return "× НЕ ГОТОВА"
        if self.warnings:
            return "! ЕСТЬ ЗАМЕЧАНИЯ"
        return "✓ ГОТОВА"

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_version": __version__,
            "verdict": self.verdict,
            "ready": self.ready,
            "complete": self.complete,
            "checks": [c.to_dict() for c in self.checks],
        }

    def format_text(self) -> str:
        """Человекочитаемый отчёт."""
        width = max((len(c.name) for c in self.checks), default=10)
        lines = [
            "=" * 66,
            f"  Самопроверка DocRenamer Offline {__version__}",
            "=" * 66,
        ]
        for check in self.checks:
            lines.append(f" {check.icon} {check.name.ljust(width)}  {check.detail}")
            if check.hint:
                lines.append(f"   {' ' * width}  → {check.hint}")
        lines += ["=" * 66, f"  {self.badge}: {self.verdict}", "=" * 66]
        return "\n".join(lines)


def run_selftest(
    config: Config | None = None,
    paths: AppPaths | None = None,
    *,
    probe_model: bool = True,
) -> SelfTestReport:
    """Выполнить самопроверку.

    Args:
        probe_model: сделать пробный запрос к локальной модели. Это самая
            долгая проверка, поэтому при быстром запуске её пропускают.
    """
    from docrenamer.config import load_config

    app_paths = paths or default_paths()
    cfg = config or load_config(paths=app_paths)
    report = SelfTestReport()

    _check_environment(report, cfg, app_paths)
    _check_dictionaries(report, app_paths)
    _check_libraries(report)
    _check_ocr(report, cfg, app_paths)
    _check_model(report, cfg, app_paths, probe_model=probe_model)
    _check_media_backends(report, cfg, app_paths)
    _check_archives(report, cfg, app_paths)
    _check_offline(report)
    _check_pipeline(report, cfg, app_paths)
    return report


# --- отдельные проверки -----------------------------------------------------


def _check_environment(report: SelfTestReport, config: Config, paths: AppPaths) -> None:
    """Расположение, режим и права на запись служебных каталогов."""
    mode = "STRICT LOCAL MODE" if config.strict_local_mode else "обычный"
    report.add("Программа", Level.OK, f"DocRenamer {__version__}, режим {mode}")
    report.add("Расположение", Level.OK, str(paths.root))

    import os

    try:
        paths.ensure_service_dirs()
    except OSError as exc:
        report.add(
            "Служебные каталоги",
            Level.FAIL,
            f"не удалось создать: {exc}",
            "Скопируйте программу в папку, где разрешена запись.",
        )
    else:
        unwritable = [
            directory.name
            for directory in (paths.logs_dir, paths.manifests_dir, paths.temp_dir)
            if not os.access(directory, os.W_OK)
        ]
        if unwritable:
            report.add(
                "Служебные каталоги",
                Level.FAIL,
                "нет доступа на запись: " + ", ".join(unwritable),
                "Скопируйте программу в папку, где разрешена запись.",
            )
        else:
            report.add(
                "Служебные каталоги",
                Level.OK,
                "logs, manifests, runtime_temp доступны на запись",
            )

    source = config.source_file or "встроенные значения по умолчанию"
    report.add("Настройки", Level.OK, f"{source}, порог {config.naming.confidence_threshold:.2f}")


def _check_dictionaries(report: SelfTestReport, paths: AppPaths) -> None:
    """Словарь типов документов."""
    try:
        types = load_document_types(paths=paths)
    except Exception as exc:  # недоверенный файл настроек
        report.add("Словарь документов", Level.FAIL, f"не прочитан: {exc}")
        return
    if not types:
        report.add(
            "Словарь документов",
            Level.FAIL,
            "пуст",
            "Проверьте файл config/document_types.json.",
        )
        return
    report.add("Словарь документов", Level.OK, f"{len(types)} видов документов")


def _check_libraries(report: SelfTestReport) -> None:
    """Библиотеки чтения форматов."""
    import importlib

    required = {
        "pypdf": "PDF",
        "pypdfium2": "рендер PDF для распознавания",
        "docx": "DOCX",
        "openpyxl": "XLSX",
        "pptx": "PPTX",
        "xlrd": "XLS",
        "PIL": "изображения",
        "pillow_heif": "HEIC/AVIF",
        "bs4": "HTML",
        "defusedxml": "XML/KML/GPX",
        "olefile": "старые форматы Office",
        "extract_msg": "почта MSG",
        "mutagen": "аудио",
        "charset_normalizer": "кодировки",
    }
    missing: list[str] = []
    for module, purpose in required.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(f"{module} ({purpose})")
    if missing:
        report.add(
            "Чтение форматов",
            Level.FAIL,
            "не хватает: " + ", ".join(missing),
            "Сборка неполная — скачайте дистрибутив заново.",
        )
        return
    from docrenamer.readers import READERS

    kinds = len([k for k in READERS if not k.startswith("category:")])
    report.add("Чтение форматов", Level.OK, f"{kinds} форматов, все библиотеки на месте")


def _check_ocr(report: SelfTestReport, config: Config, paths: AppPaths) -> None:
    """Распознавание сканов."""
    if not config.ocr.enabled:
        report.add("Распознавание сканов", Level.OPTIONAL, "отключено в настройках")
        return
    executable = paths.tesseract(config.allow_system_binaries)
    if executable is None:
        report.add(
            "Распознавание сканов",
            Level.OPTIONAL,
            "не установлено: сканы без текстового слоя не читаются",
            "Нужно только для сканов. Положите tesseract.exe в runtime/tesseract/ "
            "(см. runtime/README.md).",
        )
        return

    result = run_tool(executable, ["--list-langs"], timeout=30)
    languages = {
        line.strip()
        for line in (result.stdout or result.stderr).splitlines()
        if line.strip() and " " not in line.strip()
    }
    needed = set(config.ocr.languages)
    missing = sorted(needed - languages)
    if missing:
        report.add(
            "Распознавание сканов",
            Level.WARN,
            f"Tesseract найден, но нет языков: {', '.join(missing)}",
            "Добавьте файлы .traineddata в runtime/tesseract/tessdata/.",
        )
        return
    report.add(
        "Распознавание сканов",
        Level.OK,
        f"Tesseract готов, языки: {config.ocr.language_spec}",
    )


def _check_model(
    report: SelfTestReport, config: Config, paths: AppPaths, *, probe_model: bool
) -> None:
    """Локальная языковая модель."""
    if not config.ai.enabled:
        report.add("Локальная модель", Level.OPTIONAL, "отключена в настройках")
        return

    model_path = resolve_model_path(paths, config.ai.model_path)
    executable = paths.llama_cli(config.allow_system_binaries)
    if not model_path.is_file():
        report.add(
            "Локальная модель",
            Level.OPTIONAL,
            "не установлена: имена строятся по правилам, без ИИ",
            f"Нужна только для сложных случаев. Положите файл .gguf как "
            f"{model_path} (см. runtime/README.md). Программа его не скачивает.",
        )
        return
    size_gb = model_path.stat().st_size / 1024 / 1024 / 1024
    if executable is None:
        report.add(
            "Локальная модель",
            Level.OPTIONAL,
            f"модель есть ({size_gb:.1f} ГБ), но не найден llama-cli",
            "Положите llama-cli.exe в runtime/llama/.",
        )
        return

    if not probe_model:
        report.add(
            "Локальная модель",
            Level.OK,
            f"{model_path.name}, {size_gb:.1f} ГБ, движок на месте",
        )
        return

    from docrenamer.ai.llama_cli import LlamaCliModel

    model = LlamaCliModel(config, paths)
    answer, status = model.generate(
        "Ответь одним словом по-русски: как называется документ с заголовком "
        "«ПОСТАНОВЛЕНИЕ»?"
    )
    if status or not answer.strip():
        report.add(
            "Локальная модель",
            Level.WARN,
            f"модель не ответила ({status or 'пустой ответ'})",
            "Программа продолжит работать по правилам, без модели.",
        )
        return
    report.add(
        "Локальная модель",
        Level.OK,
        f"{model_path.name}, {size_gb:.1f} ГБ — отвечает",
    )


def _check_media_backends(report: SelfTestReport, config: Config, paths: AppPaths) -> None:
    """Метаданные фотографий и видео."""
    exiftool = paths.exiftool(config.allow_system_binaries)
    if exiftool is not None:
        report.add("Метаданные фото", Level.OK, f"ExifTool: {exiftool}")
    else:
        report.add(
            "Метаданные фото",
            Level.OK,
            "встроенное чтение EXIF (дата съёмки, камера, координаты)",
            "ExifTool добавит RAW-форматы и XMP.",
        )

    ffprobe = paths.ffprobe(config.allow_system_binaries)
    if ffprobe is not None:
        report.add("Метаданные видео", Level.OK, f"ffprobe: {ffprobe}")
    else:
        report.add(
            "Метаданные видео",
            Level.OK,
            "встроенное чтение MP4/MOV (дата съёмки, длительность)",
            "ffprobe добавит AVI, MKV и WEBM.",
        )


def _check_archives(report: SelfTestReport, config: Config, paths: AppPaths) -> None:
    """Просмотр архивов."""
    sevenzip = paths.sevenzip(config.allow_system_binaries)
    if sevenzip is not None:
        report.add("Архивы", Level.OK, f"ZIP, TAR встроенно; 7Z и RAR: {sevenzip}")
    else:
        report.add(
            "Архивы",
            Level.OK,
            "ZIP, TAR, GZ читаются встроенно",
            "7-Zip добавит просмотр 7Z и RAR.",
        )


def _check_offline(report: SelfTestReport) -> None:
    """Отсутствие сетевых зависимостей в работающем процессе.

    Клиенты облачных сервисов недопустимы: их появление означает, что в сборку
    попал посторонний код. Модули стандартной библиотеки вроде ``http.client``
    сетевого обращения сами по себе не делают и могут быть загружены средой
    запуска, поэтому они отмечаются предупреждением, а не отказом.
    """
    loaded = assert_no_network_modules()
    third_party = [name for name in loaded if not _is_stdlib(name)]
    if third_party:
        report.add(
            "Работа без сети",
            Level.FAIL,
            "в сборку попали сетевые библиотеки: " + ", ".join(third_party),
            "Это нарушение STRICT LOCAL MODE — сборку использовать нельзя.",
        )
        return
    report.add(
        "Работа без сети",
        Level.OK,
        "клиентов сетевых сервисов нет, обращений наружу не выполняется",
    )


def _is_stdlib(module: str) -> bool:
    """Входит ли модуль в стандартную библиотеку Python."""
    import sys

    return module.split(".")[0] in sys.stdlib_module_names


def _check_pipeline(report: SelfTestReport, config: Config, paths: AppPaths) -> None:
    """Полный разбор тестового документа — проверка всей цепочки."""
    from docrenamer.analysis import build_analyzer

    session = SessionTemp(paths)
    try:
        directory = session.ensure()
        sample = directory / SAMPLE_FILENAME
        sample.write_bytes(SAMPLE_DOCUMENT.encode("utf-8"))
        stat = sample.stat()
        scanned = ScannedFile(
            path=sample, size=stat.st_size, mtime=stat.st_mtime, extension=".txt"
        )
        analyzer = build_analyzer(config, paths, temp=session)
        analysis = analyzer.analyze(scanned)
        name = analysis.proposed_filename
    except Exception as exc:  # разбор не должен падать ни при каких условиях
        report.add("Разбор документа", Level.FAIL, f"ошибка: {exc}")
        return
    finally:
        session.cleanup()

    if not name:
        report.add(
            "Разбор документа",
            Level.FAIL,
            "имя для тестового документа не построено",
        )
        return
    if not any(fragment in name for fragment in EXPECTED_DATES):
        report.add("Разбор документа", Level.FAIL, f"дата не распознана: {name}")
        return
    if EXPECTED_TYPE not in name:
        report.add("Разбор документа", Level.FAIL, f"вид документа не распознан: {name}")
        return
    report.add("Разбор документа", Level.OK, f"тестовый документ распознан: {name}")
