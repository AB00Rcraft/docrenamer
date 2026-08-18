"""Обязательные сценарии раздела 74 ТЗ, не покрытые другими наборами."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.file_signature import check_extension, detect_type
from docrenamer.paths import AppPaths
from docrenamer.types import Status
from tests.fixtures import builders

pytestmark = pytest.mark.integration


def analyses_by_name(app: Application, directory: Path) -> dict[str, object]:
    return {a.source_path.name: a for a in app.analyze(app.scan(directory))}


def test_unsupported_format_is_reported(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Неизвестный формат честно помечается, а не угадывается (раздел 92 ТЗ)."""
    (workdir / "прошивка.bin").write_bytes(bytes(range(256)) * 8)

    app = Application(config, paths=app_paths)
    analysis = analyses_by_name(app, workdir)["прошивка.bin"]

    assert analysis.has_status(Status.UNSUPPORTED_FORMAT)
    assert analysis.proposed_filename == ""


def test_extension_mismatch_detected_but_extension_kept(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Расхождение фиксируется, расширение автоматически не меняется (раздел 10 ТЗ)."""
    path = workdir / "документ.txt"
    builders.make_pdf_with_text(path)

    detected = detect_type(path)
    assert detected.kind == "pdf"
    assert check_extension(path, detected) == Status.EXTENSION_MISMATCH.value

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    item = plan.items[0]

    assert item.analysis.has_status(Status.EXTENSION_MISMATCH)
    assert item.proposed_filename.endswith(".txt")


def test_duplicate_content_marked_without_action(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дубликаты помечаются, но никаких действий с ними не выполняется (раздел 66 ТЗ)."""
    builders.make_docx(workdir / "копия-1.docx")
    (workdir / "копия-2.docx").write_bytes((workdir / "копия-1.docx").read_bytes())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    duplicates = [i for i in plan.items if Status.DUPLICATE_CONTENT.value in i.statuses]
    assert len(duplicates) == 1
    assert (workdir / "копия-2.docx").exists()

    report = app.apply(plan)
    assert report.renamed == 2, "дубликаты переименовываются, но не удаляются"
    assert len(list(workdir.iterdir())) == 2


def test_sidecar_pair_requires_manual_review(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Sidecar-файлы не переименовываются автоматически (раздел 67 ТЗ)."""
    builders.make_jpeg(workdir / "IMG_1234.jpg")
    (workdir / "IMG_1234.AAE").write_text("<plist/>", encoding="utf-8")

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    assert all(not item.selected for item in plan.items)
    assert any(Status.SIDECAR_DETECTED.value in item.statuses for item in plan.items)


def test_live_photo_pair_requires_manual_review(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Пара HEIC+MOV помечается для ручной проверки (раздел 68 ТЗ)."""
    builders.make_jpeg(workdir / "IMG_1234.jpg")
    (workdir / "IMG_1234.mov").write_bytes(bytes(4) + b"ftypqt  " + bytes(16))

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    assert any(Status.LIVE_PHOTO_PAIR_DETECTED.value in item.statuses for item in plan.items)
    assert all(not item.selected for item in plan.items)


def test_photo_without_exif_uses_filesystem_date_with_marker(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата из ФС допустима только с явной отметкой (разделы 41, 65 ТЗ)."""
    builders.make_jpeg(workdir / "IMG_1822.jpg")

    app = Application(config, paths=app_paths)
    analysis = analyses_by_name(app, workdir)["IMG_1822.jpg"]

    assert analysis.has_status(Status.DATE_SOURCE_FILESYSTEM)
    assert analysis.document_date is not None
    assert analysis.document_date.source.value == "filesystem"
    assert analysis.overall_confidence < config.naming.confidence_threshold


def test_filesystem_date_fallback_can_be_disabled(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Запрет отката на дату файловой системы работает (раздел 65 ТЗ)."""
    builders.make_jpeg(workdir / "IMG_1822.jpg")
    config.naming.allow_filesystem_date_fallback = False

    app = Application(config, paths=app_paths)
    analysis = analyses_by_name(app, workdir)["IMG_1822.jpg"]

    assert analysis.document_date is None


# Короткое замыкание обязательно: в Windows os.geteuid просто не существует.
@pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0,
    reason="проверка прав доступа имеет смысл только на POSIX и не под root",
)
def test_access_denied_does_not_stop_batch(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Недоступный файл не останавливает пакет (раздел 53 ТЗ)."""
    builders.make_docx(workdir / "доступный.docx")
    locked = workdir / "закрытый.docx"
    builders.make_docx(locked)
    locked.chmod(0o000)
    try:
        app = Application(config, paths=app_paths)
        plan = app.preview(workdir)
        report = app.apply(plan)

        assert report.renamed >= 1
        assert not report.critical
    finally:
        locked.chmod(0o644)


def test_mixed_pdf_text_and_scan_pages(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Документ с текстовой и графической страницами читается по текстовому слою."""
    from pypdf import PdfWriter

    text_pdf = builders.make_pdf_with_text(workdir / "часть-1.pdf")
    scan_pdf = builders.make_pdf_scan(workdir / "часть-2.pdf")
    writer = PdfWriter()
    for source in (text_pdf, scan_pdf):
        writer.append(str(source))
    mixed = workdir / "смешанный.pdf"
    with open(mixed, "wb") as handle:
        writer.write(handle)
    text_pdf.unlink()
    scan_pdf.unlink()

    app = Application(config, paths=app_paths)
    analysis = analyses_by_name(app, workdir)["смешанный.pdf"]

    assert analysis.read_result is not None
    assert analysis.read_result.page_count == 2
    assert "ПОСТАНОВЛЕНИЕ" in analysis.read_result.text


def test_empty_and_zero_byte_files(config: Config, app_paths: AppPaths, workdir: Path) -> None:
    """Пустой файл не ломает конвейер и не получает выдуманного имени."""
    (workdir / "пустой.txt").write_bytes(b"")
    (workdir / "пустой.pdf").write_bytes(b"")

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    assert len(plan.items) == 2
    assert all(not item.selected for item in plan.items)


def test_long_russian_name_is_shortened_safely(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Длинное имя укорачивается, оставаясь допустимым для файловой системы."""
    payload = (
        "ПОСТАНОВЛЕНИЕ о возбуждении исполнительного производства "
        "№ 859189755/7728 от 27 июля 2026 года. "
        "Алтуфьевский ОСП ГУФССП России по г. Москве. "
        "Должник: Иванов Иван Иванович. Взыскатель: "
        "Общество с ограниченной ответственностью «Альфа-Бета-Гамма-Дельта-Эпсилон». "
        "Исполнительное производство № 652102/26/77028-ИП."
    )
    (workdir / ("очень-длинное-русское-имя-" * 3 + ".txt")).write_bytes(payload.encode())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    item = plan.items[0]

    assert len(item.proposed_filename) <= config.naming.max_filename_length
    assert len(item.proposed_filename.encode("utf-8")) <= 255
    # Идентификатор переживает укорачивание (раздел 45 ТЗ).
    assert "652102-26-77028-ИП" in item.proposed_filename

    report = app.apply(plan)
    assert not report.critical
    # В Windows суммарный путь может упереться в предел 260 символов — это
    # штатный отказ с понятным кодом, а не сбой (раздел 69 ТЗ).
    allowed = {Status.RENAMED.value, Status.PATH_TOO_LONG.value}
    assert all(r["status"] in allowed for r in report.results), report.results


def test_office_created_property_is_not_document_date(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата из свойств Office не приравнивается к дате документа (раздел 41 ТЗ).

    Свойство ``created`` описывает файл, а не событие: у шаблонов Office оно
    вообще фиктивно. Такое значение допустимо только как запасное, обязано быть
    помечено и не должно давать уверенности для автоматического переименования.
    """
    builders.make_pptx(workdir / "презентация.pptx")

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    item = plan.items[0]
    analysis = item.analysis

    assert analysis.document_date is not None
    assert analysis.has_status(Status.DATE_SOURCE_FILE_PROPERTY)
    assert analysis.document_date.confidence < 0.6
    assert item.confidence < config.naming.confidence_threshold
    assert not item.selected, "файл с сомнительной датой не переименовывается сам"


def test_text_date_wins_over_file_properties(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата, найденная в тексте, всегда важнее свойств файла."""
    builders.make_docx(workdir / "договор.docx")

    app = Application(config, paths=app_paths)
    analysis = analyses_by_name(app, workdir)["договор.docx"]

    assert analysis.document_date is not None
    assert analysis.document_date.value == "2026-08-18"
    assert not analysis.has_status(Status.DATE_SOURCE_FILE_PROPERTY)


def test_gpx_track_gets_meaningful_name(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Трек именуется по данным самого файла (разделы 11, 24 ТЗ)."""
    builders.make_gpx(workdir / "трек.gpx")

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    item = plan.items[0]

    assert item.proposed_filename.startswith("2026-08-03__Трек__Поездка-Москва")
    assert item.proposed_filename.endswith(".gpx")
    assert item.selected
