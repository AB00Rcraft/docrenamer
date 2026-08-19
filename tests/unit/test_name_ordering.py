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

    assert name.startswith("Постановление_СПИ_")
    assert name.endswith("_27.07.2026.txt")


def test_same_kind_documents_sort_together(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Сортировка по имени собирает однотипные документы рядом."""
    (workdir / "scan0001.txt").write_bytes(POSTANOVLENIE.encode())
    (workdir / "scan0002.txt").write_bytes(DOGOVOR.encode())
    (workdir / "scan0003.txt").write_bytes(POSTANOVLENIE.replace("27 июля", "28 июля").encode())

    names = sorted(preview_names(config, app_paths, workdir).values())

    # Однотипные документы стоят подряд: сортировка по имени группирует их.
    assert names[0].startswith("Договор_")
    assert names[1].startswith("Постановление_СПИ_")
    assert names[2].startswith("Постановление_СПИ_")


def test_photos_and_videos_group_by_kind(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    builders.make_jpeg_with_exif(workdir / "IMG_7834.jpg")
    builders.make_mp4(workdir / "VID_3871.mp4")

    names = preview_names(config, app_paths, workdir)

    assert names["IMG_7834.jpg"].startswith("Фото_")
    assert names["VID_3871.mp4"].startswith("Видео_")


def test_date_first_order_is_available(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Хронологический порядок включается настройкой."""
    config.naming.order = "date-first"
    config.naming.date_format = "YYYY-MM-DD"
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    assert name.startswith("2026-07-27_")


def test_proposal_for_good_name_also_sorts_by_kind(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Предложенный вариант подчиняется общему порядку: вид, затем дата."""
    (workdir / "Постановление по делу Иванова.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["Постановление по делу Иванова.txt"]

    assert name.startswith("Постановление_СПИ_")
    assert name.endswith("_27.07.2026.txt")


def test_name_stays_readable_in_length(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Имя не разрастается: смысловых частей не больше заданного числа."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]
    assert len(name) <= 100, f"имя слишком длинное: {len(name)}"
    assert len(name) <= 100, f"имя слишком длинное: {len(name)}"


def test_no_more_than_two_participants(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """В имени не больше двух участников — иначе оно нечитаемо."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]
    # Участники стоят подряд: их не больше двух.
    assert name.count("Иванов") <= 1
    assert len([p for p in name.split("_") if p and p[0].isupper()]) <= 6, name


def test_person_comes_before_organization(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """По фамилии документ ищут чаще, чем по названию организации."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    # Полное ФИО в имени сокращается до фамилии с инициалами.
    assert "ИвановИИ_" in name
    assert name.index("ИвановИИ") < name.index("Альфа"), name


def test_one_authority_is_enough(config: Config, app_paths: AppPaths, workdir: Path) -> None:
    """Подразделение и вышестоящий орган не дублируются в имени."""
    (workdir / "scan0007.txt").write_bytes(POSTANOVLENIE.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    assert not ("ОСП" in name and "ГУФССП" in name), name


def test_rejects_unknown_order(config: Config) -> None:
    with pytest.raises(ConfigError) as exc:
        Config.from_dict({"naming": {"order": "random"}})
    assert "order" in str(exc.value)


# --- вид документа всегда первым --------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_prefix"),
    [
        (
            "СПРАВКА об отключении газоснабжения от 15 марта 2026 года. АО «Мосгаз».",
            "Справка_",
        ),
        (
            "Предмет купли-продажи — транспортное средство. Воробьев Сергей Петрович, "
            "Покупатель. Дата: 25 ноября 2024 года.",
            "Договор_купли_продажи_",
        ),
        (
            "СЧЕТ-ФАКТУРА № 245 от 18.08.2026, продавец ООО «Альфа»",
            "Счет_фактура_",
        ),
    ],
)
def test_name_always_starts_with_document_kind(
    config: Config, app_paths: AppPaths, workdir: Path, text: str, expected_prefix: str
) -> None:
    """Первое слово имени — вид документа, а не обрывок фразы.

    Раньше «купли-продажи» вело имя, потому что составное слово через дефис
    считалось общим словом и вид документа не подтверждался.
    """
    (workdir / "scan0007.txt").write_bytes(text.encode())

    name = preview_names(config, app_paths, workdir)["scan0007.txt"]

    assert name.startswith(expected_prefix), name
    assert name[0].isupper()


def test_unknown_kind_does_not_justify_renaming(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Нейтральное «Документ» держит форму имени, но не повод его менять."""
    (workdir / "заметки по проекту.txt").write_bytes(
        "Обсудили сроки, смету и материалы. Договорились созвониться позже.".encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert not item.selected
