"""Самопроверка имени — второй проход (требование приёмки).

Проверки второго прохода намеренно независимы от логики сборки имени: именно
поэтому они ловят её ошибки.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.naming.review import Issue, is_blocking, review_name, review_segments
from docrenamer.naming.sanitizer import Segment
from docrenamer.paths import AppPaths
from docrenamer.types import Status


def codes(issues: list[Issue]) -> set[str]:
    return {issue.code for issue in issues}


# --- сегменты ---------------------------------------------------------------


def test_date_outside_date_segment_is_removed() -> None:
    """Дата, попавшая в номер документа, из имени убирается."""
    segments = [
        Segment("Договор", 80, kind="type"),
        Segment("11.12.2026", 90, kind="identifier"),
        Segment("25.11.2024", 95, kind="date"),
    ]
    kept, issues = review_segments(
        [Segment("Договор", 80, kind="type"), Segment("11.12.2026", 90, kind="subject"),
         Segment("25.11.2024", 95, kind="date")]
    )

    assert [s.text for s in kept] == ["Договор", "25.11.2024"]
    assert "date_outside_date" in codes(issues)
    # У настоящего номера дата-подобный вид допустим.
    kept_identifier, _ = review_segments(segments)
    assert len(kept_identifier) == 3


def test_bare_number_is_removed() -> None:
    kept, issues = review_segments(
        [Segment("Договор", 80, kind="type"), Segment("2", 40, kind="subject")]
    )

    assert [s.text for s in kept] == ["Договор"]
    assert "bare_number" in codes(issues)


def test_repeated_words_are_removed() -> None:
    kept, issues = review_segments(
        [Segment("Постановление", 80, kind="type"), Segment("постановление", 40, kind="subject")]
    )

    assert len(kept) == 1
    assert "duplicate" in codes(issues)


# --- готовое имя ------------------------------------------------------------


def test_two_dates_block_the_name() -> None:
    issues = review_name("Договор_11.12.2026_25.11.2024.pdf", max_length=160)

    assert "many_dates" in codes(issues)
    assert is_blocking(issues)


def test_wrong_date_blocks_the_name() -> None:
    issues = review_name("Договор_01.01.2020.pdf", max_length=160, expected_date="25.11.2024")

    assert "wrong_date" in codes(issues)
    assert is_blocking(issues)


def test_lowercase_start_is_reported_but_not_blocking() -> None:
    issues = review_name("купли-продажи_Воробьев_25.11.2024.pdf", max_length=160)

    assert "lowercase_start" in codes(issues)
    assert not is_blocking(issues)


def test_double_separator_is_reported() -> None:
    assert "double_separator" in codes(review_name("Договор__Петров.pdf", max_length=160))


def test_broken_characters_block_the_name() -> None:
    issues = review_name("Договор_���.pdf", max_length=160)

    assert "broken_text" in codes(issues)
    assert is_blocking(issues)


def test_correct_name_has_no_issues() -> None:
    assert review_name(
        "Постановление_СПИ_ИвановИИ_652102_26_77028-ИП_27.07.2026.pdf",
        max_length=160,
        expected_date="27.07.2026",
    ) == []


# --- сквозная проверка ------------------------------------------------------


def test_pipeline_records_review_notes(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Замечания второго прохода сохраняются в разборе — их видно в отчёте."""
    (workdir / "scan0007.txt").write_bytes(
        (
            "ДОГОВОР КУПЛИ-ПРОДАЖИ № 2 г. Москва 25 ноября 2024 года "
            "Афанасиди И.В., именуемый Продавец, и Воробьев Сергей Петрович, "
            "именуемый Покупатель. Срок оплаты до 11.12.2026."
        ).encode()
    )

    app = Application(config, paths=app_paths)
    analysis = app.analyze(app.scan(workdir))[0]
    name = analysis.proposed_filename

    assert name.startswith("Договор"), name
    assert name.count("2024") + name.count("2026") == 1, f"в имени должна быть одна дата: {name}"
    assert name[0].isupper()


def test_name_is_dropped_when_review_fails(
    config: Config, app_paths: AppPaths, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если имя не прошло проверку, файл остаётся как есть."""
    from docrenamer.naming import builder

    monkeypatch.setattr(
        builder,
        "review_name",
        lambda name, **kwargs: [Issue("many_dates", "две даты", name)],
    )
    (workdir / "scan0007.txt").write_bytes(
        "ПОСТАНОВЛЕНИЕ\nот 27 июля 2026 года\nДолжник: Иванов И.И.\n".encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert not item.is_rename, "имя не должно меняться"
    assert item.analysis is not None
    assert item.analysis.has_status(Status.NAME_REVIEW_FAILED)
    assert item.analysis.proposed_filename == ""
    assert not item.selected
