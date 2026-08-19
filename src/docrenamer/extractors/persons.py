"""Извлечение ФИО (разделы 42, 14A.10 ТЗ).

Учитываются полная форма, инициалы до и после фамилии, а также падежи.
Морфологическая нормализация не меняет отображаемое имя без подтверждения.
"""

from __future__ import annotations

import re

from docrenamer.extractors.common import context_window
from docrenamer.types import Candidate, EntityRef, Source

_UP = "А-ЯЁ"
_LOW = "а-яё"

#: «Иванов Иван Иванович» — отчество распознаётся по суффиксу.
FULL_NAME_RE = re.compile(
    rf"\b([{_UP}][{_LOW}]+(?:-[{_UP}][{_LOW}]+)?)\s+"
    rf"([{_UP}][{_LOW}]+)\s+"
    rf"([{_UP}][{_LOW}]*(?:ович|евич|ьевич|овна|евна|ьевна|ична|инична|оглы|кызы)\w*)"
)

#: «ИВАНОВ ИВАН ИВАНОВИЧ» — так печатают в паспортах и так распознаёт OCR.
UPPERCASE_NAME_RE = re.compile(
    rf"\b([{_UP}]{{2,}})\s+([{_UP}]{{2,}})\s+"
    rf"([{_UP}]*(?:ОВИЧ|ЕВИЧ|ЬЕВИЧ|ОВНА|ЕВНА|ЬЕВНА|ИЧНА|ИНИЧНА|ОГЛЫ|КЫЗЫ))\b"
)

#: «Иванов И.И.» и «Иванов И. И.»
SURNAME_INITIALS_RE = re.compile(
    rf"\b([{_UP}][{_LOW}]+(?:-[{_UP}][{_LOW}]+)?)\s+([{_UP}])\.\s?([{_UP}])?\.?"
)

#: «И.И. Иванов»
INITIALS_SURNAME_RE = re.compile(
    rf"\b([{_UP}])\.[ \u00a0]?([{_UP}])?\.?[ \u00a0]{{1,2}}"
    rf"([{_UP}][{_LOW}]+(?:-[{_UP}][{_LOW}]+)?)\b"
)

#: Роли участников (раздел 42 ТЗ) и слова-маркеры, по которым они опознаются.
ROLE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("должник", ("должник", "должника", "должнику")),
    ("взыскатель", ("взыскатель", "взыскателя", "взыскателю")),
    ("истец", ("истец", "истца", "истцу")),
    ("ответчик", ("ответчик", "ответчика", "ответчику")),
    ("заявитель", ("заявитель", "заявителя", "заявителем")),
    ("обвиняемый", ("обвиняемый", "обвиняемого")),
    ("подозреваемый", ("подозреваемый", "подозреваемого")),
    ("свидетель", ("свидетель", "свидетеля")),
    ("потерпевший", ("потерпевший", "потерпевшего")),
    ("судья", ("судья", "судьи", "председательствующий")),
    ("следователь", ("следователь", "следователя")),
    ("пристав", ("пристав", "пристав-исполнитель", "судебный пристав")),
    ("представитель", ("представитель", "представителя", "по доверенности")),
    ("сторона договора", ("займодавец", "заёмщик", "заемщик", "продавец", "покупатель",
                          "арендодатель", "арендатор", "поставщик", "заказчик", "подрядчик")),
    ("подписант", ("подпись", "подписал", "генеральный директор", "директор"))
    ,
)

#: Слова, которые выглядят как фамилия, но ею не являются.
STOPWORDS = frozenset(
    {
        "российской",
        "федерации",
        "москва",
        "москвы",
        "россии",
        "общество",
        "постановление",
        "определение",
        "решение",
        "договор",
        "приложение",
        "судебный",
        "исполнительное",
        "управление",
        "отделение",
        # Процессуальные роли: часто стоят рядом с ФИО, но фамилиями не являются.
        "должник",
        "взыскатель",
        "истец",
        "ответчик",
        "заявитель",
        "обвиняемый",
        "подозреваемый",
        "свидетель",
        "потерпевший",
        "судья",
        "следователь",
        "пристав",
        "представитель",
        "займодавец",
        "заёмщик",
        "заемщик",
        "продавец",
        "покупатель",
        "директор",
        "приказываю",
    }
)

#: Максимальное расстояние до маркера роли.
ROLE_WINDOW = 90


def _role_for(text: str, position: int) -> tuple[str, float]:
    """Определить роль лица по ближайшему маркеру слева."""
    left = text[max(0, position - ROLE_WINDOW) : position].lower()
    best_role, best_index = "", -1
    for role, markers in ROLE_MARKERS:
        for marker in markers:
            index = left.rfind(marker)
            if index > best_index:
                best_role, best_index = role, index
    if best_index < 0:
        return "", 0.0
    # Чем ближе маркер, тем выше уверенность в роли.
    distance = len(left) - best_index
    return best_role, max(0.4, 1.0 - distance / ROLE_WINDOW)


def extract_persons(text: str) -> list[Candidate]:
    """Найти ФИО в тексте."""
    if not text:
        return []
    found: dict[str, Candidate] = {}

    def add(display: str, start: int, end: int, confidence: float, kind: str) -> None:
        key = display.casefold()
        role, role_confidence = _role_for(text, start)
        candidate = Candidate(
            value=display,
            position=start,
            context=context_window(text, start, end),
            source=Source.REGEX,
            role_guess=role,
            confidence=min(0.99, confidence + 0.05 * role_confidence),
            kind=kind,
        )
        current = found.get(key)
        if current is None or candidate.confidence > current.confidence:
            found[key] = candidate

    for match in FULL_NAME_RE.finditer(text):
        surname, name, patronymic = match.groups()
        if surname.casefold() in STOPWORDS:
            continue
        add(f"{surname} {name} {patronymic}", match.start(), match.end(), 0.9, "full")

    for match in UPPERCASE_NAME_RE.finditer(text):
        surname, name, patronymic = match.groups()
        if surname.casefold() in STOPWORDS:
            continue
        # Отображаем как принято: «Иванов Иван Иванович», а не прописными.
        display = " ".join(part.capitalize() for part in (surname, name, patronymic))
        add(display, match.start(), match.end(), 0.88, "uppercase")

    consumed = {c.position for c in found.values()}
    for match in SURNAME_INITIALS_RE.finditer(text):
        if match.start() in consumed:
            continue
        surname, first, second = match.groups()
        if surname.casefold() in STOPWORDS:
            continue
        initials = f"{first}.{second}." if second else f"{first}."
        add(f"{surname} {initials}", match.start(), match.end(), 0.82, "initials_after")

    for match in INITIALS_SURNAME_RE.finditer(text):
        first, second, surname = match.groups()
        if surname.casefold() in STOPWORDS:
            continue
        initials = f"{first}.{second}." if second else f"{first}."
        add(f"{surname} {initials}", match.start(), match.end(), 0.8, "initials_before")

    return sorted(found.values(), key=lambda c: (-c.confidence, c.position))


#: Роли, наиболее значимые для имени файла, в порядке убывания важности.
ROLE_PRIORITY: tuple[str, ...] = (
    "должник",
    "обвиняемый",
    "подозреваемый",
    "ответчик",
    "истец",
    "заявитель",
    "взыскатель",
    "потерпевший",
    "свидетель",
    "сторона договора",
    "представитель",
    "подписант",
    "судья",
    "следователь",
    "пристав",
)


#: Должностные лица: они ведут дело, но не являются его сторонами. В имя файла
#: попадают только если стороны не установлены.
OFFICIAL_ROLES: frozenset[str] = frozenset({"судья", "следователь", "пристав", "подписант"})


def select_persons(candidates: list[Candidate], limit: int = 3) -> list[EntityRef]:
    """Выбрать ключевых лиц для имени файла (раздел 42 ТЗ)."""
    parties = [c for c in candidates if c.role_guess and c.role_guess not in OFFICIAL_ROLES]
    if parties:
        candidates = parties or candidates

    def sort_key(candidate: Candidate) -> tuple[int, float, int]:
        try:
            role_rank = ROLE_PRIORITY.index(candidate.role_guess)
        except ValueError:
            role_rank = len(ROLE_PRIORITY)
        return role_rank, -candidate.confidence, candidate.position

    selected = sorted(candidates, key=sort_key)[:limit]
    return [
        EntityRef(
            name=c.value,
            role=c.role_guess,
            confidence=c.confidence,
            evidence=c.context,
            source=Source.REGEX,
        )
        for c in selected
    ]
