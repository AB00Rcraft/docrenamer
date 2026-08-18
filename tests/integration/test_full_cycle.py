"""Сквозной цикл SCAN → PREVIEW → APPLY → VERIFY → MANIFEST → UNDO (раздел 91 ТЗ).

Анализатор здесь подменён детерминированной заглушкой: проверяется машинерия
плана, транзакций, manifest и отката, а не качество распознавания.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.logging.manifest import load_manifest
from docrenamer.operations.hashing import sha256_file
from docrenamer.paths import AppPaths
from docrenamer.types import Category, Field, FileAnalysis, ScannedFile, Source, Status

pytestmark = pytest.mark.integration


class StubAnalyzer:
    """Заглушка анализа: имя формируется по номеру файла."""

    def __init__(self, confidence: float = 0.95) -> None:
        self.confidence = confidence

    def analyze(self, scanned: ScannedFile) -> FileAnalysis:
        analysis = FileAnalysis(source_path=scanned.path, detected_type="pdf")
        analysis.category = Category.DOCUMENT
        analysis.document_date = Field("2026-07-27", Source.REGEX, "27 июля 2026 г.", 0.97)
        analysis.document_type = Field(
            "Постановление_СПИ", Source.TEXT, "ПОСТАНОВЛЕНИЕ", 0.96
        )
        analysis.main_persons = []
        analysis.document_number = Field(
            scanned.path.stem.upper(), Source.REGEX, scanned.path.stem, 0.95
        )
        analysis.overall_confidence = self.confidence
        analysis.proposed_filename = (
            f"2026-07-27_Постановление_СПИ_{scanned.path.stem}{scanned.path.suffix}"
        )
        return analysis

    def model_info(self) -> dict[str, Any]:
        return {"enabled": False, "available": False, "engine": "stub", "id": ""}


@pytest.fixture
def app(config: Config, app_paths: AppPaths) -> Application:
    return Application(config, paths=app_paths, analyzer=StubAnalyzer())


@pytest.fixture
def documents(workdir: Path) -> dict[str, bytes]:
    payloads = {
        "дело-1.pdf": "ПОСТАНОВЛЕНИЕ №1 Иванов".encode(),
        "дело-2.pdf": "ПОСТАНОВЛЕНИЕ №2 Петров".encode(),
        "ёжик.pdf": "ПОСТАНОВЛЕНИЕ №3 Ёлкин".encode(),
    }
    for name, data in payloads.items():
        (workdir / name).write_bytes(data)
    return payloads


def test_full_cycle_preserves_content_and_supports_undo(
    app: Application, workdir: Path, documents: dict[str, bytes], app_paths: AppPaths
) -> None:
    hashes_before = {name: sha256_file(workdir / name) for name in documents}

    plan = app.preview(workdir)
    assert len(plan.items) == len(documents)
    assert len(plan.selected_items) == len(documents)
    # PREVIEW ничего не меняет на диске.
    assert {p.name for p in workdir.iterdir()} == set(documents)

    report = app.apply(plan)
    assert report.renamed == len(documents)
    assert report.failed == 0
    assert not report.critical

    renamed = sorted(p.name for p in workdir.iterdir())
    assert all(name.startswith("2026-07-27_Постановление_СПИ_") for name in renamed)

    # Содержимое не изменилось.
    for path in workdir.iterdir():
        original_stem = path.stem.split("_")[-1]
        expected = hashes_before[f"{original_stem}{path.suffix}"]
        assert sha256_file(path) == expected

    # Manifest читается и содержит кириллицу как текст.
    assert report.manifest_path is not None
    raw = report.manifest_path.read_text(encoding="utf-8")
    assert "Постановление" in raw
    assert "\\u041f" not in raw
    manifest = json.loads(raw)
    assert manifest["completed"] is True
    assert len(manifest["records"]) == len(documents)
    for record in manifest["records"]:
        assert record["sha256_before"] == record["sha256_after"]
        assert record["status"] == Status.RENAMED.value

    # Журнал открывается как читаемый русский текст.
    assert report.log_path is not None
    log_text = report.log_path.read_text(encoding="utf-8")
    assert "Encoding: UTF-8" in log_text
    assert "RESULT:" in log_text

    # UNDO возвращает исходные имена и содержимое.
    undo_report = app.undo(report.manifest_path)
    assert undo_report.restored == len(documents)
    assert undo_report.failed == 0
    assert {p.name for p in workdir.iterdir()} == set(documents)
    for name, expected_hash in hashes_before.items():
        assert sha256_file(workdir / name) == expected_hash


def test_undo_refuses_when_original_name_taken(
    app: Application, workdir: Path, documents: dict[str, bytes]
) -> None:
    plan = app.preview(workdir)
    report = app.apply(plan)
    assert report.manifest_path is not None

    # Кто-то создал файл со старым именем.
    intruder = "ЧУЖОЙ ФАЙЛ".encode()
    (workdir / "дело-1.pdf").write_bytes(intruder)

    undo_report = app.undo(report.manifest_path)

    assert undo_report.skipped >= 1
    assert any(
        o["status"] == Status.UNDO_TARGET_EXISTS.value for o in undo_report.outcomes
    )
    assert (workdir / "дело-1.pdf").read_bytes() == intruder


def test_low_confidence_not_applied_but_shown(
    config: Config, app_paths: AppPaths, workdir: Path, documents: dict[str, bytes]
) -> None:
    app = Application(config, paths=app_paths, analyzer=StubAnalyzer(confidence=0.5))

    plan = app.preview(workdir)

    assert len(plan.items) == len(documents)
    assert plan.selected_items == []
    assert all(i.status == Status.SKIPPED_LOW_CONFIDENCE.value for i in plan.items)

    report = app.apply(plan)
    assert report.renamed == 0
    assert {p.name for p in workdir.iterdir()} == set(documents)


def test_collision_gets_numeric_suffix(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    class SameNameAnalyzer(StubAnalyzer):
        def analyze(self, scanned: ScannedFile) -> FileAnalysis:
            analysis = super().analyze(scanned)
            analysis.proposed_filename = "2026-07-27_Постановление.pdf"
            return analysis

    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (workdir / name).write_bytes(name.encode())

    app = Application(config, paths=app_paths, analyzer=SameNameAnalyzer())
    plan = app.preview(workdir)
    report = app.apply(plan)

    names = sorted(p.name for p in workdir.iterdir())
    assert report.renamed == 3
    assert names == [
        "2026-07-27_Постановление.pdf",
        "2026-07-27_Постановление_02.pdf",
        "2026-07-27_Постановление_03.pdf",
    ]


def test_source_changed_after_preview_is_skipped(
    app: Application, workdir: Path, documents: dict[str, bytes]
) -> None:
    plan = app.preview(workdir)
    (workdir / "дело-1.pdf").write_bytes("изменено после предпросмотра".encode())

    report = app.apply(plan)

    assert report.skipped >= 1
    assert (workdir / "дело-1.pdf").exists()
    assert any(
        r["status"] == Status.SOURCE_CHANGED_AFTER_PREVIEW.value for r in report.results
    )


def test_forensic_mode_changes_nothing(
    app: Application, workdir: Path, documents: dict[str, bytes], app_paths: AppPaths
) -> None:
    before = {p.name: sha256_file(p) for p in workdir.iterdir()}

    outputs = app.forensic(workdir)

    assert {p.name: sha256_file(p) for p in workdir.iterdir()} == before
    assert outputs["analysis_report"].is_file()
    assert outputs["rename_plan"].is_file()
    report = json.loads(outputs["analysis_report"].read_text(encoding="utf-8"))
    assert report["strict_local_mode"] is True
    assert len(report["files"]) == len(documents)


def test_manifest_recovers_from_journal(
    app: Application, workdir: Path, documents: dict[str, bytes]
) -> None:
    plan = app.preview(workdir)
    report = app.apply(plan)
    assert report.manifest_path is not None

    # Имитация повреждения JSON при аварийном завершении.
    report.manifest_path.write_text("{ обрезано", encoding="utf-8")
    recovered = load_manifest(report.manifest_path)

    assert len(recovered["records"]) == len(documents)
    assert recovered["completed"] is True
