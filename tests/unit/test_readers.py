"""Тесты reader'ов форматов (разделы 15–32, 74 ТЗ)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.analysis import ReaderContext
from docrenamer.config import Config
from docrenamer.paths import AppPaths
from docrenamer.readers import READERS
from docrenamer.readers.archive_reader import read_archive
from docrenamer.readers.docx_reader import read_docx
from docrenamer.readers.eml_reader import read_eml
from docrenamer.readers.html_reader import read_html
from docrenamer.readers.image_reader import read_image
from docrenamer.readers.json_reader import read_json
from docrenamer.readers.media_reader import read_media
from docrenamer.readers.pdf_reader import read_pdf
from docrenamer.readers.pptx_reader import read_pptx
from docrenamer.readers.text_reader import read_csv, read_rtf, read_text
from docrenamer.readers.xlsx_reader import read_xlsx
from docrenamer.readers.xml_reader import read_xml
from docrenamer.security.limits import Limits
from docrenamer.types import Status
from tests.fixtures import builders


@pytest.fixture
def context(config: Config, app_paths: AppPaths) -> ReaderContext:
    return ReaderContext(config=config, paths=app_paths, limits=Limits.from_config(config))


# --- PDF ------------------------------------------------------------------


def test_pdf_text_layer_extracted(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_pdf_with_text(tmp_path / "постановление.pdf")
    result = read_pdf(path, context)

    assert "ПОСТАНОВЛЕНИЕ" in result.text
    assert "652102/26/77028-ИП" in result.text
    assert result.text_quality > 0.7
    assert result.text_language_hint == "ru"
    assert result.page_count == 1
    assert result.metadata["pdf_text_source"] == "text-layer"


def test_pdf_scan_without_text_layer_is_not_treated_as_empty_text(
    tmp_path: Path, context: ReaderContext
) -> None:
    """Скан без OCR не даёт текста, но и не выдаёт ложных данных (раздел 15 ТЗ)."""
    path = builders.make_pdf_scan(tmp_path / "скан.pdf")
    result = read_pdf(path, context)

    assert result.metadata["pdf_text_source"] == "none"
    assert result.text.strip() == ""
    assert Status.EMPTY_DOCUMENT.value in result.statuses


def test_pdf_encrypted_reported(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_pdf_encrypted(tmp_path / "секрет.pdf")
    result = read_pdf(path, context)
    assert Status.PASSWORD_PROTECTED.value in result.statuses


def test_pdf_corrupted_does_not_crash(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_corrupted(tmp_path / "битый.pdf", "pdf")
    result = read_pdf(path, context)
    assert (
        Status.READ_ERROR.value in result.statuses
        or Status.EMPTY_DOCUMENT.value in result.statuses
    )


def test_pdf_ocr_fallback_used_when_layer_bad(tmp_path: Path, context: ReaderContext) -> None:
    """Если текстовый слой пуст, используется результат OCR (раздел 15.1 ТЗ)."""

    class FakeOCR:
        def ocr_pdf(self, path: Path, page_count: int) -> tuple[str, str]:
            return "ПОСТАНОВЛЕНИЕ о возбуждении исполнительного производства", ""

    context.extras["ocr"] = FakeOCR()
    path = builders.make_pdf_scan(tmp_path / "скан.pdf")
    result = read_pdf(path, context)

    assert Status.PDF_OCR_FALLBACK_USED.value in result.statuses
    assert "ПОСТАНОВЛЕНИЕ" in result.text
    assert result.metadata["pdf_text_source"] == "ocr"


# --- офисные форматы -------------------------------------------------------


def test_docx_paragraphs_tables_and_properties(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_docx(tmp_path / "договор.docx")
    result = read_docx(path, context)

    assert "ДОГОВОР ЗАЙМА" in result.text
    assert "Петров Сергей Андреевич" in result.text
    assert result.metadata["title"] == "Договор займа"
    assert result.metadata["table_count"] == 1


def test_xlsx_read_only_with_headers(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_xlsx(tmp_path / "реестр.xlsx")
    result = read_xlsx(path, context)

    assert "Реестр" in result.metadata["sheet_names"]
    assert result.metadata["table_headers"]["Реестр"][0] == "Дата"
    assert "ООО «Альфа»" in result.text


def test_pptx_titles_extracted(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_pptx(tmp_path / "отчёт.pptx")
    result = read_pptx(path, context)

    assert result.metadata["slide_count"] == 1
    assert "Отчёт по делу Иванова" in result.text


# --- текст и разметка ------------------------------------------------------


@pytest.mark.parametrize("encoding", ["utf-8", "windows-1251", "koi8-r", "cp866"])
def test_text_reader_handles_russian_encodings(
    tmp_path: Path, context: ReaderContext, encoding: str
) -> None:
    text = "Договор займа номер 17 от 18 августа 2026 года, Петров Сергей Андреевич, Москва"
    path = builders.make_text(tmp_path / f"файл-{encoding}.txt", text, encoding)
    result = read_text(path, context)

    assert result.text.strip() == text
    assert result.text_language_hint == "ru"
    assert Status.MOJIBAKE_SUSPECTED.value not in result.statuses


def test_csv_delimiter_and_encoding_detected_separately(
    tmp_path: Path, context: ReaderContext
) -> None:
    path = builders.make_csv(tmp_path / "реестр.csv")
    result = read_csv(path, context)

    assert result.metadata["csv_delimiter"] == ";"
    assert result.metadata["csv_headers"][0] == "Дата"
    assert "1251" in result.source_encoding


def test_html_declared_encoding_and_no_script_text(
    tmp_path: Path, context: ReaderContext
) -> None:
    path = builders.make_html(tmp_path / "договор.html")
    result = read_html(path, context)

    assert result.metadata["title"] == "Договор займа № 17"
    assert "ДОГОВОР ЗАЙМА" in result.text
    assert "window.location" not in result.text
    assert "1251" in result.source_encoding


def test_rtf_cyrillic_escapes_decoded(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_rtf(tmp_path / "документ.rtf")
    result = read_rtf(path, context)
    assert "Договор займа" in result.text


def test_xml_external_entity_blocked(tmp_path: Path, context: ReaderContext) -> None:
    """Внешние сущности запрещены (раздел 24 ТЗ)."""
    path = builders.make_xml_bomb(tmp_path / "враждебный.xml")
    result = read_xml(path, context)

    assert "root:" not in result.text
    assert Status.READ_ERROR.value in result.statuses


def test_gpx_track_metadata(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_gpx(tmp_path / "трек.gpx")
    result = read_xml(path, context)

    assert result.metadata["gpx_points"] == 2
    assert result.metadata["gpx_name"] == "Поездка Москва"
    assert result.metadata["gpx_start_time"].startswith("2026-08-03")
    assert result.metadata["gpx_length_km"] > 0


def test_json_structure_and_keys(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_json(tmp_path / "данные.json")
    result = read_json(path, context)

    assert "наименование" in result.metadata["json_keys"]
    assert "Договор займа" in result.text


# --- почта -----------------------------------------------------------------


def test_eml_headers_and_attachment_names(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_eml(tmp_path / "письмо.eml")
    result = read_eml(path, context)

    assert result.metadata["subject"] == "Проект договора займа"
    assert result.metadata["date"] == "2026-05-14"
    assert result.metadata["attachments"] == ["Договор.pdf"]
    assert "Направляю проект договора" in result.text


# --- изображения и медиа ---------------------------------------------------


def test_image_metadata_without_exif(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_jpeg(tmp_path / "IMG_7834.jpg")
    result = read_image(path, context)

    assert result.metadata["width"] == 1600
    assert result.metadata["height"] == 1200
    assert result.metadata["image_format"] == "JPEG"


def test_image_ocr_called_for_document_like_picture(
    tmp_path: Path, context: ReaderContext
) -> None:
    class FakeOCR:
        def ocr_image(self, path: Path) -> tuple[str, str]:
            return "ДОГОВОР ЗАЙМА № 17", ""

    context.extras["ocr"] = FakeOCR()
    path = builders.make_png_document(tmp_path / "скан.png")
    result = read_image(path, context)

    assert "ДОГОВОР ЗАЙМА" in result.text
    assert result.metadata["ocr_used"] is True


@pytest.mark.requires_ffprobe
def test_media_duration_from_ffprobe(tmp_path: Path, context: ReaderContext) -> None:
    from docrenamer.metadata.ffprobe import FFprobeBackend

    backend = FFprobeBackend(context.paths)
    if not backend.available:
        pytest.skip("ffprobe недоступен")
    context.extras["ffprobe"] = backend
    path = builders.make_wav(tmp_path / "запись.wav", seconds=1.5)
    result = read_media(path, context)

    assert result.metadata["duration_label"] in ("00m01s", "00m02s")
    assert result.metadata["duration_seconds"] > 1.0


# --- архивы ----------------------------------------------------------------


def test_archive_is_listed_not_extracted(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_zip(tmp_path / "архив.zip")
    before = {p.name for p in tmp_path.iterdir()}

    result = read_archive(path, context)

    assert result.metadata["entry_count"] == 3
    assert result.metadata["archive_theme"] == "договор-альфа-1".split("-")[0]
    assert {p.name for p in tmp_path.iterdir()} == before, "архив не должен распаковываться"


def test_zip_bomb_ratio_limited(tmp_path: Path, context: ReaderContext) -> None:
    path = builders.make_zip_bomb(tmp_path / "бомба.zip")
    result = read_archive(path, context)

    assert result.metadata["compression_ratio"] > 100
    assert Status.LIMIT_EXCEEDED.value in result.statuses


# --- реестр ----------------------------------------------------------------


def test_registry_covers_declared_formats() -> None:
    """Все заявленные в ТЗ форматы имеют reader (раздел 11 ТЗ)."""
    required = [
        "pdf", "docx", "xlsx", "xlsm", "pptx", "txt", "md", "csv", "html", "xml",
        "json", "rtf", "jpg", "png", "tiff", "heic", "webp", "avif", "bmp", "gif",
        "dng", "mp4", "mov", "avi", "mkv", "webm", "mts", "mp3", "m4a", "wav",
        "flac", "ogg", "wma", "aiff", "amr", "eml", "msg", "zip", "7z", "rar",
        "tar", "gz", "gpx", "kml", "kmz", "doc", "xls", "ppt",
    ]
    missing = [kind for kind in required if kind not in READERS]
    assert missing == [], f"Нет reader'а для: {missing}"
