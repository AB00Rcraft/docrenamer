"""Формат даты в имени файла (раздел 44 ТЗ).

Внутри программы дата всегда хранится в каноническом виде ``ГГГГ-ММ-ДД``: так
она попадает в manifest и в отчёты, так её удобно сравнивать. В имя файла она
выводится в том формате, который выбрал пользователь, — по умолчанию в
привычном российском «день.месяц.год».
"""

from __future__ import annotations

import re

#: Поддерживаемые форматы даты в имени файла.
DATE_FORMATS: dict[str, str] = {
    "DD.MM.YYYY": "день.месяц.год — привычный российский формат",
    "DD-MM-YYYY": "день-месяц-год через дефис",
    "YYYY-MM-DD": "год-месяц-день — файлы сортируются по дате",
}

DEFAULT_DATE_FORMAT = "DD.MM.YYYY"

#: Каноническая дата, возможно с временем: 2026-08-03 или 2026-08-03_18-42-17.
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?P<tail>[_T].*)?$")


def format_date_for_name(value: str, date_format: str = DEFAULT_DATE_FORMAT) -> str:
    """Преобразовать каноническую дату к виду для имени файла.

    Время, если оно есть, сохраняется без изменений: ``2026-08-03_18.42.17``
    превращается в ``03.08.2026_18.42.17``.

    Значение, не похожее на каноническую дату, возвращается как есть — портить
    неизвестные данные нельзя.
    """
    match = _ISO_RE.match(str(value).strip())
    if not match:
        return str(value)
    year, month, day = match.group(1), match.group(2), match.group(3)
    tail = match.group("tail") or ""

    if date_format == "YYYY-MM-DD":
        head = f"{year}-{month}-{day}"
    elif date_format == "DD-MM-YYYY":
        head = f"{day}-{month}-{year}"
    else:
        head = f"{day}.{month}.{year}"
    return f"{head}{tail}"


def date_variants(value: str) -> set[str]:
    """Все написания даты, по которым её можно узнать в имени файла."""
    match = _ISO_RE.match(str(value).strip())
    if not match:
        return {str(value)}
    year, month, day = match.group(1), match.group(2), match.group(3)
    return {
        f"{year}-{month}-{day}",
        f"{day}.{month}.{year}",
        f"{day}-{month}-{year}",
        f"{int(day)}.{int(month)}.{year}",
    }
