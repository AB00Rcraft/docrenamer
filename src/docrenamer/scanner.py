"""Сканирование каталогов (раздел 9 ТЗ).

Сканер не открывает содержимое файлов: он только строит список кандидатов и
защищает обход от петель, symlink/junction-выходов за пределы дерева и от
попадания в системные и собственные служебные каталоги.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from docrenamer.paths import AppPaths, default_paths
from docrenamer.types import ScannedFile, nfc

#: Шаблоны игнорирования из раздела 9 ТЗ.
IGNORE_PATTERNS: tuple[str, ...] = (
    ".git",
    ".svn",
    "__pycache__",
    "node_modules",
    "$RECYCLE.BIN",
    "System Volume Information",
    "runtime_temp",
    "logs",
    "manifests",
    "Thumbs.db",
    "desktop.ini",
    "~$*",
    "*.tmp",
)

#: Дополнительные служебные объекты, которые не являются пользовательскими данными.
EXTRA_IGNORE_PATTERNS: tuple[str, ...] = (
    ".DS_Store",
    "._*",
    ".Spotlight-V100",
    ".Trashes",
    "*.crdownload",
    "*.part",
    "*.partial",
)

#: Системные каталоги, в которые запрещено заходить.
SYSTEM_DIRS_WINDOWS = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "c:\\$recycle.bin",
    "c:\\system volume information",
    "c:\\recovery",
)
SYSTEM_DIRS_POSIX = ("/proc", "/sys", "/dev", "/run", "/boot")


@dataclass(slots=True)
class ScanStats:
    """Статистика обхода для GUI и логов."""

    directories: int = 0
    folders_found: int = 0
    files_found: int = 0
    files_skipped: int = 0
    symlinks_skipped: int = 0
    loops_prevented: int = 0
    access_denied: int = 0
    by_extension: dict[str, int] = field(default_factory=dict)

    def note_extension(self, extension: str) -> None:
        key = extension.lower() or "<без расширения>"
        self.by_extension[key] = self.by_extension.get(key, 0) + 1

    def summary_ru(self) -> str:
        """Короткая сводка вида «PDF: 91 | DOCX: 32 | другое: 17»."""
        if not self.by_extension:
            return "Файлов не найдено"
        top = sorted(self.by_extension.items(), key=lambda kv: (-kv[1], kv[0]))
        head = top[:6]
        rest = sum(count for _, count in top[6:])
        parts = [f"{ext.lstrip('.').upper() or '—'}: {count}" for ext, count in head]
        if rest:
            parts.append(f"другое: {rest}")
        return " | ".join(parts)


def is_ignored_name(name: str, patterns: tuple[str, ...]) -> bool:
    """Совпадает ли имя с шаблоном игнорирования (без учёта регистра)."""
    lowered = name.lower()
    for pattern in patterns:
        pattern_lower = pattern.lower()
        if "*" in pattern_lower or "?" in pattern_lower or "[" in pattern_lower:
            if fnmatch.fnmatch(lowered, pattern_lower):
                return True
        elif lowered == pattern_lower:
            return True
    return False


def is_system_dir(path: Path) -> bool:
    """Является ли каталог системным."""
    text = str(path).lower().rstrip("\\/")
    if os.name == "nt":
        return any(text == d or text.startswith(d + "\\") for d in SYSTEM_DIRS_WINDOWS)
    return any(text == d or text.startswith(d + "/") for d in SYSTEM_DIRS_POSIX)


class Scanner:
    """Обход каталога с защитой от петель и выхода за пределы дерева."""

    def __init__(
        self,
        *,
        recursive: bool = True,
        paths: AppPaths | None = None,
        extra_ignores: tuple[str, ...] = (),
        follow_symlinks: bool = False,
    ) -> None:
        self.recursive = recursive
        self.paths = paths or default_paths()
        self.patterns = IGNORE_PATTERNS + EXTRA_IGNORE_PATTERNS + tuple(extra_ignores)
        self.follow_symlinks = follow_symlinks
        self.stats = ScanStats()
        #: Найденные подкаталоги — их тоже можно переименовать.
        self.folders: list[Path] = []
        self._visited: set[tuple[int, int]] = set()
        self._own_paths: set[Path] = set()

    # --- внутренние проверки ---------------------------------------------

    def _resolve_own_paths(self) -> None:
        own: set[Path] = set()
        for candidate in self.paths.own_paths():
            try:
                own.add(candidate.resolve())
            except OSError:
                continue
        self._own_paths = own

    def _is_own_path(self, path: Path) -> bool:
        """Лежит ли путь внутри собственных каталогов приложения (раздел 9 ТЗ)."""
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for own in self._own_paths:
            if own == self.paths.root.resolve():
                # Корень приложения сам по себе может быть выбран пользователем;
                # исключаются только служебные подкаталоги.
                continue
            if resolved == own or resolved.is_relative_to(own):
                return True
        return False

    def _seen(self, entry_stat: os.stat_result) -> bool:
        """Отметить каталог как посещённый; True — если это повтор (петля)."""
        key = (entry_stat.st_dev, entry_stat.st_ino)
        if key in self._visited:
            return True
        self._visited.add(key)
        return False

    def _within_root(self, path: Path, root: Path) -> bool:
        """Остаётся ли реальный путь внутри выбранного дерева."""
        try:
            return path.resolve().is_relative_to(root)
        except OSError:
            return False

    # --- обход -------------------------------------------------------------

    def scan(self, directory: Path) -> Iterator[ScannedFile]:
        """Выдать файлы каталога.

        Скрытые для обхода объекты не читаются и не открываются.
        """
        root = Path(directory)
        if not root.is_dir():
            raise NotADirectoryError(f"Каталог не найден: {root}")
        root_resolved = root.resolve()
        self.stats = ScanStats()
        self.folders = []
        self._visited = set()
        self._resolve_own_paths()
        yield from self._walk(root_resolved, root_resolved)

    def _walk(self, directory: Path, root: Path) -> Iterator[ScannedFile]:
        if is_system_dir(directory):
            return
        try:
            stat_result = directory.stat()
        except OSError:
            self.stats.access_denied += 1
            return
        if self._seen(stat_result):
            self.stats.loops_prevented += 1
            return

        self.stats.directories += 1
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            self.stats.access_denied += 1
            return

        subdirectories: list[Path] = []
        for entry in entries:
            name = nfc(entry.name)
            path = Path(entry.path)

            if is_ignored_name(name, self.patterns):
                self.stats.files_skipped += 1
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError:
                self.stats.access_denied += 1
                continue

            if is_link:
                # Symlink/junction/reparse point: за пределы дерева не выходим
                # и по умолчанию вообще не следуем (раздел 9 ТЗ).
                self.stats.symlinks_skipped += 1
                if not self.follow_symlinks or not self._within_root(path, root):
                    continue
                try:
                    is_dir = path.is_dir()
                    is_file = path.is_file()
                except OSError:
                    continue

            if is_dir:
                if not self._is_own_path(path):
                    self.folders.append(path)
                    self.stats.folders_found += 1
                    if self.recursive:
                        subdirectories.append(path)
                continue

            if not is_file:
                # FIFO, сокеты, устройства — не пользовательские документы.
                self.stats.files_skipped += 1
                continue

            if self._is_own_path(path):
                self.stats.files_skipped += 1
                continue

            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                self.stats.access_denied += 1
                continue

            extension = path.suffix.lower()
            self.stats.files_found += 1
            self.stats.note_extension(extension)
            yield ScannedFile(
                path=path,
                size=stat.st_size,
                mtime=stat.st_mtime,
                extension=extension,
            )

        for subdirectory in subdirectories:
            yield from self._walk(subdirectory, root)


def scan_directory(
    directory: Path,
    *,
    recursive: bool = True,
    paths: AppPaths | None = None,
) -> tuple[list[ScannedFile], ScanStats]:
    """Удобная обёртка: вернуть список файлов и статистику."""
    scanner = Scanner(recursive=recursive, paths=paths)
    files = list(scanner.scan(Path(directory)))
    return files, scanner.stats


def scan_folders(
    directory: Path,
    *,
    recursive: bool = True,
    paths: AppPaths | None = None,
) -> list[Path]:
    """Подкаталоги выбранной папки — их тоже можно переименовать."""
    scanner = Scanner(recursive=recursive, paths=paths)
    list(scanner.scan(Path(directory)))
    return list(scanner.folders)
