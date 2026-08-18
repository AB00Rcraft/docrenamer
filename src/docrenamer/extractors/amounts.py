"""Извлечение денежных сумм (раздел 40 ТЗ).

Суммы не попадают в имя файла напрямую, но участвуют в определении типа
документа и в контексте для локальной модели.
"""

from __future__ import annotations

import re

from docrenamer.extractors.common import context_window
from docrenamer.types import Candidate, Source

#: «154 300,50 руб.», «1 000 000 рублей», «25 000₽», «100000.00 RUB»
AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(руб\.?|рублей|рубля|₽|RUB|коп\.?|USD|\$|EUR|€)",
    re.IGNORECASE,
)

CURRENCY_MAP = {
    "руб": "RUB",
    "рублей": "RUB",
    "рубля": "RUB",
    "₽": "RUB",
    "rub": "RUB",
    "usd": "USD",
    "$": "USD",
    "eur": "EUR",
    "€": "EUR",
}


def parse_amount(raw: str) -> float | None:
    """Преобразовать русскую запись суммы в число."""
    cleaned = raw.replace(" ", "").replace(" ", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_amounts(text: str, limit: int = 20) -> list[Candidate]:
    """Найти денежные суммы."""
    if not text:
        return []
    results: list[tuple[float, Candidate]] = []
    for match in AMOUNT_RE.finditer(text):
        value = parse_amount(match.group(1))
        if value is None or value <= 0:
            continue
        unit = match.group(2).lower().rstrip(".")
        if unit.startswith("коп"):
            continue
        currency = CURRENCY_MAP.get(unit, "RUB")
        results.append(
            (
                value,
                Candidate(
                    value=f"{value:.2f} {currency}",
                    position=match.start(),
                    context=context_window(text, *match.span()),
                    source=Source.REGEX,
                    role_guess="amount",
                    confidence=0.9,
                    kind="amount",
                ),
            )
        )
        if len(results) >= limit:
            break
    # Крупные суммы первыми: они чаще определяют предмет документа.
    return [c for _, c in sorted(results, key=lambda pair: (-pair[0], pair[1].position))]
