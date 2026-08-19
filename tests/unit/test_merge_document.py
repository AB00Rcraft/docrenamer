"""Ручное объединение страниц в один документ (раздел 79 ТЗ).

Программа не всегда может понять, что перед ней страницы: сканы без
распознавания ничем не отличаются от отдельных снимков. Тогда решает человек.
"""

from __future__ import annotations

from pathlib import Path

from docrenamer.operations.planner import RenamePlan, merge_as_document
from docrenamer.types import PlanItem, Status


def make_item(path: Path) -> PlanItem:
    return PlanItem(
        source_path=path,
        target_path=path,
        proposed_filename=path.name,
        sha256="0" * 64,
        size=10,
        mtime=0.0,
        confidence=0.4,
    )


def test_pages_get_one_name_with_numbers(workdir: Path) -> None:
    """Восемь сканов получают общее имя и номера страниц по порядку."""
    items = []
    for number in range(1, 9):
        path = workdir / f"скан {number}.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0")
        items.append(make_item(path))
    plan = RenamePlan(root=workdir, items=items)

    accepted, message = merge_as_document(plan, items, "Иск Шахмановой")

    assert accepted, message
    assert items[0].proposed_filename == "Иск Шахмановой_стр_1.jpg"
    assert items[7].proposed_filename == "Иск Шахмановой_стр_8.jpg"
    assert all(Status.MANUAL_NAME.value in item.statuses for item in items)
    assert all(item.selected for item in items)


def test_order_follows_numbers_not_alphabet(workdir: Path) -> None:
    """«10» идёт после «9», а не между «1» и «2»."""
    items = []
    for number in (1, 2, 9, 10):
        path = workdir / f"{number}.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0")
        items.append(make_item(path))
    plan = RenamePlan(root=workdir, items=items)

    merge_as_document(plan, items, "Дело")

    assert [item.proposed_filename for item in items] == [
        "Дело_стр_1.jpg",
        "Дело_стр_2.jpg",
        "Дело_стр_3.jpg",
        "Дело_стр_4.jpg",
    ]


def test_single_file_is_not_a_document(workdir: Path) -> None:
    path = workdir / "скан.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0")
    item = make_item(path)

    accepted, message = merge_as_document(RenamePlan(root=workdir, items=[item]), [item], "Иск")

    assert not accepted
    assert "два" in message


def test_pages_from_different_folders_refused(workdir: Path) -> None:
    inner = workdir / "вложенная"
    inner.mkdir()
    first, second = workdir / "1.jpg", inner / "2.jpg"
    for path in (first, second):
        path.write_bytes(b"\xff\xd8\xff\xe0")
    items = [make_item(first), make_item(second)]

    accepted, message = merge_as_document(RenamePlan(root=workdir, items=items), items, "Иск")

    assert not accepted
    assert "одной папке" in message
