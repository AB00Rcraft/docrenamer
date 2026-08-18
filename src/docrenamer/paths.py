"""Portable-раскладка и поиск bundled runtime binaries (разделы 4, 60, 62 ТЗ).

Все внутренние пути вычисляются относительно расположения исполняемого файла.
Никакой привязки к букве диска, `%APPDATA%` или пользовательскому профилю.
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

#: Имена подкаталогов portable-раскладки.
CONFIG_DIRNAME = "config"
RUNTIME_DIRNAME = "runtime"
MODELS_DIRNAME = "models"
LOGS_DIRNAME = "logs"
MANIFESTS_DIRNAME = "manifests"
TEMP_DIRNAME = "runtime_temp"

#: Каталоги внутри raскладки, которые сканер обязан исключать из обработки.
SERVICE_DIRNAMES = frozenset(
    {CONFIG_DIRNAME, RUNTIME_DIRNAME, MODELS_DIRNAME, LOGS_DIRNAME, MANIFESTS_DIRNAME, TEMP_DIRNAME}
)


def is_frozen() -> bool:
    """Запущены ли мы из собранного PyInstaller-дистрибутива."""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Корень приложения.

    В собранном виде — каталог рядом с ``DocRenamer.exe``.
    В исходном виде — корень репозитория (на два уровня выше пакета).
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundled_root() -> Path:
    """Каталог ресурсов, вшитых в сборку.

    PyInstaller распаковывает данные рядом с исполняемым файлом (onedir) либо
    во временный каталог (onefile). Используется как запасной источник
    конфигурации, если пользовательский ``config/`` рядом с программой
    отсутствует — программа обязана запускаться и в этом случае.
    """
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(meipass)
    return app_root()


def _exe(name: str) -> str:
    """Имя исполняемого файла с учётом платформы."""
    return f"{name}.exe" if os.name == "nt" else name


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Разрешённые пути portable-раскладки."""

    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / CONFIG_DIRNAME

    @property
    def bundled_config_dir(self) -> Path:
        """Конфигурация по умолчанию, вшитая в сборку."""
        return bundled_root() / CONFIG_DIRNAME

    def _config_resource(self, name: str) -> Path:
        """Файл конфигурации: сначала рядом с программой, затем вшитый в сборку."""
        external = self.config_dir / name
        if external.is_file():
            return external
        bundled = self.bundled_config_dir / name
        return bundled if bundled.is_file() else external

    @property
    def config_file(self) -> Path:
        return self._config_resource("config.json")

    @property
    def document_types_file(self) -> Path:
        return self._config_resource("document_types.json")

    @property
    def runtime_dir(self) -> Path:
        return self.root / RUNTIME_DIRNAME

    @property
    def models_dir(self) -> Path:
        return self.root / MODELS_DIRNAME

    @property
    def logs_dir(self) -> Path:
        return self.root / LOGS_DIRNAME

    @property
    def manifests_dir(self) -> Path:
        return self.root / MANIFESTS_DIRNAME

    @property
    def temp_dir(self) -> Path:
        return self.root / TEMP_DIRNAME

    @property
    def tessdata_dir(self) -> Path:
        return self.runtime_dir / "tesseract" / "tessdata"

    def own_paths(self) -> tuple[Path, ...]:
        """Каталоги приложения, которые нельзя обрабатывать как пользовательские."""
        return (
            self.root,
            self.config_dir,
            self.runtime_dir,
            self.models_dir,
            self.logs_dir,
            self.manifests_dir,
            self.temp_dir,
        )

    def ensure_service_dirs(self) -> None:
        """Создать собственные служебные каталоги (не трогая пользовательские данные)."""
        for directory in (self.logs_dir, self.manifests_dir, self.temp_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # --- bundled binaries -------------------------------------------------

    def _bundled(self, subdir: str, name: str) -> Path:
        return self.runtime_dir / subdir / _exe(name)

    def find_binary(self, subdir: str, name: str, allow_system: bool = True) -> Path | None:
        """Найти локальный бинарник.

        Приоритет у bundled-версии внутри ``runtime/``. Системный PATH — только
        запасной вариант для разработки; это не нарушает STRICT_LOCAL_MODE,
        поскольку сетевых обращений не выполняется. Загрузка из сети не
        производится ни при каких условиях (разделы 3, 61 ТЗ).
        """
        bundled = self._bundled(subdir, name)
        if bundled.is_file():
            return bundled
        if allow_system:
            found = shutil.which(name)
            if found:
                return Path(found)
        return None

    def llama_cli(self, allow_system: bool = True) -> Path | None:
        return self.find_binary("llama", "llama-cli", allow_system)

    def tesseract(self, allow_system: bool = True) -> Path | None:
        return self.find_binary("tesseract", "tesseract", allow_system)

    def exiftool(self, allow_system: bool = True) -> Path | None:
        return self.find_binary("exiftool", "exiftool", allow_system)

    def ffprobe(self, allow_system: bool = True) -> Path | None:
        return self.find_binary("ffmpeg", "ffprobe", allow_system)

    def sevenzip(self, allow_system: bool = True) -> Path | None:
        for subdir, name in (("7zip", "7z"), ("7zip", "7za"), ("7zip", "7zz")):
            found = self.find_binary(subdir, name, allow_system)
            if found:
                return found
        return None

    # --- временные данные -------------------------------------------------

    def session_temp(self, session_id: str) -> Path:
        """Каталог временных данных сессии (раздел 62 ТЗ)."""
        return self.temp_dir / session_id


def default_paths() -> AppPaths:
    """Пути по умолчанию для текущего размещения приложения."""
    return AppPaths(root=app_root())


def new_session_id() -> str:
    """Идентификатор сессии для temp-каталога, логов и manifest."""
    return uuid.uuid4().hex[:16]


def resolve_model_path(paths: AppPaths, configured: str) -> Path:
    """Разрешить путь модели относительно корня приложения.

    Относительный путь из config трактуется относительно ``app_root()``,
    а не текущего рабочего каталога — иначе portable-запуск ломается.
    """
    candidate = Path(configured)
    if candidate.is_absolute():
        return candidate
    return (paths.root / candidate).resolve()
