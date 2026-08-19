"""Извлечение номеров и реквизитов (разделы 40, 39 ТЗ).

Номера типизируются, а не складываются в одно поле: номер документа, номер
исполнительного производства, номер судебного дела, номер договора, ИНН и ОГРН
играют разные роли при построении имени.
"""

from __future__ import annotations

import re

from docrenamer.extractors.common import context_window, head_position_bonus
from docrenamer.types import Candidate, Source

#: Номер исполнительного производства: 652102/26/77028-ИП.
ENFORCEMENT_RE = re.compile(r"\b(\d{4,8}/\d{2}/\d{3,7}(?:-[А-ЯЁ]{2,4})?)\b")

#: Номер арбитражного дела: А40-123456/2026.
ARBITRATION_CASE_RE = re.compile(r"\b([АA]\d{1,2}-\d{1,7}/\d{4})\b")

#: Номер дела суда общей юрисдикции: 2-1234/2026, 5-12/2025, 33-456/2026.
COURT_CASE_RE = re.compile(
    r"(?:дел[оаеу]\D{0,12})(?<![А-ЯЁA-Za-z\d])(\d{1,3}-\d{1,6}/\d{4})", re.IGNORECASE
)

#: Явный номер дела с указанием «№».
GENERIC_CASE_RE = re.compile(r"\bдел[оаеу]\s*№\s*([^\s,;]{3,40})", re.IGNORECASE)

#: Номер документа после знака «№». Длина ограничена: иначе в номер попадает
#: всё, что напечатано следом, и в имени оказывается бессмысленная строка
#: вида «2.1183-2026-2124».
NUMBER_AFTER_SIGN_RE = re.compile(r"№\s*([0-9][0-9A-Za-zА-Яа-яЁё\-/._]{0,19})")

#: Номер договора: «Договор № 17», «договор займа №17».
CONTRACT_RE = re.compile(
    r"(?:договор|контракт|соглашени[ея]|полис)[^\n№]{0,40}№\s*([0-9][^\s,;.]{0,30})",
    re.IGNORECASE,
)

#: ИНН и ОГРН с явными подписями.
INN_RE = re.compile(r"\bИНН[\s:]*([0-9]{10}|[0-9]{12})\b")
OGRN_RE = re.compile(r"\bОГРН(?:ИП)?[\s:]*([0-9]{13}|[0-9]{15})\b")
KPP_RE = re.compile(r"\bКПП[\s:]*([0-9]{9})\b")

#: Значение, похожее на дату: 11.83.2026, 25.11.2024. Номером документа быть
#: не может — иначе в имени оказываются две даты, одна из них неверная.
DATE_LIKE_RE = re.compile(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$|^\d{4}-\d{2}-\d{2}$")

#: Исполнительный лист: серия ФС № 012345678.
WRIT_RE = re.compile(r"\b(?:сери[яи]\s*)?(ФС|ВС|АС)\s*№?\s*(\d{6,12})\b")


#: Разделители, допустимые внутри номера.
_SEPARATORS = "-/._"

#: Похоже на денежную сумму или дробное число, а не на номер.
DECIMAL_RE = re.compile(r"^\d+[.,]\d+$")


def is_plausible_number(value: str) -> bool:
    """Похоже ли значение на номер документа.

    Настоящий номер короткий и содержит немного разделителей. Строка вида
    «2.1183-2026-2124» — это склейка нескольких чисел из текста, и в имени
    файла она только мешает.
    """
    text = value.strip()
    if not text or len(text) > 20:
        return False
    if DECIMAL_RE.match(text):
        return False
    if text[-1] in _SEPARATORS:
        return False
    # Больше двух разделителей — это уже склейка нескольких чисел.
    # Номера исполнительных производств и дел разбираются отдельными
    # правилами, поэтому ограничение им не мешает.
    if sum(text.count(char) for char in _SEPARATORS) > 2:
        return False
    return any(char.isdigit() for char in text)


def _add(
    found: dict[str, Candidate],
    text: str,
    value: str,
    span: tuple[int, int],
    kind: str,
    confidence: float,
    role: str = "",
) -> None:
    value = value.strip().strip(".,;")
    if not value:
        return
    if kind in ("document_number", "contract_number") and DATE_LIKE_RE.match(value):
        # Это дата, а не номер: она попадёт в имя как дата.
        return
    if kind in ("document_number", "contract_number") and not is_plausible_number(value):
        return
    key = f"{kind}:{value.casefold()}"
    candidate = Candidate(
        value=value,
        position=span[0],
        context=context_window(text, *span),
        source=Source.REGEX,
        role_guess=role or kind,
        confidence=min(0.99, confidence + head_position_bonus(span[0], len(text))),
        kind=kind,
    )
    current = found.get(key)
    if current is None or candidate.confidence > current.confidence:
        found[key] = candidate


def validate_inn(value: str) -> bool:
    """Проверить контрольную сумму ИНН (10 или 12 цифр)."""
    if not value.isdigit():
        return False
    digits = [int(ch) for ch in value]
    if len(digits) == 10:
        weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        checksum = sum(w * d for w, d in zip(weights, digits[:9], strict=True)) % 11 % 10
        return checksum == digits[9]
    if len(digits) == 12:
        weights_11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        weights_12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        first = sum(w * d for w, d in zip(weights_11, digits[:10], strict=True)) % 11 % 10
        second = sum(w * d for w, d in zip(weights_12, digits[:11], strict=True)) % 11 % 10
        return first == digits[10] and second == digits[11]
    return False


def validate_ogrn(value: str) -> bool:
    """Проверить контрольный разряд ОГРН (13 цифр) или ОГРНИП (15 цифр)."""
    if not value.isdigit():
        return False
    if len(value) == 13:
        return int(value[:-1]) % 11 % 10 == int(value[-1])
    if len(value) == 15:
        return int(value[:-1]) % 13 % 10 == int(value[-1])
    return False


def extract_identifiers(text: str) -> dict[str, list[Candidate]]:
    """Найти номера и реквизиты, разложив их по типам."""
    if not text:
        return {}
    found: dict[str, Candidate] = {}

    for match in ENFORCEMENT_RE.finditer(text):
        value = match.group(1)
        confidence = 0.96 if value.upper().endswith("-ИП") else 0.8
        _add(found, text, value, match.span(1), "enforcement_number", confidence, "case_number")

    for match in ARBITRATION_CASE_RE.finditer(text):
        _add(found, text, match.group(1), match.span(1), "case_number", 0.95)

    for pattern in (COURT_CASE_RE, GENERIC_CASE_RE):
        for match in pattern.finditer(text):
            _add(found, text, match.group(1), match.span(1), "case_number", 0.9)

    for match in CONTRACT_RE.finditer(text):
        _add(found, text, match.group(1), match.span(1), "contract_number", 0.92)

    for match in INN_RE.finditer(text):
        value = match.group(1)
        _add(found, text, value, match.span(1), "inn", 0.97 if validate_inn(value) else 0.5)

    for match in OGRN_RE.finditer(text):
        value = match.group(1)
        _add(found, text, value, match.span(1), "ogrn", 0.97 if validate_ogrn(value) else 0.5)

    for match in KPP_RE.finditer(text):
        _add(found, text, match.group(1), match.span(1), "kpp", 0.9)

    for match in WRIT_RE.finditer(text):
        _add(
            found,
            text,
            f"{match.group(1)} {match.group(2)}",
            match.span(),
            "writ_number",
            0.93,
        )

    known_values = {c.value for c in found.values()}
    for match in NUMBER_AFTER_SIGN_RE.finditer(text):
        value = match.group(1)
        if value in known_values or any(value in known for known in known_values):
            continue
        _add(found, text, value, match.span(1), "document_number", 0.85)

    grouped: dict[str, list[Candidate]] = {}
    for candidate in found.values():
        grouped.setdefault(candidate.kind, []).append(candidate)
    for values in grouped.values():
        values.sort(key=lambda c: (-c.confidence, c.position))
    return grouped


#: Приоритет типов номеров при выборе главного идентификатора имени файла.
IDENTIFIER_PRIORITY: tuple[str, ...] = (
    "enforcement_number",
    "case_number",
    "writ_number",
    "contract_number",
    "document_number",
)


def select_identifier(grouped: dict[str, list[Candidate]]) -> Candidate | None:
    """Выбрать главный идентификатор для имени файла."""
    for kind in IDENTIFIER_PRIORITY:
        values = grouped.get(kind)
        if values:
            return values[0]
    return None


def select_case_numbers(grouped: dict[str, list[Candidate]], limit: int = 2) -> list[Candidate]:
    """Номера дел и исполнительных производств."""
    result: list[Candidate] = []
    for kind in ("enforcement_number", "case_number"):
        result.extend(grouped.get(kind, []))
    return sorted(result, key=lambda c: (-c.confidence, c.position))[:limit]
