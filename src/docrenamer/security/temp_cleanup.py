"""Временные данные сессии (раздел 62 ТЗ).

OCR-изображения и промежуточные данные не должны оставаться на чужом
компьютере. Удаление разрешено исключительно внутри ``runtime_temp/``: любая
попытка удалить что-то за его пределами считается ошибкой программы.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from types import TracebackType

from docrenamer.paths import AppPaths, default_paths, new_session_id

#: Возраст, после которого чужая сессия считается брошенной, секунды.
STALE_SESSION_SECONDS = 24 * 3600


class TempGuardError(RuntimeError):
    """Попытка удалить путь за пределами ``runtime_temp``."""


def _assert_inside_temp(path: Path, temp_root: Path) -> None:
    """Убедиться, что путь лежит внутри каталога временных данных."""
    try:
        resolved = path.resolve()
        root = temp_root.resolve()
    except OSError as exc:  # pragma: no cover — недоступная ФС
        raise TempGuardError(f"Не удалось проверить путь: {exc}") from exc
    if resolved != root and not resolved.is_relative_to(root):
        raise TempGuardError(
            f"Удаление разрешено только внутри {root}, получен путь {resolved}"
        )


def purge(path: Path, temp_root: Path) -> None:
    """Удалить временный файл или каталог после проверки границ."""
    _assert_inside_temp(path, temp_root)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_stale_sessions(
    paths: AppPaths | None = None,
    *,
    max_age_seconds: int = STALE_SESSION_SECONDS,
    keep: str = "",
) -> int:
    """Удалить каталоги брошенных сессий при старте (раздел 62 ТЗ)."""
    app_paths = paths or default_paths()
    temp_root = app_paths.temp_dir
    if not temp_root.is_dir():
        return 0
    removed = 0
    now = time.time()
    for entry in temp_root.iterdir():
        if entry.name == keep or entry.name.startswith("."):
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            continue
        if age < max_age_seconds:
            continue
        purge(entry, temp_root)
        removed += 1
    return removed


class SessionTemp:
    """Каталог временных данных одной сессии.

    Используется как контекстный менеджер: по выходу каталог удаляется целиком.
    """

    def __init__(self, paths: AppPaths | None = None, session_id: str | None = None) -> None:
        self.paths = paths or default_paths()
        self.session_id = session_id or new_session_id()
        self.root = self.paths.session_temp(self.session_id)

    def ensure(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def path(self, name: str) -> Path:
        """Путь внутри сессионного каталога."""
        candidate = self.root / name
        _assert_inside_temp(candidate, self.paths.temp_dir)
        return candidate

    def cleanup(self) -> None:
        if self.root.exists():
            purge(self.root, self.paths.temp_dir)

    def __enter__(self) -> SessionTemp:
        self.ensure()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.cleanup()


def temp_dir_is_safe(paths: AppPaths | None = None) -> bool:
    """Не находится ли каталог временных данных в облачной синхронизации.

    OneDrive, Dropbox и подобные каталоги синхронизируют содержимое наружу, что
    противоречит разделу 62 ТЗ.
    """
    app_paths = paths or default_paths()
    text = str(app_paths.temp_dir).lower()
    markers: list[str] = ["onedrive", "dropbox", "yandexdisk", "google drive", "icloud"]
    if os.name == "nt":
        # Каталог профиля пользователя не предназначен для содержимого документов.
        markers.append("\\appdata\\")
    return not any(marker in text for marker in markers)
