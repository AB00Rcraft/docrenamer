"""Самопроверка построенного имени — второй проход (раздел 92 ТЗ).

Первый проход собирает имя из найденных фактов. Второй перечитывает то, что
получилось, и отвечает на вопрос: можно ли это показывать человеку. Проверки
намеренно тупые и независимые от логики сборки — именно так они ловят её
ошибки: две даты в имени, повтор одного и того же слова, случайное число,
обрывок фразы вместо названия.

Найденную мелочь второй проход исправляет сам (убирает лишний сегмент), а при
серьёзной ошибке отказывается от имени: лучше оставить файл как есть, чем
переименовать его неверно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docrenamer.naming.sanitizer import Segment, is_safe_filename, utf8_length
from docrenamer.textquality import comparison_key

#: Токен, похожий на дату: 27.07.2026, 2026-07-27, 25-11-2024.
DATE_TOKEN_RE = re.compile(r"^\d{1,2}[.\-]\d{1,2}[.\-]\d{4}$|^\d{4}-\d{2}-\d{2}$")

#: Одинокое короткое число: в имени оно ничего не сообщает.
BARE_NUMBER_RE = re.compile(r"^\d{1,2}$")

#: Виды сегментов, которым число или дата принадлежат по праву.
NUMERIC_KINDS = frozenset(
    {
        "date",
        "datetime",
        "identifier",
        "identifier_from_name",
        "series",
        "count",
        "duration",
        "gps",
    }
)


def dedupe_key(text: str) -> str:
    """Ключ сравнения сегментов без разделителей.

    «Договор_купли_продажи» и «купли-продажи» — это одно и то же, хотя
    записаны по-разному. Без такой нормализации предмет повторяет вид
    документа прямо в имени файла.
    """
    return re.sub(r"[^\w]|_", "", comparison_key(text))


@dataclass(frozen=True, slots=True)
class Issue:
    """Замечание к имени."""

    code: str
    message: str
    segment: str = ""


def review_segments(segments: list[Segment]) -> tuple[list[Segment], list[Issue]]:
    """Первый шаг второго прохода: убрать сегменты, которым в имени не место."""
    kept: list[Segment] = []
    issues: list[Issue] = []
    seen: list[str] = []

    for segment in segments:
        text = segment.text.strip()
        key = dedupe_key(text)
        if not key:
            continue

        if segment.kind not in NUMERIC_KINDS and DATE_TOKEN_RE.match(text):
            issues.append(
                Issue("date_outside_date", "значение похоже на дату, но датой не является", text)
            )
            continue

        if segment.kind not in NUMERIC_KINDS and BARE_NUMBER_RE.match(text):
            issues.append(Issue("bare_number", "одинокое число ничего не сообщает", text))
            continue

        if any(key == other or (len(key) > 3 and key in other) for other in seen):
            issues.append(Issue("duplicate", "повтор уже сказанного", text))
            continue

        seen.append(key)
        kept.append(segment)

    return kept, issues


def review_name(name: str, *, max_length: int, expected_date: str = "") -> list[Issue]:
    """Второй шаг: перечитать готовое имя целиком."""
    issues: list[Issue] = []
    if not name:
        return issues

    stem = name.rsplit(".", 1)[0] if "." in name else name

    if not is_safe_filename(name, max_length=max(max_length, 40)):
        issues.append(Issue("unsafe", "имя недопустимо для файловой системы", name))
    if len(name) > max_length or utf8_length(name) > 255:
        issues.append(Issue("too_long", "имя длиннее допустимого", name))
    if "__" in stem:
        issues.append(Issue("double_separator", "двойной разделитель", name))
    if stem.startswith("_") or stem.endswith("_"):
        issues.append(Issue("edge_separator", "разделитель с краю", name))

    first = next((ch for ch in stem if ch.isalnum()), "")
    if first and first.isalpha() and first.islower():
        issues.append(Issue("lowercase_start", "имя начинается со строчной буквы", name))

    dates = [part for part in stem.split("_") if DATE_TOKEN_RE.match(part)]
    if len(dates) > 1:
        issues.append(Issue("many_dates", "в имени больше одной даты", ", ".join(dates)))
    if expected_date and dates and dates[0] != expected_date:
        issues.append(Issue("wrong_date", "дата в имени не та, что установлена", dates[0]))

    # Проверка на «кракозябры» ведётся по символам замены. Частотная модель
    # русского языка здесь неприменима: имя файла — это несколько имён
    # собственных, а не связный текст, и она даёт ложные срабатывания.
    if "\ufffd" in name:
        issues.append(Issue("broken_text", "в имени есть нечитаемые символы", name))

    return issues


#: Замечания, при которых имя предлагать нельзя.
BLOCKING_CODES = frozenset({"unsafe", "too_long", "many_dates", "wrong_date", "broken_text"})


def is_blocking(issues: list[Issue]) -> bool:
    """Есть ли среди замечаний такое, из-за которого имя нельзя предлагать."""
    return any(issue.code in BLOCKING_CODES for issue in issues)
