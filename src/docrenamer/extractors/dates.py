"""Извлечение дат (разделы 40, 41, 14A.9 ТЗ).

Поддерживаются числовые и словесные русские формы. Двузначный год без явно
заданной политики не интерпретируется.
"""

from __future__ import annotations

import re
from datetime import date

from docrenamer.extractors.common import context_window, head_position_bonus
from docrenamer.types import Candidate, Source

#: Названия месяцев в родительном падеже и распространённые сокращения.
MONTHS: dict[str, int] = {
    "января": 1, "янв": 1,
    "февраля": 2, "фев": 2, "февр": 2,
    "марта": 3, "мар": 3,
    "апреля": 4, "апр": 4,
    "мая": 5,
    "июня": 6, "июн": 6,
    "июля": 7, "июл": 7,
    "августа": 8, "авг": 8,
    "сентября": 9, "сен": 9, "сент": 9,
    "октября": 10, "окт": 10,
    "ноября": 11, "ноя": 11, "нояб": 11,
    "декабря": 12, "дек": 12,
}

#: Именительный падеж — встречается в заголовках таблиц и штампах.
MONTHS_NOMINATIVE: dict[str, int] = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

_MONTH_ALTERNATION = "|".join(sorted({*MONTHS, *MONTHS_NOMINATIVE}, key=len, reverse=True))

#: «18 августа 2026 года», ««18» августа 2026 г.»
VERBAL_RE = re.compile(
    r"[«\"']?(\d{1,2})[»\"']?\s+(" + _MONTH_ALTERNATION + r")\.?\s+(\d{4})\s*(?:г\.?|года|год)?",
    re.IGNORECASE,
)

#: «18.08.2026», «18/08/2026», «18-08-2026»
NUMERIC_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b")

#: «18.08.26» — двузначный год.
SHORT_YEAR_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})\b(?!\d)")

#: ISO-форма «2026-08-18».
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

#: Маркеры, повышающие вероятность того, что это дата самого документа.
DOCUMENT_DATE_MARKERS = (
    "от",
    "дата",
    "составлен",
    "составлено",
    "подписан",
    "выдан",
    "вынесено",
    "принято",
    "утверждено",
    "г. москва",
    "город",
)

#: Маркеры дат, которые датой документа быть не могут: они описывают человека
#: или сам предмет, а не время составления. Дата рождения в справке по
#: человеку стоит в первых строках и иначе побеждает по положению в тексте.
PERSONAL_DATE_MARKERS: tuple[str, ...] = (
    "рождения",
    "родился",
    "родилась",
    "дата рожд",
    "г.р.",
    "года рождения",
    "срок действия",
    "действителен до",
    "годен до",
)

#: Разумные границы: документы вне этого диапазона почти всегда ошибка разбора.
MIN_YEAR = 1900
MAX_YEAR = 2100


def _make(value: date, match: re.Match[str], text: str, confidence: float, kind: str) -> Candidate:
    start, end = match.span()
    snippet = context_window(text, start, end)
    if _looks_like_personal_date(text, start):
        role = "personal_date"
    elif _looks_like_document_date(text, start):
        role = "document_date"
    else:
        role = "date"
    return Candidate(
        value=value.isoformat(),
        position=start,
        context=snippet,
        source=Source.REGEX,
        role_guess=role,
        confidence=min(0.99, confidence + head_position_bonus(start, len(text))),
        kind=kind,
    )


def _looks_like_personal_date(text: str, position: int) -> bool:
    """Дата рождения или срок действия — не дата документа."""
    left = text[max(0, position - 40) : position].lower()
    return any(marker in left for marker in PERSONAL_DATE_MARKERS)


def _looks_like_document_date(text: str, position: int) -> bool:
    """Есть ли рядом маркер, характерный для даты документа."""
    left = text[max(0, position - 40) : position].lower()
    return any(marker in left for marker in DOCUMENT_DATE_MARKERS)


def _safe_date(year: int, month: int, day: int) -> date | None:
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_dates(text: str, *, allow_two_digit_year: bool = False) -> list[Candidate]:
    """Найти все даты в тексте.

    Args:
        allow_two_digit_year: интерпретировать ли двузначный год. По умолчанию
            выключено (раздел 14A.9 ТЗ): такие значения помечаются низкой
            уверенностью и ролью ``ambiguous_year``.
    """
    if not text:
        return []
    candidates: list[Candidate] = []

    for match in VERBAL_RE.finditer(text):
        day_raw, month_raw, year_raw = match.groups()
        month_key = month_raw.lower().rstrip(".")
        month = MONTHS.get(month_key) or MONTHS_NOMINATIVE.get(month_key)
        if month is None:
            continue
        value = _safe_date(int(year_raw), month, int(day_raw))
        if value is not None:
            candidates.append(_make(value, match, text, 0.93, "verbal"))

    for match in NUMERIC_RE.finditer(text):
        day_raw, month_raw, year_raw = match.groups()
        value = _safe_date(int(year_raw), int(month_raw), int(day_raw))
        if value is None:
            # Возможен формат «месяц.день.год» — но угадывать не будем.
            continue
        candidates.append(_make(value, match, text, 0.88, "numeric"))

    for match in ISO_RE.finditer(text):
        year_raw, month_raw, day_raw = match.groups()
        value = _safe_date(int(year_raw), int(month_raw), int(day_raw))
        if value is not None:
            candidates.append(_make(value, match, text, 0.9, "iso"))

    for match in SHORT_YEAR_RE.finditer(text):
        day_raw, month_raw, year_raw = match.groups()
        if not allow_two_digit_year:
            candidates.append(
                Candidate(
                    value=match.group(0),
                    position=match.start(),
                    context=context_window(text, *match.span()),
                    source=Source.REGEX,
                    role_guess="ambiguous_year",
                    confidence=0.25,
                    kind="short_year",
                )
            )
            continue
        year = 2000 + int(year_raw) if int(year_raw) < 70 else 1900 + int(year_raw)
        value = _safe_date(year, int(month_raw), int(day_raw))
        if value is not None:
            candidates.append(_make(value, match, text, 0.6, "short_year"))

    return _dedupe(candidates)


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """Убрать дубли по значению, оставив самый уверенный экземпляр."""
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        current = best.get(candidate.value)
        if current is None or candidate.confidence > current.confidence:
            best[candidate.value] = candidate
    return sorted(best.values(), key=lambda c: (-c.confidence, c.position))


def select_document_date(
    candidates: list[Candidate],
    *,
    metadata_date: str = "",
    metadata_confidence: float = 0.0,
) -> Candidate | None:
    """Выбрать дату документа по приоритетам раздела 41 ТЗ.

    Приоритет: надёжные метаданные → дата рядом с маркером «от»/«дата» →
    самая ранняя по положению в тексте.
    """
    if metadata_date and metadata_confidence >= 0.9:
        return Candidate(
            value=metadata_date,
            position=-1,
            context="metadata",
            source=Source.METADATA,
            role_guess="document_date",
            confidence=metadata_confidence,
            kind="metadata",
        )

    usable = [
        c for c in candidates if c.role_guess not in ("ambiguous_year", "personal_date")
    ]
    if not usable:
        return None

    marked = [c for c in usable if c.role_guess == "document_date"]
    pool = marked or usable
    return min(pool, key=lambda c: (c.position if c.position >= 0 else 0, -c.confidence))
