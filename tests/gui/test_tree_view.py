"""Дерево переименований: вложенность и отметка папки целиком.

Запускается там, где доступна графическая подсистема (в сборке под Windows).
На машинах без дисплея тест пропускается — проверять там нечего.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.operations.planner import RenamePlan
from docrenamer.types import PlanItem

tk = pytest.importorskip("tkinter")


@pytest.fixture
def gui(config, app_paths, workdir):  # type: ignore[no-untyped-def]
    from docrenamer import gui as gui_module

    try:
        window = gui_module.DocRenamerGUI(config, app_paths, workdir)
    except tk.TclError:  # pragma: no cover — нет дисплея
        pytest.skip("графическая подсистема недоступна")
    yield window
    window.root.destroy()


def make_item(path: Path, proposed: str, *, kind: str = "file") -> PlanItem:
    return PlanItem(
        source_path=path,
        target_path=path.parent / proposed,
        proposed_filename=proposed,
        sha256="0" * 64,
        size=1,
        mtime=0.0,
        confidence=0.9,
        kind=kind,
    )


def test_tree_shows_nesting(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Файлы корня — сверху, содержимое папки — под самой папкой."""
    inner = workdir / "Дело"
    inner.mkdir()
    plan = RenamePlan(
        root=workdir,
        items=[
            make_item(workdir / "договор.docx", "Договор_18.08.2026.docx"),
            make_item(inner / "1.pdf", "Иск_стр_1.pdf"),
            make_item(inner / "2.pdf", "Иск_стр_2.pdf"),
            make_item(inner, "Иск_Шахманова", kind="folder"),
        ],
    )

    gui._show_plan(plan)

    top = gui.tree.get_children("")
    assert len(top) == 2, top
    folder_row = top[-1]
    assert len(gui.tree.get_children(folder_row)) == 2


def test_folder_checkbox_marks_contents(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Отметка на папке распространяется на всё её содержимое."""
    inner = workdir / "Дело"
    inner.mkdir()
    items = [
        make_item(inner / "1.pdf", "Иск_стр_1.pdf"),
        make_item(inner / "2.pdf", "Иск_стр_2.pdf"),
        make_item(inner, "Иск_Шахманова", kind="folder"),
    ]
    gui._show_plan(RenamePlan(root=workdir, items=items))
    folder_row = gui.tree.get_children("")[0]

    gui._set_row_selected(folder_row, toggle=True)

    assert all(not item.selected for item in items)

    gui._set_row_selected(folder_row, toggle=True)

    assert all(item.selected for item in items)


def test_scan_results_show_file_names(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """После сканирования имена файлов видны, а не спрятаны в колонке галочки."""
    from docrenamer.types import ScannedFile

    (workdir / "договор.docx").write_bytes(b"PK\x03\x04")
    scanned = [
        ScannedFile(path=workdir / "договор.docx", size=4, mtime=0.0, extension=".docx")
    ]

    gui._show_files(scanned)

    rows = gui.tree.get_children("")
    assert rows, "список найденных файлов пуст"
    assert gui.tree.item(rows[0], "text") == "договор.docx"
    values = gui.tree.item(rows[0], "values")
    assert len(values) == len(gui.tree["columns"]), values


def test_preview_pane_shows_file(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """При выборе строки справа показывается содержимое файла."""
    from tests.fixtures import builders

    path = builders.make_jpeg_with_exif(workdir / "IMG_5608.jpg")
    item = make_item(path, "Паспорт_ИвановИИ_фото.jpg")
    gui._show_plan(RenamePlan(root=workdir, items=[item]))

    gui._show_preview(item)

    # Снимок показан картинкой, а не текстом.
    assert gui.preview_photo is not None
    assert not gui.preview_text.winfo_ismapped() or gui.preview_image.winfo_ismapped()


def test_preview_falls_back_to_text(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Для документа показывается начало текста."""
    from docrenamer.types import FileAnalysis, ReadResult

    path = workdir / "иск.txt"
    path.write_text("ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании долга", encoding="utf-8")
    item = make_item(path, "Иск_18.08.2026.txt")
    analysis = FileAnalysis(source_path=path)
    analysis.read_result = ReadResult(text="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании долга")
    item.analysis = analysis
    gui._show_plan(RenamePlan(root=workdir, items=[item]))

    gui._show_preview(item)

    assert "ИСКОВОЕ" in gui.preview_text.get("1.0", "end")
