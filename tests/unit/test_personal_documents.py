"""Снимки личных документов: паспорт, права, страховка, анкета.

Такие файлы приходят с камеры под именами вида ``IMG_5608.jpg`` и по имени
неотличимы друг от друга. Узнать их можно только по распознанному тексту, и
тогда имя должно начинаться с вида документа, а не со слова «Фото».
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.paths import AppPaths
from tests.fixtures import builders

PASSPORT = (
    "РОССИЙСКАЯ ФЕДЕРАЦИЯ\nПАСПОРТ\nкод подразделения 770-001\n"
    "выдан отделом УФМС России\nИВАНОВ\nИВАН ИВАНОВИЧ\nместо рождения гор. Москва"
)
PASSPORT_SPREAD = (
    "МЕСТО ЖИТЕЛЬСТВА\nзарегистрирован по адресу город Москва улица Тверская\n"
    "отметка о регистрации проставлена отделом"
)
LICENCE = (
    "ВОДИТЕЛЬСКОЕ УДОСТОВЕРЕНИЕ\nПЕТРОВА\nМАРИЯ СЕРГЕЕВНА\n"
    "разрешённые категории B B1 M\nдата выдачи 14.03.2021"
)
HOLIDAY = ""


class FakeOCR:
    """Распознавание подменяется: тексты заданы прямо в тесте."""

    def __init__(self, texts: dict[str, str]) -> None:
        self.texts = texts

    def ocr_image(self, path: Path) -> tuple[str, str]:
        return self.texts.get(path.name, ""), ""

    def ocr_pdf(self, path: Path, pages: int) -> tuple[str, str]:
        return "", ""


def preview(
    config: Config, app_paths: AppPaths, workdir: Path, texts: dict[str, str]
) -> dict[str, str]:
    app = Application(config, paths=app_paths)
    app.analyzer.context.extras["ocr"] = FakeOCR(texts)
    return {a.source_path.name: a.proposed_filename for a in app.analyze(app.scan(workdir))}


@pytest.fixture
def photos(workdir: Path) -> Path:
    return workdir


def test_passport_photo_named_by_document(
    config: Config, app_paths: AppPaths, photos: Path
) -> None:
    """Имя снимка паспорта начинается с вида документа и содержит владельца."""
    builders.make_jpeg_with_exif(photos / "IMG_5608.jpg")

    name = preview(config, app_paths, photos, {"IMG_5608.jpg": PASSPORT})["IMG_5608.jpg"]

    assert name.startswith("Паспорт_"), name
    assert "ИвановИИ" in name, name
    assert "фото" in name, name


def test_uppercase_name_is_readable(
    config: Config, app_paths: AppPaths, photos: Path
) -> None:
    """ФИО прописными буквами приводится к обычному виду."""
    builders.make_jpeg_with_exif(photos / "IMG_5610.jpg")

    name = preview(config, app_paths, photos, {"IMG_5610.jpg": LICENCE})["IMG_5610.jpg"]

    assert name.startswith("Водительское_удостоверение_"), name
    assert "ПетроваМС" in name, name
    assert "ПЕТРОВА" not in name, name


def test_scan_pages_keep_order(config: Config, app_paths: AppPaths, photos: Path) -> None:
    """Подряд снятые страницы получают номера, и порядок виден по имени."""
    texts = {}
    for offset, text in enumerate((PASSPORT, PASSPORT_SPREAD, PASSPORT_SPREAD)):
        name = f"IMG_{5608 + offset}.jpg"
        builders.make_jpeg_with_exif(photos / name)
        texts[name] = text

    names = preview(config, app_paths, photos, texts)

    assert "стр_1" in names["IMG_5608.jpg"], names
    assert "стр_2" in names["IMG_5609.jpg"], names
    assert "стр_3" in names["IMG_5610.jpg"], names
    # Реквизиты с титульной страницы переходят на развороты без шапки.
    assert all(n.startswith("Паспорт_ИвановИИ") for n in names.values()), names
    assert sorted(names.values()) == [names[f"IMG_{5608 + i}.jpg"] for i in range(3)]


def test_ordinary_photos_are_not_pages(
    config: Config, app_paths: AppPaths, photos: Path
) -> None:
    """Подряд снятые кадры без документа страницами не объявляются."""
    texts = {}
    for offset in range(3):
        name = f"DSC_{7001 + offset}.jpg"
        builders.make_jpeg_with_exif(photos / name)
        texts[name] = HOLIDAY

    names = preview(config, app_paths, photos, texts)

    assert all("стр" not in n for n in names.values()), names
