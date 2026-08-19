"""Таблицы Excel — особая категория (раздел 18 ТЗ).

Суть таблицы чаще написана на ярлычке листа, а не в первой строке, а дат в
ней десятки: ни одна ячейка не является датой документа.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.paths import AppPaths

openpyxl = pytest.importorskip("openpyxl")


def make_book(path: Path, sheet: str, rows: list[list[object]]) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return path


def preview(config: Config, app_paths: AppPaths, workdir: Path) -> dict[str, str]:
    app = Application(config, paths=app_paths)
    return {a.source_path.name: a.proposed_filename for a in app.analyze(app.scan(workdir))}


def test_register_gets_period_not_cell_date(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата из ячейки относится к своей строке, поэтому в имя идёт период."""
    make_book(
        workdir / "книга1.xlsx",
        "Реестр платежей",
        [
            ["Дата", "Контрагент", "Сумма"],
            ["12.01.2025", "ООО «Альфа»", 120000],
            ["03.02.2025", "ООО «Альфа»", 240000],
            ["17.06.2025", "ИП Петров", 85000],
            ["28.11.2025", "ООО «Бета»", 310000],
            ["14.03.2026", "ООО «Альфа»", 150000],
        ],
    )

    name = preview(config, app_paths, workdir)["книга1.xlsx"]

    assert name.startswith("Реестр"), name
    assert "2025-2026" in name, name
    assert "12.01.2025" not in name, name


def test_sheet_tab_names_the_table(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Ярлычок листа — подпись, которую таблице дал человек."""
    make_book(
        workdir / "Книга2.xlsx",
        "Бюджет проекта Север",
        [["Статья", "План", "Факт"], ["Оборудование", 1000, 900]],
    )

    name = preview(config, app_paths, workdir)["Книга2.xlsx"]

    assert name.startswith("Бюджет_"), name
    assert "Север" in name, name
    # Слово «Бюджет» не повторяется: вид документа уже назван.
    assert name.count("Бюджет") == 1, name


def test_type_from_sheet_beats_neutral_label(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """«Смета» точнее нейтральной «Таблицы» и не дублирует прежнее имя."""
    make_book(
        workdir / "смета_кровля_итог.xlsx",
        "Смета",
        [["Локальная смета на ремонт кровли"], ["Работы", "Ед.", "Цена"], ["Демонтаж", "м2", 350]],
    )

    name = preview(config, app_paths, workdir)["смета_кровля_итог.xlsx"]

    assert name.startswith("Смета_"), name
    assert "Таблица" not in name, name
    assert name.lower().count("смета") == 1, name


def test_unrecognized_table_keeps_neutral_label(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Если вид не подтверждён, файл честно называется таблицей."""
    make_book(
        workdir / "данные.xlsx", "Лист1", [["Показатель", "Значение"], ["Температура", 22]]
    )

    name = preview(config, app_paths, workdir)["данные.xlsx"]

    assert name.startswith("Таблица"), name
