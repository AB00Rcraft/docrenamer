"""Тесты детерминированных extractors (разделы 39–43, 14A.9, 14A.10 ТЗ)."""

from __future__ import annotations

import pytest

from docrenamer.config import load_document_types
from docrenamer.extractors.amounts import extract_amounts
from docrenamer.extractors.dates import extract_dates, select_document_date
from docrenamer.extractors.document_types import DocumentTypeMatcher, select_document_type
from docrenamer.extractors.identifiers import (
    extract_identifiers,
    select_identifier,
    validate_inn,
    validate_ogrn,
)
from docrenamer.extractors.organizations import extract_organizations, select_organizations
from docrenamer.extractors.persons import extract_persons, select_persons

POSTANOVLENIE = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "№ 859189755/7728 от 27 июля 2026 года\n"
    "Алтуфьевский ОСП ГУФССП России по г. Москве\n"
    "Судебный пристав-исполнитель Сидорова А.А.\n"
    "Должник: Иванов Иван Иванович\n"
    "Взыскатель: ООО «Альфа», ИНН 7707083893\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
    "Взыскать 154 300,50 руб.\n"
)


# --- даты ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("документ от 18.08.2026 года", "2026-08-18"),
        ("составлен 18 августа 2026", "2026-08-18"),
        ("подписан 18 августа 2026 г.", "2026-08-18"),
        ("выдан 18 августа 2026 года", "2026-08-18"),
        ('дата «18» августа 2026 г.', "2026-08-18"),
        ("от 5 сент. 2024 г.", "2024-09-05"),
        ("дата 2026-08-18", "2026-08-18"),
    ],
)
def test_russian_date_formats(text: str, expected: str) -> None:
    candidates = extract_dates(text)
    assert any(c.value == expected for c in candidates), [c.value for c in candidates]


def test_two_digit_year_not_interpreted_by_default() -> None:
    """Двузначный год без явной политики не превращается в дату (раздел 14A.9 ТЗ)."""
    candidates = extract_dates("документ от 18.08.26")
    assert all(c.role_guess == "ambiguous_year" for c in candidates)
    assert select_document_date(candidates) is None


def test_two_digit_year_with_explicit_policy() -> None:
    candidates = extract_dates("от 18.08.26", allow_two_digit_year=True)
    assert any(c.value == "2026-08-18" for c in candidates)


def test_impossible_date_rejected() -> None:
    assert extract_dates("от 31.02.2026") == []


def test_document_date_prefers_marker() -> None:
    text = "Приложение 01.01.2020. ПОСТАНОВЛЕНИЕ от 27 июля 2026 года"
    selected = select_document_date(extract_dates(text))
    assert selected is not None
    assert selected.value == "2026-07-27"


def test_metadata_date_wins_when_reliable() -> None:
    selected = select_document_date(
        extract_dates("текст без дат"), metadata_date="2026-08-03", metadata_confidence=0.97
    )
    assert selected is not None
    assert selected.value == "2026-08-03"


# --- лица ------------------------------------------------------------------


def test_full_name_and_role() -> None:
    candidates = extract_persons(POSTANOVLENIE)
    ivanov = next(c for c in candidates if c.value == "Иванов Иван Иванович")
    assert ivanov.role_guess == "должник"
    assert ivanov.confidence > 0.85


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Должник: Иванов Иван Иванович", "Иванов Иван Иванович"),
        ("подписал Иванов И.И.", "Иванов И.И."),
        ("представитель И.И. Иванов", "Иванов И.И."),
        ("пристав Иванов И. И.", "Иванов И.И."),
    ],
)
def test_person_name_variants(text: str, expected: str) -> None:
    values = [c.value for c in extract_persons(text)]
    assert expected in values, values


def test_role_words_are_not_surnames() -> None:
    values = [c.value for c in extract_persons("Сидорова А.А.\nДолжник: Петров Пётр Петрович")]
    assert not any(v.startswith("Должник") for v in values), values


def test_case_parties_preferred_over_officials() -> None:
    selected = select_persons(extract_persons(POSTANOVLENIE), limit=3)
    roles = {p.role for p in selected}
    assert "должник" in roles
    assert "пристав" not in roles


def test_yo_preserved_in_person_name() -> None:
    values = [c.value for c in extract_persons("Должник: Ёлкин Пётр Семёнович")]
    assert "Ёлкин Пётр Семёнович" in values


# --- организации -----------------------------------------------------------


def test_organizations_and_authorities() -> None:
    values = [c.value for c in extract_organizations(POSTANOVLENIE)]
    assert "ООО «Альфа»" in values
    assert any("ОСП" in v for v in values)
    assert any("ГУФССП" in v for v in values)


def test_enforcement_number_suffix_is_not_sole_trader() -> None:
    """«-ИП» в номере производства не порождает индивидуального предпринимателя."""
    values = [c.value for c in extract_organizations("Производство № 652102/26/77028-ИП\nСумма")]
    assert not any(v.startswith("ИП ") for v in values), values


def test_sole_trader_recognized() -> None:
    values = [c.value for c in extract_organizations("Договор с ИП Смирнов С.С. заключён")]
    assert "ИП Смирнов С.С." in values


def test_full_legal_form_recognized() -> None:
    text = 'Общество с ограниченной ответственностью «Бета-Инвест» заключило договор'
    selected = select_organizations(extract_organizations(text))
    assert selected
    assert "Бета-Инвест" in selected[0].name


# --- номера и реквизиты ----------------------------------------------------


def test_identifier_types_are_separated() -> None:
    grouped = extract_identifiers(POSTANOVLENIE)
    assert grouped["enforcement_number"][0].value == "652102/26/77028-ИП"
    assert grouped["document_number"][0].value == "859189755/7728"
    assert grouped["inn"][0].value == "7707083893"


def test_main_identifier_is_enforcement_number() -> None:
    main = select_identifier(extract_identifiers(POSTANOVLENIE))
    assert main is not None
    assert main.value == "652102/26/77028-ИП"


def test_arbitration_case_number() -> None:
    grouped = extract_identifiers("Дело № А40-123456/2026 рассмотрено")
    assert grouped["case_number"][0].value == "А40-123456/2026"


def test_contract_number() -> None:
    grouped = extract_identifiers("ДОГОВОР ЗАЙМА № 17 от 18.08.2026")
    assert grouped["contract_number"][0].value == "17"


@pytest.mark.parametrize(
    ("value", "valid"),
    [("7707083893", True), ("500100732259", True), ("1234567890", False), ("770708389", False)],
)
def test_inn_checksum(value: str, valid: bool) -> None:
    assert validate_inn(value) is valid


@pytest.mark.parametrize(
    ("value", "valid"), [("1027700132195", True), ("1234567890123", False)]
)
def test_ogrn_checksum(value: str, valid: bool) -> None:
    assert validate_ogrn(value) is valid


def test_invalid_checksum_lowers_confidence() -> None:
    grouped = extract_identifiers("ИНН 1234567890")
    assert grouped["inn"][0].confidence < 0.7


# --- суммы -----------------------------------------------------------------


def test_amounts_parsed() -> None:
    values = [c.value for c in extract_amounts("Взыскать 154 300,50 руб. и 25 000 рублей")]
    assert "154300.50 RUB" in values
    assert "25000.00 RUB" in values


# --- типы документов -------------------------------------------------------


@pytest.fixture
def matcher() -> DocumentTypeMatcher:
    return DocumentTypeMatcher(load_document_types())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (POSTANOVLENIE, "Постановление судебного пристава"),
        ("ДОГОВОР ЗАЙМА № 17\nЗаймодавец и Заёмщик заключили настоящий договор", "Договор"),
        ("РЕШЕНИЕ\nИменем Российской Федерации\nсуд решил:", "Решение суда"),
        ("ПРОТОКОЛ допроса свидетеля\nмне разъяснены права", "Протокол допроса"),
        ("СЧЕТ-ФАКТУРА № 245", "Счёт-фактура"),
        ("АПЕЛЛЯЦИОННАЯ ЖАЛОБА на решение суда", "Апелляционная жалоба"),
        ("ИСКОВОЕ ЗАЯВЛЕНИЕ\nпрошу взыскать\nцена иска", "Исковое заявление"),
    ],
)
def test_document_type_matching(matcher: DocumentTypeMatcher, text: str, expected: str) -> None:
    best = select_document_type(matcher.match(text))
    assert best is not None
    assert best.value == expected


def test_specific_type_beats_generic(matcher: DocumentTypeMatcher) -> None:
    ranked = [c.value for c in matcher.match(POSTANOVLENIE)]
    assert ranked.index("Постановление судебного пристава") < ranked.index("Постановление")


def test_dictionary_has_all_required_types() -> None:
    names = {entry["canonical_name"] for entry in load_document_types()}
    required = {
        "Договор", "Дополнительное соглашение", "Акт", "Доверенность", "Претензия",
        "Исковое заявление", "Отзыв", "Возражения", "Жалоба", "Апелляционная жалоба",
        "Кассационная жалоба", "Ходатайство", "Заявление", "Ответ", "Запрос",
        "Уведомление", "Письмо", "Справка", "Постановление",
        "Постановление судебного пристава", "Постановление следователя",
        "Постановление дознавателя", "Определение суда", "Решение суда", "Приговор",
        "Судебный приказ", "Протокол судебного заседания", "Протокол допроса",
        "Протокол осмотра", "Протокол обыска", "Протокол выемки",
        "Обвинительное заключение", "Обвинительный акт", "Заключение эксперта",
        "Исполнительный лист", "Платёжное поручение", "Счёт", "Счёт-фактура",
        "Акт сверки", "Выписка", "Банковская выписка", "Расписка",
        "Товарная накладная", "Служебная записка", "Приказ", "Распоряжение",
    }
    assert required - names == set()
