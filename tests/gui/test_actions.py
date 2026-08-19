"""Ряд кнопок: надписи помещаются, действия на месте.

Запускается там, где доступна графическая подсистема (сборка под Windows).
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_labels_fit_the_buttons(gui) -> None:  # type: ignore[no-untyped-def]
    """Надпись не обрезается: «Переименовать» должно быть видно целиком."""
    buttons = (
        gui.scan_button,
        gui.preview_button,
        gui.apply_button,
        gui.undo_button,
        gui.merge_button,
        gui.edit_button,
        gui.reveal_button,
    )
    for button in buttons:
        text = str(button.cget("text"))
        assert int(button.cget("width")) >= len(text), text


def test_edit_button_is_in_the_row(gui) -> None:  # type: ignore[no-untyped-def]
    """Правка имени доступна кнопкой, а не только клавишей F2."""
    assert str(gui.edit_button.cget("text")) == "Изменить имя"
    assert gui.edit_button.winfo_manager() == "grid"


def test_reveal_button_sits_by_the_preview(gui) -> None:  # type: ignore[no-untyped-def]
    """Кнопка перехода к файлу стоит рядом с предпросмотром."""
    assert str(gui.reveal_button.cget("text")) == "Перейти к файлу"
    assert gui.reveal_button.master.master is gui.preview_text.master.master


def test_reset_clears_screens_and_returns_home(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Сброс убирает список, предпросмотр и журнал и уводит в домашнюю папку."""
    from docrenamer.types import ScannedFile

    (workdir / "договор.docx").write_bytes(b"PK\x03\x04")
    gui._show_files(
        [ScannedFile(path=workdir / "договор.docx", size=4, mtime=0.0, extension=".docx")]
    )
    gui._log("что-то было сделано")

    gui._reset_session()

    assert gui.tree.get_children("") == ()
    assert gui.plan is None
    assert gui.scanned == []
    assert gui.directory == Path.home()
    assert gui.directory_var.get() == str(Path.home())
    assert "что-то было сделано" not in gui.log.get("1.0", "end")


def test_selected_path_after_scan(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Переход к файлу работает и до предпросмотра, сразу после сканирования."""
    from docrenamer.types import ScannedFile

    path = workdir / "договор.docx"
    path.write_bytes(b"PK\x03\x04")
    gui._show_files([ScannedFile(path=path, size=4, mtime=0.0, extension=".docx")])
    rows = gui.tree.get_children("")
    gui.tree.selection_set(rows[0])

    assert gui._selected_path() == path


def test_period_selector_is_in_the_toolbar(gui) -> None:  # type: ignore[no-untyped-def]
    """Срок выбирается вверху, рядом с папкой и флажками отбора."""
    from docrenamer.scanner import PERIODS

    assert gui.period_var.get() == PERIODS[0][0]
    assert gui._period_days() == 0

    gui._set_period("За месяц")

    assert gui._period_days() == 30
    assert gui.period_var.get() == "За месяц"


def test_plan_arrives_in_batches(gui, workdir) -> None:  # type: ignore[no-untyped-def]
    """Строки дописываются пачками, а не перерисовывают список заново."""
    from docrenamer.operations.planner import RenamePlan
    from docrenamer.types import PlanItem

    def item(name: str) -> PlanItem:
        path = workdir / name
        path.write_bytes(b"PK\x03\x04")
        return PlanItem(
            source_path=path,
            target_path=path.parent / f"Документ_{name}",
            proposed_filename=f"Документ_{name}",
            sha256="0" * 64,
            size=4,
            mtime=0.0,
            confidence=0.9,
        )

    first = RenamePlan(root=workdir, items=[item("иск.docx"), item("отзыв.docx")])
    second = RenamePlan(root=workdir, items=[item("акт.docx")])

    gui._append_plan(first)
    rows_after_first = gui.tree.get_children("")
    gui._append_plan(second)
    rows_after_second = gui.tree.get_children("")

    assert len(rows_after_first) == 2
    assert len(rows_after_second) == 3
    # Первые строки не пересоздавались: их место в дереве осталось прежним.
    assert rows_after_second[:2] == rows_after_first
    assert gui.plan is not None
    assert len(gui.plan.items) == 3
