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


def test_row_menu_exists(gui) -> None:  # type: ignore[no-untyped-def]
    """Действия над файлом живут в меню строки, а не в ряду кнопок."""
    labels = [
        gui.row_menu.entrycget(index, "label")
        for index in range(gui.row_menu.index("end") + 1)
        if gui.row_menu.type(index) == "command"
    ]

    assert any("Изменить имя" in label for label in labels), labels
    assert any("Пересканировать" in label for label in labels), labels
    assert any("одним документом" in label for label in labels), labels
    assert any("метаданные" in label for label in labels), labels


def test_shift_click_does_not_toggle(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """С Shift щелчок выделяет строки, а не переключает галочку."""
    item = make_item(workdir / "договор.docx", "Договор.docx")
    gui._show_plan(RenamePlan(root=workdir, items=[item]))

    class FakeEvent:
        x = 20
        y = 10
        state = 0x0001  # Shift

    assert gui._on_click(FakeEvent()) is None
    assert item.selected


def test_card_sits_under_preview(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Сведения о файле показываются под предпросмотром, в правой колонке."""
    preview_row = gui.preview_text.master.grid_info()["row"]
    details_row = gui.details.master.grid_info()["row"]

    assert gui.preview_text.master.master is gui.details.master.master
    assert int(details_row) > int(preview_row)


def test_selecting_row_fills_card(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """При выборе строки карточка заполняется сведениями о файле."""
    path = workdir / "скан.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    item = make_item(path, "Иск_12.05.2026.pdf")
    gui._show_plan(RenamePlan(root=workdir, items=[item]))
    gui.tree.selection_set("0")

    gui._show_details()

    card = gui.details.get("1.0", "end")
    assert "скан.pdf" in card
    assert "Иск_12.05.2026.pdf" in card


def make_dialog(gui, workdir: Path, names=("скан 1.jpg", "скан 2.jpg", "скан 3.jpg"), **kwargs):  # type: ignore[no-untyped-def]
    from docrenamer.gui import MergeDialog

    items = []
    for name in names:
        path = workdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff\xe0")
        items.append(make_item(path, path.name))
    return MergeDialog(gui.root, items, **kwargs), items


def test_merge_dialog_toggles_by_click(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Щелчок по строке ставит и снимает отметку, а не сбрасывает остальные."""
    dialog, _items = make_dialog(gui, workdir)
    try:
        assert len(dialog.selected_items()) == 3

        dialog._set_mark("0", False)
        assert [item.source_path.name for item in dialog.selected_items()] == [
            "скан 2.jpg",
            "скан 3.jpg",
        ]

        dialog._mark_all(False)
        assert dialog.selected_items() == []
        dialog._mark_all(True)
        assert len(dialog.selected_items()) == 3
    finally:
        dialog.window.destroy()


def test_merge_dialog_removes_rows(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Лишний файл убирается из списка и в объединение не попадает."""
    dialog, _items = make_dialog(gui, workdir)
    try:
        dialog.tree.selection_set("1")
        dialog._remove_rows()

        assert [item.source_path.name for item in dialog.selected_items()] == [
            "скан 1.jpg",
            "скан 3.jpg",
        ]
    finally:
        dialog.window.destroy()


def test_merge_dialog_adds_files(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Файл, не попавший в разбор, добавляется в список вручную."""
    from docrenamer.operations.planner import make_plan_item

    extra = workdir / "скан 4.jpg"
    extra.write_bytes(b"\xff\xd8\xff\xe0")
    dialog, _items = make_dialog(
        gui, workdir, on_add=lambda path: make_plan_item(path, config=gui.config)
    )
    try:
        item = dialog.on_add(extra)
        assert item is not None
        dialog.items.append(item)
        dialog.added.append(item)
        dialog._insert(item, marked=True)

        assert "скан 4.jpg" in [i.source_path.name for i in dialog.selected_items()]
    finally:
        dialog.window.destroy()


def test_merge_dialog_opens_over_the_window(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Окно открывается над окном программы, а не в углу экрана."""
    gui.root.update_idletasks()
    dialog, _items = make_dialog(gui, workdir)
    try:
        dialog.window.update_idletasks()
        left = dialog.window.winfo_x()
        top = dialog.window.winfo_y()

        assert left >= gui.root.winfo_rootx() - 1
        assert top >= gui.root.winfo_rooty() - 1
        assert left <= gui.root.winfo_rootx() + gui.root.winfo_width()
    finally:
        dialog.window.destroy()


def test_progress_draws_from_the_middle(gui) -> None:  # type: ignore[no-untyped-def]
    """Полоса хода работы растёт от середины окна в обе стороны."""
    gui.progress.canvas.configure(width=200)
    gui.progress.canvas.update_idletasks()

    gui.progress.set(1, 2)
    drawn = gui.progress.canvas.find_all()

    assert drawn, "полоса не нарисована"
    left, _top, right, _bottom = gui.progress.canvas.coords(drawn[0])
    # Пока окно не показано, действительная ширина не известна: и полоса, и
    # проверка считают по запрошенной, иначе сравнивать нечего с чем.
    width = gui.progress.canvas.winfo_width()
    if width <= 1:
        width = gui.progress.canvas.winfo_reqwidth()
    assert abs((left + right) / 2 - width / 2) < 1.0, (left, right, width)
    assert abs((right - left) - width * 0.5) < 1.0, (left, right, width)

    gui.progress.clear()
    assert not gui.progress.canvas.find_all()


def test_merge_button_is_on_the_panel(gui) -> None:  # type: ignore[no-untyped-def]
    """Объединение — частая работа, и кнопка у него своя."""
    assert gui.merge_button.winfo_exists()
    assert gui.merge_button.cget("text") == "Объединить"


def test_merge_dialog_labels_folders(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Когда файлы из разных папок, у каждого написано, где он лежит."""
    from docrenamer.gui import MergeDialog

    inner = workdir / "Дело"
    inner.mkdir()
    items = []
    for path in (workdir / "1.jpg", inner / "2.jpg"):
        path.write_bytes(b"\xff\xd8\xff\xe0")
        items.append(make_item(path, path.name))

    dialog = MergeDialog(gui.root, items, root=workdir)
    try:
        labels = [dialog.tree.item(row, "values")[1] for row in dialog.tree.get_children("")]
        assert labels[0] == "1.jpg"
        assert labels[1].endswith("2.jpg") and "Дело" in labels[1], labels
    finally:
        dialog.window.destroy()
