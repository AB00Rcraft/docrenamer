"""Предпросмотр файла и его метаданные.

По содержимому сразу видно, отвечает ли предложенное имя тому, что в файле, а
по метаданным — что переименование ничего в файле не изменило.
"""

from __future__ import annotations

from pathlib import Path

from docrenamer.preview import (
    folder_preview,
    format_size,
    metadata_cell,
    metadata_summary,
    text_preview,
    thumbnail_png,
)
from docrenamer.types import Field, FileAnalysis, PlanItem, ReadResult, Source
from tests.fixtures import builders


def make_item(path: Path, *, text: str = "", kind: str = "file") -> PlanItem:
    analysis = FileAnalysis(source_path=path)
    analysis.detected_type = path.suffix.lstrip(".")
    if text:
        analysis.read_result = ReadResult(text=text)
    analysis.document_type = Field(
        value="Иск", source=Source.TEXT, evidence="исковое заявление", confidence=0.9
    )
    return PlanItem(
        source_path=path,
        target_path=path,
        proposed_filename=path.name,
        sha256="a" * 64,
        size=2048,
        mtime=1_760_000_000.0,
        confidence=0.9,
        analysis=analysis,
        kind=kind,
    )


def test_photo_has_thumbnail(workdir: Path) -> None:
    """Снимок показывается картинкой."""
    path = builders.make_jpeg_with_exif(workdir / "IMG_5608.jpg")

    data = thumbnail_png(path)

    assert data is not None
    assert data.startswith(b"\x89PNG")


def test_pdf_first_page_has_thumbnail(workdir: Path) -> None:
    """У PDF показывается первая страница — по ней и видно, что это."""
    path = builders.make_pdf_with_text(workdir / "1.pdf", "ИСКОВОЕ ЗАЯВЛЕНИЕ")

    data = thumbnail_png(path)

    assert data is not None
    assert data.startswith(b"\x89PNG")


def test_missing_file_has_no_thumbnail(workdir: Path) -> None:
    assert thumbnail_png(workdir / "нет.jpg") is None


def test_text_preview_shows_beginning(workdir: Path) -> None:
    """Показывается то, что программа прочитала: по этому строилось имя."""
    item = make_item(workdir / "иск.pdf", text="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании долга")

    assert "ИСКОВОЕ ЗАЯВЛЕНИЕ" in text_preview(item)


def test_text_preview_explains_absence(workdir: Path) -> None:
    item = make_item(workdir / "скан.jpg")

    assert "не" in text_preview(item).lower()


def test_metadata_cell_shows_size_and_time(workdir: Path) -> None:
    """В списке видно размер и время изменения — то, что меняться не должно."""
    cell = metadata_cell(make_item(workdir / "иск.pdf"))

    assert "КБ" in cell
    assert "." in cell  # дата в российском формате


def test_metadata_summary_mentions_hash(workdir: Path) -> None:
    summary = metadata_summary(make_item(workdir / "иск.pdf"))

    assert "SHA-256" in summary
    assert "не меняет" in summary


def test_folder_preview_lists_contents(workdir: Path) -> None:
    (workdir / "1.pdf").write_bytes(b"%PDF-1.4\n")
    (workdir / "вложенная").mkdir()

    preview = folder_preview(workdir)

    assert "1.pdf" in preview
    assert "вложенная" in preview


def test_format_size() -> None:
    assert format_size(512) == "512 Б"
    assert format_size(2048) == "2 КБ"
    assert format_size(5 * 1024 * 1024) == "5.0 МБ"
