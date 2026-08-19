"""Один человек в разных падежах — один раз в имени файла.

В документе человека называют во всех падежах сразу: «должника Иванова»,
«должнику Иванову», «должником Ивановым». Программа считала это разными
людьми, и фамилия попадала в имя файла по три раза.
"""

from __future__ import annotations

from docrenamer.extractors.persons import (
    extract_persons,
    merge_person_candidates,
    nominative_rank,
    person_key,
    select_persons,
)

ПОСТАНОВЛЕНИЕ = """
ПОСТАНОВЛЕНИЕ о возбуждении исполнительного производства

Судебный пристав-исполнитель, рассмотрев исполнительный лист в отношении
должника Иванова Ивана Ивановича, установил, что должник Иванов И.И.
уклоняется от исполнения. Взыскателем является Петров С.А.

ПОСТАНОВИЛ: возбудить исполнительное производство в отношении Иванова И.И.
Копию направить должнику Иванову Ивану Ивановичу.
"""

СПРАВКА = """
СПРАВКА в отношении Шахмановой Марии Петровны

Шахманова Мария Петровна, 12.04.1985 года рождения.
Паспорт выдан на имя Шахмановой М.П.
Проверка в отношении Шахмановой проведена 18 августа 2026 года.
"""


def test_case_forms_share_one_key() -> None:
    """Падежные формы одной фамилии дают один ключ."""
    keys = {
        person_key("Иванова Ивана Ивановича"),
        person_key("Иванову Ивану Ивановичу"),
        person_key("Ивановым Иваном Ивановичем"),
        person_key("Иванов И.И."),
    }
    assert len(keys) == 1


def test_namesakes_stay_different() -> None:
    """Однофамильцы — разные люди: инициалы входят в ключ."""
    assert person_key("Иванов Иван Иванович") != person_key("Иванова Мария Петровна")


def test_short_surnames_are_not_cut() -> None:
    """Короткие фамилии не режутся: «Цой» — это «Цой», а не «Ц»."""
    assert person_key("Цой В.Р.")[0] == "цой"


def test_nominative_is_preferred() -> None:
    """Из найденных форм выбирается именительный падеж."""
    assert nominative_rank("Иванов И.И.") == 2
    assert nominative_rank("Иванову Ивану Ивановичу") == 0
    assert nominative_rank("Шахманова Мария Петровна") == 2
    assert nominative_rank("Шахмановой Марии Петровны") == 0


def test_surname_appears_once(  ) -> None:
    """Три упоминания должника в трёх падежах — одна запись."""
    people = select_persons(extract_persons(ПОСТАНОВЛЕНИЕ), limit=3)
    surnames = [person.name.split()[0] for person in people]

    assert len({person_key(person.name) for person in people}) == len(people)
    assert sum(1 for s in surnames if s.startswith("Иванов")) == 1


def test_role_survives_the_merge() -> None:
    """Роль должника найдена при одном упоминании — она остаётся у человека."""
    people = select_persons(extract_persons(ПОСТАНОВЛЕНИЕ), limit=3)
    debtor = next(p for p in people if person_key(p.name)[0] == "иванов")

    assert debtor.role == "должник"
    assert "Иванов" in debtor.name


def test_dossier_subject_named_once() -> None:
    """В справке по человеку фамилия тоже одна, и в именительном падеже."""
    people = select_persons(extract_persons(СПРАВКА), limit=2)

    assert [p.name for p in people][:1] == ["Шахманова Мария Петровна"]


def test_merge_keeps_the_best_confidence() -> None:
    """Уверенность берётся лучшая из группы, а не последняя."""
    merged = merge_person_candidates(extract_persons(ПОСТАНОВЛЕНИЕ))
    ivanov = next(c for c in merged if person_key(c.value)[0] == "иванов")

    assert ivanov.confidence >= 0.85
