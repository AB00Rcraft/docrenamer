"""Очистка метаданных — единственная операция, меняющая сам файл.

Поэтому к ней особые требования: она не трогает ничего, кроме указанного
файла; по умолчанию создаёт копию, а не заменяет исходный; изображение не
теряет качества; и то, что удалено, действительно удалено.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.operations.scrub import (
    CLEAN_SUBDIR,
    can_scrub,
    metadata_left,
    scrub_file,
)
from docrenamer.paths import AppPaths
from tests.fixtures import builders


def test_photo_loses_exif_but_keeps_pixels(workdir: Path) -> None:
    """EXIF и GPS исчезают, а изображение остаётся тем же самым."""
    from PIL import Image

    source = builders.make_jpeg_with_exif(workdir / "IMG_5608.jpg")
    with Image.open(source) as image:
        pixels_before = image.tobytes()

    outcome = scrub_file(source)

    assert outcome.ok, outcome.message
    assert outcome.target_path is not None
    with Image.open(outcome.target_path) as cleaned:
        assert cleaned.tobytes() == pixels_before
        assert not cleaned._getexif()
    assert metadata_left(outcome.target_path) == []
    assert any("EXIF" in item for item in outcome.removed), outcome.removed


def test_original_is_untouched_by_default(workdir: Path) -> None:
    """По умолчанию исходный файл остаётся как есть — рядом ложится копия."""
    source = builders.make_jpeg_with_exif(workdir / "IMG_5608.jpg")
    before = source.read_bytes()

    outcome = scrub_file(source)

    assert source.read_bytes() == before
    assert outcome.target_path is not None
    assert outcome.target_path.parent.name == CLEAN_SUBDIR
    assert not outcome.replaced


def test_replace_mode_cleans_in_place(workdir: Path) -> None:
    """С явного согласия человека файл заменяется очищенным."""
    from PIL import Image

    source = builders.make_jpeg_with_exif(workdir / "IMG_5608.jpg")

    outcome = scrub_file(source, replace=True)

    assert outcome.replaced
    assert outcome.target_path == source
    with Image.open(source) as image:
        assert not image._getexif()
    # Временный файл после себя не оставлен.
    assert [p.name for p in workdir.iterdir()] == ["IMG_5608.jpg"]


def test_pdf_properties_removed(workdir: Path) -> None:
    """У PDF исчезают автор, программа и даты, а текст остаётся."""
    from pypdf import PdfReader

    source = builders.make_pdf_with_text(workdir / "иск.pdf", "ИСКОВОЕ ЗАЯВЛЕНИЕ")
    assert PdfReader(str(source)).metadata

    outcome = scrub_file(source)

    assert outcome.ok, outcome.message
    reader = PdfReader(str(outcome.target_path))
    assert not reader.metadata
    assert "ИСКОВОЕ" in (reader.pages[0].extract_text() or "")


def test_office_document_loses_author(workdir: Path) -> None:
    """У документа Office исчезают автор и сведения о правках."""
    source = builders.make_docx(workdir / "договор.docx")

    outcome = scrub_file(source)

    assert outcome.ok, outcome.message
    assert outcome.target_path is not None
    with zipfile.ZipFile(outcome.target_path) as archive:
        core = archive.read("docProps/core.xml").decode("utf-8")
        assert "<dc:creator>" not in core
        assert "lastModifiedBy" not in core
        # Содержимое документа на месте.
        assert "word/document.xml" in archive.namelist()
        # Отметки времени внутри архива обнулены.
        assert {info.date_time[:1] for info in archive.infolist()} == {(1980,)}


def test_unsupported_format_is_refused(workdir: Path) -> None:
    """Программа не делает вид, что очистила то, чего не умеет."""
    source = workdir / "запись.mp3"
    source.write_bytes(b"ID3\x03\x00\x00\x00")

    outcome = scrub_file(source)

    assert not outcome.ok
    assert not can_scrub(source)
    assert "не поддержан" in outcome.message


def test_scrub_touches_only_requested_file(workdir: Path) -> None:
    """Соседние файлы не затрагиваются."""
    target = builders.make_jpeg_with_exif(workdir / "IMG_5608.jpg")
    neighbour = builders.make_jpeg_with_exif(workdir / "IMG_5609.jpg")
    document = builders.make_docx(workdir / "договор.docx")
    untouched = {path: path.read_bytes() for path in (neighbour, document)}

    scrub_file(target, replace=True)

    for path, content in untouched.items():
        assert path.read_bytes() == content


def test_report_is_written(config: Config, app_paths: AppPaths, workdir: Path) -> None:
    """Операция необратима, поэтому след остаётся в отчёте."""
    source = builders.make_jpeg_with_exif(workdir / "IMG_5608.jpg")
    app = Application(config, paths=app_paths)

    report = app.scrub([source])

    assert report.cleaned == 1
    assert report.report_path is not None
    assert report.report_path.is_file()
    assert "IMG_5608.jpg" in report.report_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["скан.png", "снимок.jpg"])
def test_cleaned_copy_opens(workdir: Path, name: str) -> None:
    """Очищенный файл остаётся правильным файлом своего формата."""
    from PIL import Image

    source = (
        builders.make_png_document(workdir / name)
        if name.endswith(".png")
        else builders.make_jpeg_with_exif(workdir / name)
    )

    outcome = scrub_file(source)

    assert outcome.target_path is not None
    with Image.open(outcome.target_path) as image:
        image.load()
        assert image.size == Image.open(source).size
