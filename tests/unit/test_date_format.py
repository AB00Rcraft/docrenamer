"""Формат даты в имени файла (требование приёмки).

Дата в имени выводится по-русски: день, месяц, год. Внутри программы и в
manifest она остаётся канонической ``ГГГГ-ММ-ДД``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config, ConfigError
from docrenamer.naming.dates import date_variants, format_date_for_name
from docrenamer.paths import AppPaths

DOCUMENT = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "№ 859189755/7728 от 27 июля 2026 года\n"
    "Судебный пристав-исполнитель Сидорова А.А.\n"
    "Должник: Иванов Иван Иванович\n"
)


@pytest.mark.parametrize(
    ("value", "date_format", "expected"),
    [
        ("2026-07-27", "DD.MM.YYYY", "27.07.2026"),
        ("2026-07-27", "DD-MM-YYYY", "27-07-2026"),
        ("2026-07-27", "YYYY-MM-DD", "2026-07-27"),
        ("2026-08-03_18.42.17", "DD.MM.YYYY", "03.08.2026_18.42.17"),
        ("2026-01-09", "DD.MM.YYYY", "09.01.2026"),
    ],
)
def test_format_variants(value: str, date_format: str, expected: str) -> None:
    assert format_date_for_name(value, date_format) == expected


def test_unknown_value_is_returned_unchanged() -> None:
    """Непонятное значение не портится — лучше оставить как есть."""
    assert format_date_for_name("без даты", "DD.MM.YYYY") == "без даты"


def test_date_variants_cover_common_writings() -> None:
    variants = date_variants("2026-07-27")
    assert "27.07.2026" in variants
    assert "2026-07-27" in variants
    assert "27-07-2026" in variants


def test_rejects_unknown_format() -> None:
    with pytest.raises(ConfigError) as exc:
        Config.from_dict({"naming": {"date_format": "MM/DD/YYYY"}})
    assert "date_format" in str(exc.value)


def test_default_is_russian_format(config: Config) -> None:
    assert config.naming.date_format == "DD.MM.YYYY"


def test_filename_uses_russian_date(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    (workdir / "scan0007.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.endswith("_27.07.2026.txt")


def test_iso_format_can_be_restored(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Хронологическая сортировка возвращается одной настройкой."""
    config.naming.date_format = "YYYY-MM-DD"
    config.naming.order = "date-first"
    (workdir / "scan0007.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.startswith("2026-07-27_")


def test_manifest_keeps_canonical_date(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """В manifest дата остаётся машинно-читаемой, независимо от имени файла."""
    (workdir / "scan0007.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(workdir))
    assert report.manifest_path is not None

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    analysis = manifest["records"][0]["analysis"] if "analysis" in manifest["records"][0] else None
    assert "27.07.2026" in manifest["records"][0]["new_filename"]
    if analysis:
        assert analysis["document_date"]["value"] == "2026-07-27"


def test_good_name_with_russian_date_is_not_touched(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата в имени уже записана по-русски — второй раз её не добавляем."""
    name = "Постановление от 27.07.2026.txt"
    (workdir / name).write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename == name
    assert not item.selected
