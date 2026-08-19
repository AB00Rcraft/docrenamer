"""Что лежит в папке — сведения для окна выбора папки.

Системное окно выбора показывает одни названия папок: что внутри, не видно, и
нужную папку приходится угадывать по памяти. Программа поэтому рисует своё
окно, а этот модуль отвечает на два вопроса: что лежит в папке и с чего
начинать обзор.

Модуль намеренно не зависит от Tkinter — так его можно проверить и там, где
графической подсистемы нет. Файлы только перечисляются: ничего не
открывается, не читается и не меняется.
"""

from __future__ import annotations

import os
import string
from dataclasses import dataclass
from pathlib import Path

#: Сколько строк показывать в списке содержимого. Больше человек всё равно не
#: разглядывает: ему нужно понять, та ли это папка.
MAX_ENTRIES = 500

#: Предел обхода каталога. В папке загрузок бывают десятки тысяч файлов, и
#: окно выбора не имеет права из-за этого замереть.
MAX_COUNTED = 20_000


@dataclass(frozen=True, slots=True)
class Entry:
    """Строка содержимого папки."""

    path: Path
    name: str
    is_dir: bool
    size: int
    mtime: float


@dataclass(frozen=True, slots=True)
class Listing:
    """Содержимое папки: что показать и сколько всего внутри."""

    path: Path
    entries: tuple[Entry, ...]
    folders: int
    files: int
    #: Сколько строк не поместилось в показанные.
    hidden: int
    #: Обход прерван по пределу: в папке больше MAX_COUNTED записей.
    partial: bool = False
    #: Папка не прочитана — здесь человеческая причина.
    error: str | None = None


def list_directory(path: Path, *, limit: int = MAX_ENTRIES) -> Listing:
    """Перечислить содержимое папки: сначала папки, затем файлы.

    Недоступная папка не является ошибкой программы: на любом диске есть
    каталоги, закрытые правами. Такая папка возвращается с пояснением, а не
    с исключением — окно выбора продолжает работать.
    """
    entries: list[Entry] = []
    folders = files = 0
    partial = False
    try:
        with os.scandir(path) as scan:
            for record in scan:
                if folders + files >= MAX_COUNTED:
                    partial = True
                    break
                entries.append(_entry(record))
                if entries[-1].is_dir:
                    folders += 1
                else:
                    files += 1
    except OSError as exc:
        return Listing(
            path=path, entries=(), folders=0, files=0, hidden=0, error=_reason(exc)
        )
    entries.sort(key=lambda entry: (not entry.is_dir, entry.name.casefold()))
    shown = tuple(entries[:limit])
    return Listing(
        path=path,
        entries=shown,
        folders=folders,
        files=files,
        hidden=max(0, folders + files - len(shown)),
        partial=partial,
    )


def subdirectories(path: Path, *, limit: int = MAX_ENTRIES) -> list[Path]:
    """Вложенные папки — для дерева в окне выбора."""
    listing = list_directory(path, limit=limit)
    return [entry.path for entry in listing.entries if entry.is_dir]


def has_subdirectories(path: Path) -> bool:
    """Есть ли внутри хоть одна папка.

    Нужно, чтобы дерево показывало стрелку раскрытия только там, где есть что
    раскрывать. Обход прекращается на первой найденной папке.
    """
    try:
        with os.scandir(path) as scan:
            for index, record in enumerate(scan):
                if index >= MAX_COUNTED:
                    return False
                try:
                    if record.is_dir():
                        return True
                except OSError:  # запись пропала или недоступна — не помеха
                    continue
    except OSError:
        return False
    return False


def summary(listing: Listing) -> str:
    """Строка под списком: сколько всего в папке."""
    if listing.error:
        return listing.error
    if not listing.folders and not listing.files:
        return "Папка пуста."
    parts: list[str] = []
    if listing.folders:
        parts.append(f"{listing.folders} {plural(listing.folders, FOLDER_FORMS)}")
    if listing.files:
        parts.append(f"{listing.files} {plural(listing.files, FILE_FORMS)}")
    text = "В папке: " + ", ".join(parts)
    if listing.partial:
        text += " и больше — показаны не все"
    elif listing.hidden:
        text += f"; показаны первые {len(listing.entries)}"
    return text


#: Формы слов для счёта: 1 файл, 2 файла, 5 файлов.
FILE_FORMS = ("файл", "файла", "файлов")
FOLDER_FORMS = ("папка", "папки", "папок")


def plural(count: int, forms: tuple[str, str, str]) -> str:
    """Русская форма слова при числе: 1 файл, 2 файла, 5 файлов."""
    tail = abs(count) % 100
    if 11 <= tail <= 14:
        return forms[2]
    tail %= 10
    if tail == 1:
        return forms[0]
    if 2 <= tail <= 4:
        return forms[1]
    return forms[2]


def quick_roots() -> list[tuple[str, Path]]:
    """С чего начинать обзор: диски и привычные папки пользователя.

    На Windows это буквы дисков, иначе — корень файловой системы. Домашние
    папки добавляются всюду: чаще всего документы лежат именно там.
    """
    roots: list[tuple[str, Path]] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append((f"Диск {letter}:", drive))
    else:
        roots.append(("Файловая система", Path("/")))
    home = Path.home()
    if home.is_dir():
        roots.append(("Домашняя папка", home))
        for label, names in HOME_FOLDERS:
            for name in names:
                candidate = home / name
                if candidate.is_dir():
                    roots.append((label, candidate))
                    break
    return _unique(roots)


#: Привычные папки внутри домашней. Имена бывают и русские, и английские —
#: смотрим оба варианта и берём первый существующий.
HOME_FOLDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Рабочий стол", ("Desktop", "Рабочий стол")),
    ("Документы", ("Documents", "Документы")),
    ("Загрузки", ("Downloads", "Загрузки")),
)


def path_chain(path: Path, roots: list[tuple[str, Path]]) -> list[Path]:
    """Путь от начала обзора до папки — по одному уровню на шаг.

    По этой цепочке дерево раскрывается до нужной папки. Если папка лежит вне
    известных начал обзора (сетевой путь, чужой диск), цепочки нет: дерево
    остаётся как есть, а содержимое всё равно показывается.
    """
    for _label, root in roots:
        if path == root:
            return [root]
        if root in path.parents:
            chain = [root]
            current = root
            for part in path.relative_to(root).parts:
                current = current / part
                chain.append(current)
            return chain
    return []


def start_folder(initial: Path | None) -> Path:
    """С какой папки открывать окно выбора.

    Прошлая папка удобнее любой другой: чаще всего работа продолжается там
    же. Если её больше нет — домашняя папка, а в крайнем случае текущая.
    """
    if initial is not None and initial.is_dir():
        return initial
    home = Path.home()
    return home if home.is_dir() else Path.cwd()


def _entry(record: os.DirEntry[str]) -> Entry:
    """Строка содержимого по записи каталога."""
    try:
        is_dir = record.is_dir()
    except OSError:  # ссылка в никуда или отобранный доступ
        is_dir = False
    size = 0
    mtime = 0.0
    try:
        stat = record.stat()
        mtime = stat.st_mtime
        if not is_dir:
            size = stat.st_size
    except OSError:  # свойства недоступны — показываем хотя бы имя
        pass
    return Entry(path=Path(record.path), name=record.name, is_dir=is_dir, size=size, mtime=mtime)


def _reason(exc: OSError) -> str:
    """Почему папка не прочитана — по-русски."""
    if isinstance(exc, PermissionError):
        return "Папка закрыта правами доступа."
    if isinstance(exc, FileNotFoundError):
        return "Папки больше нет."
    if isinstance(exc, NotADirectoryError):
        return "Это файл, а не папка."
    return f"Папка не прочитана: {exc.strerror or exc}"


def _unique(roots: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """Убрать повторы путей, сохранив порядок."""
    seen: set[Path] = set()
    result: list[tuple[str, Path]] = []
    for label, path in roots:
        if path in seen:
            continue
        seen.add(path)
        result.append((label, path))
    return result
