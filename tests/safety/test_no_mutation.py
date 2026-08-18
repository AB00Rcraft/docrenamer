"""Инварианты неизменности пользовательских данных (разделы 2, 76, 77 ТЗ).

Проверяется главное обещание программы: содержимое файлов не меняется, файлы не
удаляются, не перемещаются и не перезаписываются.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.operations.hashing import sha256_file
from docrenamer.paths import AppPaths
from tests.fixtures import builders

pytestmark = pytest.mark.safety


def snapshot(directory: Path) -> dict[str, tuple[str, int]]:
    """Слепок каталога: имя → (SHA-256, размер)."""
    return {
        path.name: (sha256_file(path), path.stat().st_size)
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def content_multiset(directory: Path) -> list[tuple[str, int]]:
    """Множество содержимого без учёта имён."""
    return sorted(snapshot(directory).values())


@pytest.fixture
def corpus(workdir: Path) -> Path:
    """Разнородный набор файлов, включая двоичные."""
    builders.make_pdf_with_text(workdir / "постановление.pdf")
    builders.make_docx(workdir / "договор.docx")
    builders.make_xlsx(workdir / "реестр.xlsx")
    builders.make_pptx(workdir / "презентация.pptx")
    builders.make_jpeg(workdir / "IMG_7834.jpg")
    builders.make_png_document(workdir / "скан.png")
    builders.make_wav(workdir / "запись.wav")
    builders.make_eml(workdir / "письмо.eml")
    builders.make_zip(workdir / "архив.zip")
    builders.make_gpx(workdir / "трек.gpx")
    builders.make_text(workdir / "заметка.txt", "Договор займа номер 17", "cp1251")
    builders.make_corrupted(workdir / "битый.pdf", "pdf")
    return workdir


def test_analysis_does_not_touch_files(
    config: Config, app_paths: AppPaths, corpus: Path
) -> None:
    """Чтение и анализ не меняют ни один байт."""
    before = snapshot(corpus)
    app = Application(config, paths=app_paths)

    app.analyze(app.scan(corpus))

    assert snapshot(corpus) == before


def test_preview_changes_nothing(config: Config, app_paths: AppPaths, corpus: Path) -> None:
    before = snapshot(corpus)
    app = Application(config, paths=app_paths)

    app.preview(corpus)

    assert snapshot(corpus) == before


def test_apply_changes_only_names(config: Config, app_paths: AppPaths, corpus: Path) -> None:
    """После APPLY меняются имена, но не содержимое и не количество файлов."""
    before_contents = content_multiset(corpus)
    before_count = len(list(corpus.iterdir()))
    app = Application(config, paths=app_paths)

    plan = app.preview(corpus)
    report = app.apply(plan)

    assert not report.critical
    assert len(list(corpus.iterdir())) == before_count, "число файлов изменилось"
    assert content_multiset(corpus) == before_contents, "изменилось содержимое файлов"


def test_no_file_leaves_its_directory(
    config: Config, app_paths: AppPaths, corpus: Path, tmp_path: Path
) -> None:
    """Файлы не перемещаются в другие каталоги (раздел 2 ТЗ)."""
    nested = corpus / "Том 1"
    nested.mkdir()
    builders.make_docx(nested / "приложение.docx")
    outside_before = {p.name for p in tmp_path.iterdir()}

    app = Application(config, paths=app_paths)
    plan = app.preview(corpus)
    app.apply(plan)

    assert len(list(nested.iterdir())) == 1
    assert {p.name for p in tmp_path.iterdir()} == outside_before


def test_existing_files_are_never_overwritten(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Занятое имя получает суффикс, чужой файл остаётся нетронутым."""
    builders.make_docx(workdir / "a.docx")
    builders.make_docx(workdir / "b.docx")
    guard = workdir / "2026-08-18__Договор__ООО-Альфа--Петров__17.docx"
    guard.write_bytes(b"NE TROGAT")
    guard_hash = hashlib.sha256(b"NE TROGAT").hexdigest()

    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(workdir))

    assert not report.critical
    assert sha256_file(guard) == guard_hash


def test_undo_restores_bytes_exactly(
    config: Config, app_paths: AppPaths, corpus: Path
) -> None:
    before = snapshot(corpus)
    app = Application(config, paths=app_paths)

    report = app.apply(app.preview(corpus))
    assert report.manifest_path is not None
    app.undo(report.manifest_path)

    assert snapshot(corpus) == before


def test_hash_recorded_before_equals_after(
    config: Config, app_paths: AppPaths, corpus: Path
) -> None:
    """Manifest фиксирует совпадение контрольных сумм (раздел 76 ТЗ)."""
    import json

    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(corpus))
    assert report.manifest_path is not None

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert manifest["records"]
    for record in manifest["records"]:
        assert record["sha256_before"] == record["sha256_after"]
        assert len(record["sha256_before"]) == 64


def test_corrupted_file_does_not_break_batch(
    config: Config, app_paths: AppPaths, corpus: Path
) -> None:
    """Одна ошибка не останавливает пакет (раздел 53 ТЗ)."""
    app = Application(config, paths=app_paths)
    plan = app.preview(corpus)

    assert any(item.source_path.name == "битый.pdf" for item in plan.items)
    report = app.apply(plan)
    assert report.renamed >= 1
    assert not report.critical
