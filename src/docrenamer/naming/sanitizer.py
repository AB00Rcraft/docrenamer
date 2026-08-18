"""Санитизация имён файлов (раздел 45 ТЗ).

Задача модуля — гарантировать, что предложенное имя безопасно и допустимо в
Windows и POSIX, при этом сохраняя кириллицу, «№», кавычки «» и длинное тире,
которые для русских документов значимы (раздел 14A ТЗ).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from docrenamer.types import nfc

#: Символы, запрещённые в именах файлов Windows. Разделительные по смыслу
#: символы заменяются на дефис, чтобы «Иванов/Петров» не склеился в одно слово.
FORBIDDEN_TO_DASH = {"/": "-", "\\": "-", "|": "-", ":": "-"}
#: Остальные запрещённые символы удаляются.
FORBIDDEN_TO_REMOVE = '<>"*?'

#: Зарезервированные имена устройств Windows (раздел 45 ТЗ).
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

#: Предел длины имени в байтах UTF-8. Для ext4/APFS NAME_MAX = 255 байт, что для
#: кириллицы (2 байта на символ) наступает раньше символьного лимита.
MAX_FILENAME_BYTES = 255

_WHITESPACE_RE = re.compile(r"\s+")
#: Три и более дефиса схлопываются до двойного: «--» — значимый разделитель
#: участников в грамматике имени (раздел 44 ТЗ).
_DASH_RUN_RE = re.compile(r"-{3,}")
_TRIM_RE = re.compile(r"^[\s.\-_]+|[\s.\-_]+$")


def strip_control_chars(value: str) -> str:
    """Удалить control- и format-символы.

    Кроме C0/C1 удаляются символы категории ``Cf`` — в частности U+202E
    RIGHT-TO-LEFT OVERRIDE, которым маскируют расширение файла.
    """
    return "".join(ch for ch in value if unicodedata.category(ch) not in ("Cc", "Cf"))


def sanitize_component(value: str, *, max_length: int = 0) -> str:
    """Привести один смысловой сегмент имени к безопасному виду."""
    if not value:
        return ""
    text = nfc(str(value))
    text = strip_control_chars(text)
    for bad, replacement in FORBIDDEN_TO_DASH.items():
        text = text.replace(bad, replacement)
    for bad in FORBIDDEN_TO_REMOVE:
        text = text.replace(bad, "")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.replace(" ", "-")
    text = _DASH_RUN_RE.sub("--", text)
    text = _TRIM_RE.sub("", text)
    if max_length > 0:
        text = text[:max_length]
        text = _TRIM_RE.sub("", text)
    return text


def normalize_extension(extension: str, *, lowercase: bool = True) -> str:
    """Нормализовать расширение, не меняя его смысл.

    Меняется только регистр (примеры раздела 27 ТЗ: ``.HEIC`` → ``.heic``).
    Сам тип файла расширением не подменяется (раздел 10 ТЗ).
    """
    if not extension:
        return ""
    ext = nfc(extension)
    ext = strip_control_chars(ext)
    if not ext.startswith("."):
        ext = "." + ext
    ext = "".join(ch for ch in ext if ch not in FORBIDDEN_TO_REMOVE and ch not in FORBIDDEN_TO_DASH)
    ext = _WHITESPACE_RE.sub("", ext)
    if ext == ".":
        return ""
    return ext.lower() if lowercase else ext


def is_reserved(stem: str) -> bool:
    """Является ли основа имени зарезервированным именем устройства Windows."""
    return stem.strip().upper() in RESERVED_NAMES


def utf8_length(value: str) -> int:
    """Длина строки в байтах UTF-8."""
    return len(value.encode("utf-8"))


def _truncate_to_bytes(value: str, max_bytes: int) -> str:
    """Обрезать строку так, чтобы уложиться в ``max_bytes`` байт UTF-8.

    Обрезка идёт по символам, поэтому многобайтовая кириллица не рвётся.
    """
    if utf8_length(value) <= max_bytes:
        return value
    result: list[str] = []
    used = 0
    for ch in value:
        size = len(ch.encode("utf-8"))
        if used + size > max_bytes:
            break
        result.append(ch)
        used += size
    return "".join(result)


def sanitize_filename(
    stem: str,
    extension: str = "",
    *,
    max_length: int = 160,
    max_bytes: int = MAX_FILENAME_BYTES,
    fallback: str = "файл",
    lowercase_extension: bool = True,
) -> str:
    """Собрать безопасное имя файла из основы и расширения.

    Гарантии:

    * расширение сохраняется;
    * запрещённые и управляющие символы отсутствуют;
    * нет пробелов и точек в начале и конце;
    * имя не равно ``.`` или ``..``;
    * зарезервированные имена Windows экранируются;
    * длина не превышает ни символьный, ни байтовый лимит.
    """
    ext = normalize_extension(extension, lowercase=lowercase_extension)
    base = sanitize_component(stem)

    if base in ("", ".", ".."):
        base = fallback
    if is_reserved(base):
        base = f"_{base}"

    ext_len = len(ext)
    ext_bytes = utf8_length(ext)
    char_budget = max(1, max_length - ext_len)
    byte_budget = max(1, max_bytes - ext_bytes)

    base = base[:char_budget]
    base = _truncate_to_bytes(base, byte_budget)
    base = _TRIM_RE.sub("", base)
    if not base:
        base = _truncate_to_bytes(fallback[:char_budget], byte_budget) or "_"
    if is_reserved(base):
        base = f"_{base}"[:char_budget]
    return f"{base}{ext}"


def is_safe_filename(
    name: str, *, max_length: int = 240, max_bytes: int = MAX_FILENAME_BYTES
) -> bool:
    """Проверка, что имя пригодно для записи на диск.

    Используется как инвариант в safety-тестах и перед APPLY.
    """
    if not name or name in (".", ".."):
        return False
    if len(name) > max_length or utf8_length(name) > max_bytes:
        return False
    if any(ch in name for ch in FORBIDDEN_TO_DASH) or any(ch in name for ch in FORBIDDEN_TO_REMOVE):
        return False
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in name):
        return False
    if name != name.strip() or name.endswith("."):
        return False
    stem = name.split(".")[0]
    return not is_reserved(stem)


@dataclass(slots=True)
class Segment:
    """Смысловой сегмент имени (раздел 44 ТЗ).

    ``priority`` — важность. При нехватке длины первыми отбрасываются
    второстепенные сегменты с наименьшим приоритетом, а не идентификаторы
    (раздел 45 ТЗ).
    """

    text: str
    priority: int = 50
    droppable: bool = True
    kind: str = ""


def assemble_filename(
    segments: list[Segment],
    extension: str,
    *,
    separator: str = "__",
    max_length: int = 160,
    max_bytes: int = MAX_FILENAME_BYTES,
    fallback: str = "файл",
    lowercase_extension: bool = True,
) -> tuple[str, list[str]]:
    """Собрать имя из сегментов, уложившись в лимиты.

    Возвращает ``(имя, отброшенные_сегменты)``.
    """
    cleaned = [
        Segment(sanitize_component(s.text), s.priority, s.droppable, s.kind)
        for s in segments
        if s.text and sanitize_component(s.text)
    ]
    dropped: list[str] = []

    def build(items: list[Segment]) -> str:
        stem = separator.join(item.text for item in items)
        return sanitize_filename(
            stem,
            extension,
            max_length=max_length,
            max_bytes=max_bytes,
            fallback=fallback,
            lowercase_extension=lowercase_extension,
        )

    ext = normalize_extension(extension, lowercase=lowercase_extension)

    def fits(items: list[Segment]) -> bool:
        stem = separator.join(item.text for item in items)
        candidate = f"{stem}{ext}"
        return len(candidate) <= max_length and utf8_length(candidate) <= max_bytes

    while cleaned and not fits(cleaned):
        droppable = [i for i, item in enumerate(cleaned) if item.droppable]
        if not droppable:
            break
        # Отбрасываем наименее приоритетный; при равенстве — самый правый.
        victim = min(droppable, key=lambda i: (cleaned[i].priority, -i))
        dropped.append(cleaned[victim].kind or cleaned[victim].text)
        del cleaned[victim]

    if not cleaned:
        return sanitize_filename(
            fallback,
            extension,
            max_length=max_length,
            max_bytes=max_bytes,
            fallback=fallback,
            lowercase_extension=lowercase_extension,
        ), dropped

    return build(cleaned), dropped
