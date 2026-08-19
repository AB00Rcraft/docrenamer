"""Правка предложенного имени руками (раздел 79 ТЗ).

Программа предлагает, решает человек. Введённое имя проходит те же проверки,
что и собранное автоматически.
"""

from __future__ import annotations

from pathlib import Path

from docrenamer.config import Config
from docrenamer.operations.planner import RenamePlan, set_manual_name
from docrenamer.types import PlanItem, Status


def make_item(path: Path, proposed: str) -> PlanItem:
    return PlanItem(
        source_path=path,
        target_path=path.parent / proposed,
        proposed_filename=proposed,
        sha256="0" * 64,
        size=10,
        mtime=0.0,
        confidence=0.9,
    )


def make_plan(workdir: Path, items: list[PlanItem]) -> RenamePlan:
    return RenamePlan(root=workdir, items=items)


def test_manual_name_keeps_extension(workdir: Path, config: Config) -> None:
    """Расширение сохраняется, даже если человек его не написал."""
    source = workdir / "scan0007.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    item = make_item(source, "Договор_18.08.2026.pdf")

    accepted, message = set_manual_name(make_plan(workdir, [item]), item, "Иск Шахмановой")

    assert accepted, message
    assert item.proposed_filename == "Иск Шахмановой.pdf"
    assert item.target_path == workdir / "Иск Шахмановой.pdf"
    assert Status.MANUAL_NAME.value in item.statuses
    assert item.selected


def test_manual_name_refuses_other_extension(workdir: Path) -> None:
    """Расширение менять нельзя: это меняет тип файла, а не его имя."""
    source = workdir / "scan0007.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    item = make_item(source, "Договор.pdf")

    accepted, message = set_manual_name(make_plan(workdir, [item]), item, "Договор.exe")

    assert not accepted
    assert "асширение" in message


def test_manual_name_refuses_collision(workdir: Path) -> None:
    """Два файла не могут получить одно имя."""
    first = workdir / "a.pdf"
    second = workdir / "b.pdf"
    for path in (first, second):
        path.write_bytes(b"%PDF-1.4\n")
    items = [make_item(first, "Иск.pdf"), make_item(second, "Отзыв.pdf")]
    plan = make_plan(workdir, items)

    accepted, message = set_manual_name(plan, items[1], "Иск.pdf")

    assert not accepted
    assert "занято" in message


def test_manual_name_refuses_empty(workdir: Path) -> None:
    source = workdir / "a.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    item = make_item(source, "Иск.pdf")

    accepted, _message = set_manual_name(make_plan(workdir, [item]), item, "   ")

    assert not accepted


def test_manual_name_cleans_forbidden_characters(workdir: Path) -> None:
    """Запрещённые символы убираются, имя остаётся пригодным."""
    source = workdir / "a.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    item = make_item(source, "Иск.pdf")

    accepted, _message = set_manual_name(
        make_plan(workdir, [item]), item, 'Иск: Шахманова / "дело"'
    )

    assert accepted
    for forbidden in ':/"\\':
        assert forbidden not in item.proposed_filename


def test_manual_name_equal_to_current_is_not_a_rename(workdir: Path) -> None:
    """Если человек вернул прежнее имя, файл не переименовывается."""
    source = workdir / "Иск.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    item = make_item(source, "Договор.pdf")

    accepted, _message = set_manual_name(make_plan(workdir, [item]), item, "Иск.pdf")

    assert accepted
    assert not item.selected
    assert item.status == Status.NAME_UNCHANGED.value
