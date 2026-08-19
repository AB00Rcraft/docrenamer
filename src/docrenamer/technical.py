"""Служебные и системные файлы: узнать и не тронуть.

Рядом с документами почти всегда лежит техническая мелочь: ярлыки на рабочем
столе, файлы настроек, базы программ, журналы, резервные копии. Их имена — не
описание содержимого, а часть работы системы или программы: переименуешь
``desktop.ini`` — и папка потеряет вид, переименуешь ``.lnk`` — и ярлык
перестанет открываться тем, чем открывался.

Поэтому такие файлы программа не переименовывает вовсе. Но и прятать их
неправильно: человек должен видеть, что они есть и почему оставлены. В списке
они показываются жёлтой строкой без предложения и без отметки.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Расширения служебных файлов: настройки, базы, журналы, исполняемые файлы.
TECHNICAL_SUFFIXES: dict[str, str] = {
    ".lnk": "ярлык Windows",
    ".url": "интернет-ярлык",
    ".desktop": "ярлык рабочего стола",
    ".ini": "файл настроек",
    ".cfg": "файл настроек",
    ".conf": "файл настроек",
    ".inf": "файл установки",
    ".reg": "файл реестра Windows",
    ".dat": "служебные данные программы",
    ".db": "база данных программы",
    ".sqlite": "база данных программы",
    ".sqlite3": "база данных программы",
    ".log": "журнал программы",
    ".bak": "резервная копия",
    ".old": "прежняя версия файла",
    ".tmp": "временный файл",
    ".temp": "временный файл",
    ".swp": "временный файл редактора",
    ".lock": "файл блокировки",
    ".pid": "служебный файл процесса",
    ".sys": "системный файл",
    ".dll": "библиотека программы",
    ".exe": "исполняемый файл",
    ".msi": "установщик программы",
    ".bat": "командный файл",
    ".cmd": "командный файл",
    ".ps1": "сценарий PowerShell",
    ".vbs": "сценарий Windows",
    ".sh": "сценарий оболочки",
    ".crdownload": "недокачанный файл",
    ".part": "недокачанный файл",
    ".partial": "недокачанный файл",
    ".manifest": "служебное описание программы",
    ".cat": "каталог подписей Windows",
}

#: Имена, известные наперёд.
TECHNICAL_NAMES: dict[str, str] = {
    "desktop.ini": "вид папки в проводнике",
    "thumbs.db": "хранилище эскизов Windows",
    "ehthumbs.db": "хранилище эскизов Windows",
    "ntuser.dat": "профиль пользователя Windows",
    "autorun.inf": "автозапуск носителя",
    ".ds_store": "служебный файл macOS",
    "icon\r": "служебный файл macOS",
    ".gitignore": "служебный файл системы контроля версий",
    ".gitattributes": "служебный файл системы контроля версий",
    "package-lock.json": "служебный файл сборки",
    "yarn.lock": "служебный файл сборки",
}

#: Атрибуты Windows: скрытый и системный.
FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_SYSTEM = 0x04


def classify_technical(path: Path) -> str:
    """Служебный ли это файл, и если да — почему.

    Returns:
        Причина по-русски либо пустая строка, если файл обычный.
    """
    name = path.name
    lowered = name.casefold()

    known = TECHNICAL_NAMES.get(lowered)
    if known:
        return known

    if lowered.startswith("~$"):
        return "временный файл Office"
    if name.startswith(".") and len(name) > 1:
        return "скрытый служебный файл"

    suffix = path.suffix.lower()
    by_suffix = TECHNICAL_SUFFIXES.get(suffix)
    if by_suffix:
        return by_suffix

    if _has_system_attributes(path):
        return "файл со служебным атрибутом системы"
    return ""


def _has_system_attributes(path: Path) -> bool:
    """Помечен ли файл в Windows как скрытый или системный."""
    if os.name != "nt":
        return False
    try:
        attributes = path.stat().st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attributes & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
