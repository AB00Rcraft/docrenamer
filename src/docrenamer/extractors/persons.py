"""Извлечение ФИО (разделы 42, 14A.10 ТЗ).

Учитываются полная форма, инициалы до и после фамилии, а также падежи.
Морфологическая нормализация не меняет отображаемое имя без подтверждения.
"""

from __future__ import annotations

import re

from docrenamer.extractors.common import context_window
from docrenamer.textquality import comparison_key
from docrenamer.types import Candidate, EntityRef, Source, nfc

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

#: Падежные окончания фамилий. В одном документе человек встречается во всех
#: падежах сразу: «должника Иванова», «должнику Иванову», «должником
#: Ивановым». Это один человек, и в имени файла он обязан стоять один раз.
#: Окончания перечислены от длинных к коротким — снимается первое подошедшее.
CASE_ENDINGS: tuple[str, ...] = (
    "ыми", "ими", "ого", "ому", "ей", "ой", "ом", "ем", "ым", "им",
    "ах", "ях", "ых", "их", "ую", "ю", "у", "е", "ы", "и", "а", "я",
)

#: Сколько букв обязано остаться после снятия окончания. Короткие фамилии
#: («Цой», «Дюма») не склоняются или склоняются иначе — их не трогаем.
MIN_STEM = 4

#: Окончания фамилии в именительном падеже: так человека и называют.
NOMINATIVE_ENDINGS: tuple[str, ...] = (
    "ский", "цкий", "ская", "цкая", "ов", "ев", "ин", "ын", "ко", "ук", "юк", "ых", "их",
)

#: Окончания отчества в именительном падеже.
NOMINATIVE_PATRONYMIC: tuple[str, ...] = (
    "ович", "евич", "ьевич", "ич", "овна", "евна", "ьевна", "ична", "инична",
)

#: Окончания, по которым видно косвенный падеж фамилии.
OBLIQUE_ENDINGS: tuple[str, ...] = (
    "ого", "ому", "ыми", "ими", "ой", "ей", "ом", "ем", "ым", "им", "ую", "ю", "у", "е",
)


def _stem(word: str) -> str:
    """Основа слова без падежного окончания — только для сравнения.

    Отображаемое значение не меняется: полученная основа никуда, кроме ключа
    сравнения, не идёт (раздел 14A.10 ТЗ).
    """
    text = comparison_key(word).strip(".")
    for ending in CASE_ENDINGS:
        if text.endswith(ending) and len(text) - len(ending) >= MIN_STEM:
            return text[: -len(ending)]
    return text


def person_key(name: str) -> tuple[str, ...]:
    """Ключ человека: основа фамилии и инициалы.

    «Иванова Ивана Ивановича», «Иванову Ивану Ивановичу» и «Иванов И.И.» дают
    один ключ. «Иванова Мария Петровна» — другой: однофамильцы остаются
    разными людьми.
    """
    parts = [part for part in re.split(r"[\s\u00a0]+", nfc(name).strip()) if part]
    if not parts:
        return ()
    letters: list[str] = []
    for token in parts[1:]:
        if "." in token:
            letters.extend(ch.casefold() for ch in re.findall(rf"[{_UP}{_LOW}]", token))
        else:
            letters.append(_stem(token)[:1])
    return (_stem(parts[0]), *letters)


def nominative_rank(name: str) -> int:
    """Насколько запись похожа на именительный падеж: 2 — да, 0 — нет.

    Из нескольких найденных в документе форм в имя файла должна попасть та,
    какой человека называют, а не та, что встретилась первой. Придумывать
    форму, которой в документе не было, программа не имеет права, поэтому
    выбор идёт только среди найденного.
    """
    parts = [part for part in re.split(r"[\s\u00a0]+", nfc(name).strip()) if part]
    if not parts:
        return 0
    tail = comparison_key(parts[-1])
    if len(parts) >= 3 and len(tail) > 4:
        return 2 if tail.endswith(NOMINATIVE_PATRONYMIC) else 0
    surname = comparison_key(parts[0])
    if surname.endswith(NOMINATIVE_ENDINGS):
        return 2
    if surname.endswith(OBLIQUE_ENDINGS):
        return 0
    # «Иванова» — и женский именительный, и мужской родительный. Такая форма
    # хуже явного именительного, но лучше явно косвенной.
    return 1 if surname.endswith(("а", "я")) else 2


def merge_person_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Свести формы одного человека в одну запись.

    Остаётся та форма, какой человека называют: сначала именительный падеж,
    затем полное ФИО, затем более уверенная и более ранняя запись. Роль и
    уверенность берутся лучшие из группы — падеж не должен лишать человека
    роли должника только потому, что она нашлась при другом упоминании.
    """
    groups: dict[tuple[str, ...], list[Candidate]] = {}
    order: list[tuple[str, ...]] = []
    for candidate in candidates:
        key = person_key(candidate.value)
        if not key:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(candidate)

    merged: list[Candidate] = []
    for key in order:
        group = groups[key]
        best = min(
            group,
            key=lambda c: (
                -nominative_rank(c.value),
                -len(c.value.split()),
                -c.confidence,
                c.position,
            ),
        )
        with_role = [c for c in group if c.role_guess]
        role_source = max(with_role, key=lambda c: c.confidence) if with_role else best
        merged.append(
            Candidate(
                value=best.value,
                position=min(c.position for c in group),
                context=best.context,
                source=best.source,
                role_guess=role_source.role_guess,
                confidence=max(c.confidence for c in group),
                kind=best.kind,
            )
        )
    return merged


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
    candidates = merge_person_candidates(candidates)
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
