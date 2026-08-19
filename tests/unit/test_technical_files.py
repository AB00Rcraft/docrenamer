"""Служебные файлы: показать, но не трогать.

Ярлыки, файлы настроек и базы программ лежат рядом с документами. Их имена —
часть работы системы, и переименование ломает то, чем они служат.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.paths import AppPaths
from docrenamer.technical import classify_technical
from docrenamer.types import Status
from tests.fixtures import builders


@pytest.mark.parametrize(
    "name",
    [
        "Ярлык программы.lnk",
        "настройки.ini",
        "база.sqlite",
        "журнал.log",
        ".hidden_notes",
        "~$договор.docx",
        "desktop.ini",
    ],
)
def test_technical_files_are_recognized(name: str) -> None:
    assert classify_technical(Path("/дом") / name), name


@pytest.mark.parametrize("name", ["договор.docx", "иск.pdf", "скан 1.jpg", "таблица.xlsx"])
def test_ordinary_files_are_not_technical(name: str) -> None:
    assert not classify_technical(Path("/дом") / name), name


def test_technical_file_is_shown_but_not_renamed(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Строка есть, отметки нет, состояние объясняет причину."""
    builders.make_docx(workdir / "договор.docx")
    (workdir / "Ярлык.lnk").write_bytes(b"L\x00\x00\x00")

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    shortcut = next(item for item in plan.items if item.source_path.name == "Ярлык.lnk")

    assert shortcut.status == Status.TECHNICAL_FILE.value
    assert not shortcut.selected
    assert not shortcut.is_rename
    assert "ярлык" in shortcut.message.lower()


def test_technical_files_are_not_selected_by_select_all(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """«Выбрать все» отмечает только то, что действительно переименовывается."""
    builders.make_docx(workdir / "договор.docx")
    (workdir / "настройки.ini").write_text("[main]\nx=1\n", encoding="utf-8")

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    renameable = [item.source_path.name for item in plan.items if item.is_rename]
    assert "настройки.ini" not in renameable
