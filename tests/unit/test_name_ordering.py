"""Порядок сегментов в имени и удобство сортировки (требование приёмки).

Файлы должны быть удобно сортировать по имени: первым словом идёт то, по чему
человек ищет документ, а не день месяца.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config, ConfigError
from docrenamer.paths import AppPaths
from tests.fixtures import builders

POSTANOVLENIE = builders.POSTANOVLENIE_TEXT
DOGOVOR = builders.DOGOVOR_TEXT


def preview_names(config: Config, paths: AppPaths, directory: Path) -> dict[str, str]:
    app = Application(config, paths=paths)
    return {i.source_path.name: i.proposed_filename for i in app.preview(directory).items}


def test_name_starts_with_document_kind(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Первое слово имени — вид документа, а не дата."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    assert name.startswith("Постановление-СПИ__")
    assert name.endswith("__27.07.2026.txt")


def test_same_kind_documents_sort_together(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Сортировка по имени собирает однотипные документы рядом."""
    (workdir / "scan0001.txt").write_bytes(POSTANOVLENIE.encode())
    (workdir / "scan0002.txt").write_bytes(DOGOVOR.encode())
    (workdir / "scan0003.txt").write_bytes(POSTANOVLENIE.replace("27 июля", "28 июля").encode())

    names = sorted(preview_names(config, app_paths, workdir).values())
    kinds = [name.split("__")[0] for name in names]

    assert kinds == sorted(kinds), "имена не группируются по виду документа"
    assert kinds[0].startswith("Договор")
    assert kinds[1] == kinds[2] == "Постановление-СПИ"


def test_photos_and_videos_group_by_kind(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    builders.make_jpeg_with_exif(workdir / "IMG_7834.jpg")
    builders.make_mp4(workdir / "VID_3871.mp4")

    names = preview_names(config, app_paths, workdir)

    assert names["IMG_7834.jpg"].startswith("Фото__")
    assert names["VID_3871.mp4"].startswith("Видео__")


def test_date_first_order_is_available(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Хронологический порядок включается настройкой."""
    config.naming.order = "date-first"
    config.naming.date_format = "YYYY-MM-DD"
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    assert name.startswith("2026-07-27__")


def test_preserved_name_also_sorts_by_its_own_words(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """У сохранённого имени дата тоже уходит в конец."""
    (workdir / "Постановление по делу Иванова.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["Постановление по делу Иванова.txt"]

    assert name.startswith("Постановление по делу Иванова")
    assert name.endswith("__27.07.2026.txt")


def test_name_stays_readable_in_length(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Имя не разрастается: смысловых частей не больше заданного числа."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]
    segments = name.rsplit(".", 1)[0].split("__")

    assert len(segments) <= config.naming.max_segments + 1, name
    assert len(name) <= 100, f"имя слишком длинное: {len(name)}"


def test_no_more_than_two_participants(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """В имени не больше двух участников — иначе оно нечитаемо."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]
    entities = [part for part in name.split("__") if "--" in part]

    assert all(len(part.split("--")) <= 2 for part in entities), name


def test_person_comes_before_organization(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """По фамилии документ ищут чаще, чем по названию организации."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    assert "Иванов--" in name


def test_one_authority_is_enough(config: Config, app_paths: AppPaths, workdir: Path) -> None:
    """Подразделение и вышестоящий орган не дублируются в имени."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    assert not ("ОСП" in name and "ГУФССП" in name), name


def test_rejects_unknown_order(config: Config) -> None:
    with pytest.raises(ConfigError) as exc:
        Config.from_dict({"naming": {"order": "random"}})
    assert "order" in str(exc.value)
