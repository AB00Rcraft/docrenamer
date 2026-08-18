"""Извлечение организаций (раздел 43 ТЗ).

Полное наименование сохраняется для manifest; для имени файла оно
нормализуется отдельно в :mod:`docrenamer.naming.builder`.
"""

from __future__ import annotations

import re

from docrenamer.extractors.common import context_window
from docrenamer.types import Candidate, EntityRef, Source

_UP = "А-ЯЁ"
_LOW = "а-яё"
_QUOTED = r"[«\"']([^»\"'\n]{2,60})[»\"']"

#: «ООО «Альфа»», «ПАО "Сбербанк"», «АО Альфа-Банк»
ABBREVIATED_RE = re.compile(
    r"(?<![-\w])(ООО|ПАО|ЗАО|ОАО|АО|ИП|ФГУП|МУП|ГБУ|ГУП|АНО|ТСЖ|СНТ|НП|КФХ|ППК|ФКУ|ФГБУ)"
    r"[ \u00a0]*"
    rf"(?:{_QUOTED}|([{_UP}][\w\-]*(?:\s+[{_UP}][\w\-]*){{0,3}}))"
)

#: «Общество с ограниченной ответственностью «Альфа»»
FULL_FORM_RE = re.compile(
    r"\b(Общество с ограниченной ответственностью|Акционерное общество|"
    r"Публичное акционерное общество|Закрытое акционерное общество|"
    r"Открытое акционерное общество|Индивидуальный предприниматель|"
    r"Автономная некоммерческая организация)\s*"
    rf"(?:{_QUOTED}|([{_UP}][\w\-]*(?:\s+[\w\-]+){{0,3}}))",
    re.IGNORECASE,
)

#: Государственные органы: «Алтуфьевский ОСП», «Никулинский районный суд»,
#: «ГУФССП России по г. Москве», «ИФНС № 15 по г. Москве».
AUTHORITY_RE = re.compile(
    # Первое слово обязано быть прилагательным («Алтуфьевский», «Никулинского»),
    # иначе в название попадают случайные слова перед аббревиатурой.
    rf"\b([{_UP}][{_LOW}\-]*(?:ский|ская|ское|ского|ской|ском|ные|ный|ная|ное|ного|ной)"
    rf"(?:\s+[{_LOW}\-]+){{0,2}}\s+"
    r"(?:ОСП|РОСП|УФССП|ГУФССП|ФССП|ОВД|УВД|ГУВД|МВД|ИФНС|УФНС|ЗАГС|"
    r"районный суд|городской суд|арбитражный суд|мировой судья|прокуратура))"
)
AUTHORITY_PREFIX_RE = re.compile(
    r"\b((?:ГУФССП|УФССП|ФССП|ИФНС|УФНС|МВД|УМВД|СУ СК)"
    r"(?:\s+России)?"
    rf"(?:\s+№\s*\d+)?"
    rf"(?:\s+по\s+(?:г\.\s*)?[{_UP}][{_LOW}\-]+"
    rf"(?:\s+(?:области|краю|республике|округу|району))?)?)"
)

#: Суды, названия которых начинаются с самого слова «суд»-содержащего оборота.
COURT_RE = re.compile(
    rf"\b((?:Арбитражный|Верховный|Конституционный|Апелляционный|Кассационный)\s+суд"
    rf"(?:\s+(?:города|Республики|края|области|округа)\s+[{_UP}][{_LOW}\-]+)?)"
)

#: «ИП Смирнов С.С.» — за формой следует ФИО, а не название.
SOLE_TRADER_RE = re.compile(
    rf"(?<![-\w])(ИП|Индивидуальный предприниматель)[ \u00a0]+"
    rf"([{_UP}][{_LOW}]+(?:\s+[{_UP}]\.[ ]?[{_UP}]?\.?|\s+[{_UP}][{_LOW}]+\s+[{_UP}][{_LOW}]+))",
    re.IGNORECASE,
)


def extract_organizations(text: str) -> list[Candidate]:
    """Найти организации и государственные органы."""
    if not text:
        return []
    found: dict[str, Candidate] = {}

    def add(display: str, start: int, end: int, confidence: float, kind: str) -> None:
        display = " ".join(display.split()).strip(" ,;:-—")
        # Точка в конце убирается, только если это не инициал («ИП Смирнов С.С.»).
        while display.endswith(".") and not (len(display) >= 2 and display[-2].isupper()):
            display = display[:-1].strip()
        if len(display) < 3:
            return
        key = display.casefold()
        candidate = Candidate(
            value=display,
            position=start,
            context=context_window(text, start, end),
            source=Source.REGEX,
            role_guess=kind,
            confidence=confidence,
            kind=kind,
        )
        current = found.get(key)
        if current is None or candidate.confidence > current.confidence:
            found[key] = candidate

    for match in SOLE_TRADER_RE.finditer(text):
        add(f"ИП {match.group(2).strip()}", match.start(), match.end(), 0.96, "company")

    consumed = {c.position for c in found.values()}
    for match in ABBREVIATED_RE.finditer(text):
        if match.start() in consumed:
            continue
        form = match.group(1)
        name = match.group(2) or match.group(3) or ""
        if not name:
            continue
        add(f"{form} «{name.strip()}»" if match.group(2) else f"{form} {name.strip()}",
            match.start(), match.end(), 0.95, "company")

    for match in FULL_FORM_RE.finditer(text):
        form = match.group(1)
        name = match.group(2) or match.group(3) or ""
        if not name:
            continue
        add(f"{form} «{name.strip()}»", match.start(), match.end(), 0.93, "company")

    for pattern in (AUTHORITY_RE, AUTHORITY_PREFIX_RE, COURT_RE):
        for match in pattern.finditer(text):
            add(match.group(1), match.start(), match.end(), 0.9, "authority")

    return sorted(found.values(), key=lambda c: (-c.confidence, c.position))


def select_organizations(candidates: list[Candidate], limit: int = 2) -> list[EntityRef]:
    """Выбрать организации для имени файла."""
    ordered = sorted(candidates, key=lambda c: (-c.confidence, c.position))[:limit]
    return [
        EntityRef(
            name=c.value,
            role="issuer" if c.kind == "authority" else "party",
            confidence=c.confidence,
            evidence=c.context,
            source=Source.REGEX,
        )
        for c in ordered
    ]
