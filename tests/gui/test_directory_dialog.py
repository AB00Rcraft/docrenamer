"""Окно выбора папки: видно ли, что в папке лежит.

Системное окно выбора показывает одни названия папок, поэтому программа
рисует своё. Здесь проверяется главное: содержимое видно, в папку можно
войти, и выбранной становится именно та папка, что открыта.

Запускается там, где доступна графическая подсистема (сборка под Windows).
На машинах без дисплея тест пропускается — проверять там нечего.
"""

from __future__ import annotations

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def root():  # type: ignore[no-untyped-def]
    try:
        window = tk.Tk()
    except tk.TclError:  # pragma: no cover — нет дисплея
        pytest.skip("графическая подсистема недоступна")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Папка дела: два документа и вложенная папка со сканами."""
    directory = tmp_path / "Дело Петрова"
    (directory / "Сканы").mkdir(parents=True)
    (directory / "иск.pdf").write_bytes(b"%PDF-1.4\n")
    (directory / "Договор займа №17.docx").write_bytes(b"PK\x03\x04")
    (directory / "Сканы" / "скан 1.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    return directory


def make_dialog(root, folder: Path):  # type: ignore[no-untyped-def]
    from docrenamer.gui import DirectoryDialog

    return DirectoryDialog(root, folder)


def rows(dialog) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        dialog.contents.item(row, "text") for row in dialog.contents.get_children("")
    ]


def test_contents_are_visible(root, folder: Path) -> None:  # type: ignore[no-untyped-def]
    """Сразу видно, что в папке: файлы с именами, папки — с ними же."""
    dialog = make_dialog(root, folder)
    try:
        shown = rows(dialog)
        assert "иск.pdf" in shown
        assert "Договор займа №17.docx" in shown
        assert "📁 Сканы" in shown
        assert "1 папка" in dialog.summary_var.get()
    finally:
        dialog.window.destroy()


def test_size_and_time_are_shown(root, folder: Path) -> None:  # type: ignore[no-untyped-def]
    """У файла показаны размер и время: по ним и узнают нужную папку."""
    dialog = make_dialog(root, folder)
    try:
        row = next(
            row
            for row in dialog.contents.get_children("")
            if dialog.contents.item(row, "text") == "иск.pdf"
        )
        size, changed = dialog.contents.item(row, "values")
        assert size, "размер файла не показан"
        assert changed, "время изменения не показано"
    finally:
        dialog.window.destroy()


def test_double_click_enters_folder(root, folder: Path) -> None:  # type: ignore[no-untyped-def]
    """Двойной щелчок по папке открывает её содержимое."""
    dialog = make_dialog(root, folder)
    try:
        dialog._goto(folder / "Сканы")

        assert dialog.current == folder / "Сканы"
        assert rows(dialog) == ["скан 1.jpg"]
        assert dialog.path_var.get() == str(folder / "Сканы")
    finally:
        dialog.window.destroy()


def test_up_returns_to_parent(root, folder: Path) -> None:  # type: ignore[no-untyped-def]
    """Кнопка «Вверх» поднимает на уровень выше."""
    dialog = make_dialog(root, folder)
    try:
        dialog._go_up()

        assert dialog.current == folder.parent
        assert "📁 Дело Петрова" in rows(dialog)
    finally:
        dialog.window.destroy()


def test_chosen_folder_is_the_open_one(root, folder: Path) -> None:  # type: ignore[no-untyped-def]
    """Выбранной становится та папка, что открыта в окне."""
    dialog = make_dialog(root, folder)
    dialog._goto(folder / "Сканы")

    dialog._accept()

    assert dialog.result == folder / "Сканы"


def test_cancel_returns_nothing(root, folder: Path) -> None:  # type: ignore[no-untyped-def]
    dialog = make_dialog(root, folder)

    dialog._cancel()

    assert dialog.result is None


def test_tree_shows_nested_folders(root, folder: Path) -> None:  # type: ignore[no-untyped-def]
    """Дерево слева раскрывается до открытой папки."""
    dialog = make_dialog(root, folder)
    try:
        node = str(folder)
        assert dialog.tree.exists(node), "открытая папка не показана в дереве"
        dialog._fill(node)
        children = [
            dialog.tree.item(child, "text") for child in dialog.tree.get_children(node)
        ]
        assert children == ["📁 Сканы"]
    finally:
        dialog.window.destroy()


def test_unreadable_folder_does_not_break_window(root, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Пропавшая папка объясняется строкой, окно продолжает работать."""
    dialog = make_dialog(root, tmp_path)
    try:
        dialog._goto(tmp_path / "нет такой")

        assert "нет" in dialog.summary_var.get().lower()
        assert rows(dialog) == []
    finally:
        dialog.window.destroy()
