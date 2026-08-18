"""Доказательство работы без сети (разделы 3, 61, 75 ТЗ).

Сетевые вызовы физически блокируются на время теста: любая попытка открыть
сокет приводит к ошибке. Полный рабочий цикл обязан пройти в этих условиях.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from docrenamer.ai.llama_cli import LlamaCliModel
from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.metadata.exiftool import ExifToolBackend
from docrenamer.metadata.ffprobe import FFprobeBackend
from docrenamer.ocr.engine import TesseractEngine
from docrenamer.operations.hashing import sha256_file
from docrenamer.paths import AppPaths
from docrenamer.types import Status
from tests.fixtures import builders

pytestmark = [pytest.mark.safety, pytest.mark.offline]


class NetworkBlocked(RuntimeError):
    """Сетевой вызов во время офлайн-теста."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запретить любые сетевые операции.

    Патчатся методы соединения, а не сам класс ``socket``: подмена класса
    сломала бы стандартный модуль ``ssl``, который от него наследуется.
    """

    def blocked(*args: object, **kwargs: object) -> None:
        raise NetworkBlocked("Программа попыталась обратиться к сети.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "gethostbyname", blocked)


@pytest.fixture
def corpus(workdir: Path) -> Path:
    """Небольшой разнородный набор файлов."""
    builders.make_pdf_with_text(workdir / "постановление.pdf")
    builders.make_docx(workdir / "договор.docx")
    builders.make_text(workdir / "заметка.txt", "Договор займа номер 17", "cp1251")
    builders.make_eml(workdir / "письмо.eml")
    builders.make_zip(workdir / "архив.zip")
    builders.make_jpeg(workdir / "IMG_7834.jpg")
    return workdir


def test_full_cycle_without_network(
    no_network: None, config: Config, app_paths: AppPaths, corpus: Path
) -> None:
    """SCAN → PREVIEW → APPLY → UNDO при заблокированной сети."""
    hashes = {p.name: sha256_file(p) for p in corpus.iterdir()}
    app = Application(config, paths=app_paths)

    plan = app.preview(corpus)
    assert plan.items

    report = app.apply(plan)
    assert report.failed == 0
    assert not report.critical
    assert report.manifest_path is not None

    undo_report = app.undo(report.manifest_path)
    assert undo_report.failed == 0
    assert {p.name for p in corpus.iterdir()} == set(hashes)
    for name, digest in hashes.items():
        assert sha256_file(corpus / name) == digest


def test_text_extraction_works_offline(
    no_network: None, config: Config, app_paths: AppPaths, corpus: Path
) -> None:
    app = Application(config, paths=app_paths)
    analyses = app.analyze(app.scan(corpus))
    texts = {a.source_path.name: (a.read_result.text if a.read_result else "") for a in analyses}

    assert "ПОСТАНОВЛЕНИЕ" in texts["постановление.pdf"]
    assert "ДОГОВОР ЗАЙМА" in texts["договор.docx"]
    assert "Договор займа номер 17" in texts["заметка.txt"]


def test_missing_model_does_not_trigger_download(
    no_network: None, config: Config, app_paths: AppPaths
) -> None:
    """Отсутствие модели не вызывает попытки загрузки (раздел 3 ТЗ)."""
    model = LlamaCliModel(config, app_paths)

    assert model.status() == Status.MODEL_NOT_FOUND.value
    assert "LOCAL_MODEL_NOT_FOUND" in model.missing_model_message()
    # Обращение к модели не поднимает NetworkBlocked — сеть не используется.
    text, status = model.generate("тест")
    assert text == ""
    assert status == Status.MODEL_NOT_FOUND.value


def test_missing_ocr_does_not_trigger_download(
    no_network: None, config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    """Отсутствие OCR не вызывает попытки загрузки (раздел 3 ТЗ)."""
    config.allow_system_binaries = False
    engine = TesseractEngine(config, app_paths)

    assert not engine.available
    text, status = engine.ocr_image(builders.make_jpeg(tmp_path / "скан.jpg"))
    assert text == ""
    assert status == Status.OCR_ENGINE_NOT_FOUND.value


def test_metadata_backends_are_local_only(
    no_network: None, config: Config, app_paths: AppPaths
) -> None:
    """Backend'ы метаданных — локальные процессы, а не сетевые сервисы."""
    exif = ExifToolBackend(app_paths)
    probe = FFprobeBackend(app_paths)

    for backend in (exif, probe):
        if backend.executable is not None:
            assert Path(backend.executable).exists()


def test_no_network_modules_loaded_by_production_graph() -> None:
    """Импорт приложения не подтягивает сетевые библиотеки.

    Проверка выполняется в чистом подпроцессе: в процессе pytest сетевые модули
    может загрузить сам тестовый инструментарий, и это ничего не говорит о
    production-коде.
    """
    import subprocess
    import sys

    program = (
        "import sys;"
        "import docrenamer.app, docrenamer.cli, docrenamer.analysis;"
        "from docrenamer.security.offline_guard import assert_no_network_modules;"
        "loaded = assert_no_network_modules();"
        "extra = sorted(m for m in sys.modules"
        " if m in ('socket', 'ssl', 'http.client', 'urllib.request'));"
        "print(loaded + extra)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]", completed.stdout


def test_archive_listing_works_offline(
    no_network: None, config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    from docrenamer.analysis import ReaderContext
    from docrenamer.readers.archive_reader import read_archive
    from docrenamer.security.limits import Limits

    context = ReaderContext(config=config, paths=app_paths, limits=Limits.from_config(config))
    result = read_archive(builders.make_zip(tmp_path / "архив.zip"), context)
    assert result.metadata["entry_count"] == 3
