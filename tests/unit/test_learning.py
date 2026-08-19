"""Журнал обучения: что записывается и чего в нём быть не должно.

Журнал существует ради улучшения алгоритма имён, поэтому главное требование к
нему — обезличенность. Ни имя файла, ни фамилия, ни название организации не
имеют права там оказаться.
"""

from __future__ import annotations

from pathlib import Path

from docrenamer.learning import LearningLog
from docrenamer.paths import AppPaths
from docrenamer.types import EntityRef, Field, FileAnalysis, PlanItem, Source, Status


def make_item(workdir: Path, name: str, proposed: str) -> PlanItem:
    analysis = FileAnalysis(source_path=workdir / name)
    analysis.detected_type = "pdf"
    analysis.document_type = Field(
        value="Иск", source=Source.TEXT, evidence="исковое заявление", confidence=0.9
    )
    analysis.main_persons = [
        EntityRef(name="Шахманова Мария Петровна", confidence=0.9, role="истец")
    ]
    analysis.metadata["document_type_canonical"] = "Исковое заявление"
    return PlanItem(
        source_path=workdir / name,
        target_path=workdir / proposed,
        proposed_filename=proposed,
        sha256="0" * 64,
        size=100,
        mtime=0.0,
        confidence=0.82,
        analysis=analysis,
        status=Status.OK.value,
    )


def test_log_holds_no_names(app_paths: AppPaths, workdir: Path) -> None:
    """В журнале нет ни имени файла, ни фамилии, ни названия организации."""
    log = LearningLog(paths=app_paths, version="1.3.0")
    item = make_item(workdir, "секретный документ Шахмановой.pdf", "Иск_ШахмановаМП_12.05.2026.pdf")

    log.record_applied([item])
    log.record_edit(item, proposed=item.proposed_filename, chosen="Иск Шахмановой.pdf")

    text = log.file.read_text(encoding="utf-8")
    for secret in ("Шахманов", "секретный", "ШахмановаМП", str(workdir)):
        assert secret not in text, text
    assert "Исковое заявление" in text  # вид документа из справочника — можно


def test_report_counts_edits(app_paths: AppPaths, workdir: Path) -> None:
    """Отчёт показывает, как часто имена приходится править."""
    log = LearningLog(paths=app_paths, version="1.3.0")
    item = make_item(workdir, "a.pdf", "Иск_ШахмановаМП_12.05.2026.pdf")
    log.record_applied([item, item])
    log.record_edit(item, proposed=item.proposed_filename, chosen="Иск_Шахмановой.pdf")

    report = log.build_report()

    assert report["records"] == 3
    assert report["edited"] == 1
    assert report["by_document_type"]["Исковое заявление"] == 3
    assert report["kept_first_word"] == 1
    assert report["dropped_date"] == 1


def test_disabled_log_writes_nothing(app_paths: AppPaths, workdir: Path) -> None:
    log = LearningLog(paths=app_paths, version="1.3.0", enabled=False)

    log.record_applied([make_item(workdir, "a.pdf", "Иск.pdf")])

    assert not log.file.exists()


def test_report_saved_next_to_log(app_paths: AppPaths, workdir: Path) -> None:
    log = LearningLog(paths=app_paths, version="1.3.0")
    log.record_applied([make_item(workdir, "a.pdf", "Иск.pdf")])

    path = log.save_report()

    assert path.is_file()
    assert path.parent == app_paths.logs_dir
