"""Окна программы устроены одинаково.

Разнобой в окнах читается как небрежность: у одного окна шапка, у другого нет,
кнопки разной ширины, главное действие то слева, то справа. Здесь проверяется
общий каркас: заголовок с названием программы, шапка, линия под ней и ряд
кнопок, где главное действие стоит последним и накрашено.

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


def dialogs(gui, workdir: Path):  # type: ignore[no-untyped-def]
    """Все окна программы, кроме главного."""
    from docrenamer.gui import DirectoryDialog, MergeDialog, SettingsDialog
    from docrenamer.types import PlanItem

    def item(name: str) -> PlanItem:
        path = workdir / name
        path.write_bytes(b"\xff\xd8\xff\xe0")
        return PlanItem(
            source_path=path,
            target_path=path,
            proposed_filename=name,
            sha256="0" * 64,
            size=1,
            mtime=0.0,
            confidence=0.9,
        )

    return [
        DirectoryDialog(gui.root, workdir).window,
        MergeDialog(gui.root, [item("скан 1.jpg"), item("скан 2.jpg")]).window,
        SettingsDialog(gui.root, gui.config, gui.paths).window,
    ]


def test_titles_name_the_program(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """В заголовке каждого окна стоит название программы."""
    from docrenamer.gui import APP_TITLE

    for window in dialogs(gui, workdir):
        try:
            assert str(window.title()).startswith(APP_TITLE), window.title()
        finally:
            window.destroy()


def test_every_dialog_has_the_accent_rule(gui, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    """Под шапкой каждого окна — линия цвета программы."""
    from docrenamer.gui import COLORS

    for window in dialogs(gui, workdir):
        try:
            rules = [
                child
                for child in window.winfo_children()
                if isinstance(child, tk.Frame) and str(child.cget("bg")) == COLORS["accent"]
            ]
            assert rules, f"нет линии под шапкой: {window.title()}"
        finally:
            window.destroy()


def test_primary_action_is_last_and_accented(gui) -> None:  # type: ignore[no-untyped-def]
    """Главное действие стоит справа и накрашено, отказ — слева от него."""
    from docrenamer.gui import dialog_buttons

    row = dialog_buttons(
        gui.root, (("Отмена", lambda: None, False), ("Объединить", lambda: None, True))
    )
    buttons = row.winfo_children()

    assert str(buttons[0].cget("text")) == "Отмена"
    assert str(buttons[1].cget("style")) == "Accent.TButton"
    row.destroy()


def test_button_labels_fit(gui) -> None:  # type: ignore[no-untyped-def]
    """Надпись не обрезается даже в длинной кнопке окна."""
    from docrenamer.gui import dialog_buttons

    row = dialog_buttons(gui.root, (("Выбрать эту папку", lambda: None, True),))
    button = row.winfo_children()[0]

    assert int(button.cget("width")) >= len(str(button.cget("text")))
    row.destroy()


def test_dark_titlebar_is_harmless_elsewhere(gui) -> None:  # type: ignore[no-untyped-def]
    """На не-Windows вызов ничего не делает и не падает."""
    from docrenamer.gui import dark_titlebar

    dark_titlebar(gui.root)
