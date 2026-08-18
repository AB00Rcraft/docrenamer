"""Оркестратор приложения (разделы 8, 13, 46, 79, 81, 83 ТЗ).

GUI и CLI не содержат бизнес-логики: оба вызывают методы :class:`Application`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from docrenamer import __version__
from docrenamer.analysis import Analyzer, build_analyzer
from docrenamer.config import Config, load_config, write_json_atomic
from docrenamer.logging.manifest import ManifestWriter, new_manifest_path
from docrenamer.logging.text_log import TextLog, new_log_path
from docrenamer.operations.planner import RenamePlan, build_plan, verify_plan_item
from docrenamer.operations.rename import CriticalSafetyError, rename_file
from docrenamer.operations.undo import UndoReport, undo_session
from docrenamer.paths import AppPaths, default_paths, new_session_id
from docrenamer.scanner import Scanner, ScanStats
from docrenamer.security.temp_cleanup import SessionTemp, cleanup_stale_sessions
from docrenamer.types import FileAnalysis, ScannedFile, Status


class Mode(StrEnum):
    """Режимы работы (раздел 8 ТЗ)."""

    ANALYZE = "analyze"
    PREVIEW = "preview"
    APPLY = "apply"
    FORENSIC = "forensic"
    UNDO = "undo"


class Cancelled(RuntimeError):
    """Работа прервана пользователем (раздел 81 ТЗ)."""


@dataclass(slots=True)
class ApplyReport:
    """Итог исполнения плана."""

    total: int = 0
    renamed: int = 0
    skipped: int = 0
    failed: int = 0
    low_confidence: int = 0
    critical: str = ""
    cancelled: bool = False
    manifest_path: Path | None = None
    log_path: Path | None = None
    results: list[dict[str, Any]] = field(default_factory=list)

    def counters(self) -> dict[str, int]:
        return {
            "Всего в плане": self.total,
            "Переименовано": self.renamed,
            "Пропущено": self.skipped,
            "Низкая уверенность": self.low_confidence,
            "Ошибок": self.failed,
        }


class Application:
    """Единая точка входа бизнес-логики."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        paths: AppPaths | None = None,
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        analyzer: Analyzer | None = None,
    ) -> None:
        self.paths = paths or default_paths()
        self.config = config or load_config(paths=self.paths)
        self.on_line = on_line
        self.on_progress = on_progress
        self.session_id = new_session_id()
        self.cancel_event = threading.Event()
        self.paths.ensure_service_dirs()
        self.temp = SessionTemp(self.paths, self.session_id)
        self._analyzer = analyzer
        self.last_scan_stats: ScanStats | None = None

    # --- служебное ---------------------------------------------------------

    @property
    def analyzer(self) -> Analyzer:
        """Ленивая сборка конвейера анализа."""
        if self._analyzer is None:
            self._analyzer = build_analyzer(self.config, self.paths, temp=self.temp)
        return self._analyzer

    def log_line(self, message: str) -> None:
        if self.on_line:
            self.on_line(message)

    def progress(self, done: int, total: int, stage: str = "") -> None:
        if self.on_progress:
            self.on_progress(done, total, stage)

    def cancel(self) -> None:
        """Остановить запуск новых задач (раздел 81 ТЗ)."""
        self.cancel_event.set()

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled("Операция остановлена пользователем.")

    def cleanup(self) -> None:
        """Удалить временные данные сессии."""
        self.temp.cleanup()

    def startup_maintenance(self) -> int:
        """Очистить брошенные сессии при старте (раздел 62 ТЗ)."""
        return cleanup_stale_sessions(self.paths, keep=self.session_id)

    # --- этапы -------------------------------------------------------------

    def scan(self, directory: Path, *, recursive: bool | None = None) -> list[ScannedFile]:
        """Просканировать каталог."""
        scanner = Scanner(
            recursive=self.config.recursive if recursive is None else recursive,
            paths=self.paths,
        )
        files = list(scanner.scan(Path(directory)))
        self.last_scan_stats = scanner.stats
        self.log_line(f"Найдено файлов: {len(files)}")
        self.log_line(scanner.stats.summary_ru())
        return files

    def analyze(self, files: Iterable[ScannedFile]) -> list[FileAnalysis]:
        """Проанализировать файлы (раздел 13 ТЗ)."""
        items = list(files)
        results: list[FileAnalysis] = []
        total = len(items)
        for index, scanned in enumerate(items, start=1):
            self._check_cancel()
            self.progress(index, total, "ANALYZE")
            analysis = self.analyzer.analyze(scanned)
            results.append(analysis)
            if analysis.proposed_filename:
                label = (
                    str(analysis.document_type.value)
                    if analysis.document_type
                    else analysis.detected_type
                )
                self.log_line(f"→ {label} | confidence {analysis.overall_confidence:.2f}")

        # Часть уточнений видна только по каталогу целиком: например, тома
        # одного документа.
        postprocess = getattr(self.analyzer, "postprocess", None)
        if callable(postprocess):
            postprocess(results)
        return results

    def preview(
        self,
        directory: Path,
        *,
        recursive: bool | None = None,
        save_plan_to: Path | None = None,
    ) -> RenamePlan:
        """Построить план без изменений на диске (раздел 8 ТЗ)."""
        files = self.scan(directory, recursive=recursive)
        analyses = self.analyze(files)
        plan = build_plan(
            analyses,
            config=self.config,
            root=Path(directory),
            app_version=__version__,
            progress=lambda done, total: self.progress(done, total, "PLAN"),
        )
        if save_plan_to:
            plan.save(Path(save_plan_to))
        for key, value in plan.counters().items():
            self.log_line(f"{key}: {value}")
        return plan

    def apply(self, plan: RenamePlan, *, write_log: bool = True) -> ApplyReport:
        """Исполнить утверждённый план (разделы 48, 51 ТЗ)."""
        report = ApplyReport()
        items = [item for item in plan.items if item.selected and item.is_rename]
        report.total = len(items)
        report.low_confidence = sum(
            1 for i in plan.items if i.status == Status.SKIPPED_LOW_CONFIDENCE.value
        )

        log: TextLog | None = None
        writer: ManifestWriter | None = None
        if write_log:
            log = TextLog(
                new_log_path(self.paths.logs_dir),
                encoding=self.config.human_log_encoding,
                on_line=self.on_line,
                language=self.config.language,
            )
            report.log_path = log.path
            writer = ManifestWriter(
                new_manifest_path(self.paths.manifests_dir),
                session_id=self.session_id,
                app_version=__version__,
                config_fingerprint=self.config.fingerprint(),
                strict_local_mode=self.config.strict_local_mode,
                mode=Mode.APPLY.value,
                model_info=self.analyzer.model_info(),
                root_directory=str(plan.root),
            )
            report.manifest_path = writer.path
            log.line(f"Каталог: {plan.root}")
            log.line(f"К переименованию: {len(items)}")

        try:
            for index, item in enumerate(items, start=1):
                if self.cancel_event.is_set():
                    report.cancelled = True
                    if log:
                        log.line("Остановлено пользователем. Выполненные операции не откатываются.")
                    break
                self.progress(index, len(items), "APPLY")

                ok, status, message = verify_plan_item(item)
                if not ok:
                    report.skipped += 1
                    report.results.append(
                        {"source": str(item.source_path), "status": status, "message": message}
                    )
                    if log:
                        log.file_record(
                            index,
                            len(items),
                            old_path=item.source_path,
                            proposed_path=item.target_path,
                            document_type=item.analysis.detected_type if item.analysis else "",
                            document_date="",
                            confidence=item.confidence,
                            result=status,
                            message=message,
                        )
                    continue

                try:
                    outcome = rename_file(
                        item.source_path,
                        item.target_path,
                        expected_size=item.size,
                        expected_mtime=item.mtime,
                        expected_sha256=item.sha256,
                        detected_type=item.analysis.detected_type if item.analysis else "",
                        confidence=item.confidence,
                    )
                except CriticalSafetyError as exc:
                    report.critical = str(exc)
                    report.failed += 1
                    if log:
                        log.line(f"КРИТИЧЕСКАЯ ОШИБКА: {exc}")
                        log.line("Пакетная обработка остановлена.")
                    break

                report.results.append(
                    {
                        "source": str(item.source_path),
                        "target": str(outcome.target_path),
                        "status": outcome.status,
                        "message": outcome.message,
                    }
                )
                if outcome.ok and outcome.record is not None:
                    report.renamed += 1
                    if writer:
                        writer.append(outcome.record)
                elif outcome.status in (
                    Status.NAME_UNCHANGED.value,
                    Status.NAME_COLLISION_RESOLVED.value,
                    Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
                ):
                    report.skipped += 1
                else:
                    report.failed += 1

                if log:
                    log.file_record(
                        index,
                        len(items),
                        old_path=item.source_path,
                        proposed_path=item.target_path,
                        document_type=item.analysis.detected_type if item.analysis else "",
                        document_date=(
                            str(item.analysis.document_date.value)
                            if item.analysis and item.analysis.document_date
                            else ""
                        ),
                        confidence=item.confidence,
                        sha_before=outcome.record.sha256_before if outcome.record else item.sha256,
                        sha_after=outcome.record.sha256_after if outcome.record else "",
                        result=outcome.status,
                        message=outcome.message,
                    )
        finally:
            if writer:
                writer.complete(report.counters())
            if log:
                log.summary(report.counters())
                log.close()
        return report

    def forensic(self, directory: Path, *, output_dir: Path | None = None) -> dict[str, Path]:
        """Режим FORENSIC: только отчёты, без изменений (раздел 8 ТЗ)."""
        target_dir = Path(output_dir) if output_dir else self.paths.manifests_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        files = self.scan(directory)
        analyses = self.analyze(files)
        plan = build_plan(
            analyses, config=self.config, root=Path(directory), app_version=__version__
        )

        analysis_path = target_dir / "analysis_report.json"
        plan_path = target_dir / "rename_plan.json"
        write_json_atomic(
            analysis_path,
            {
                "app_version": __version__,
                "session_id": self.session_id,
                "root": str(directory),
                "strict_local_mode": self.config.strict_local_mode,
                "config_fingerprint": self.config.fingerprint(),
                "model": self.analyzer.model_info(),
                "files": [a.to_dict() for a in analyses],
            },
        )
        plan.save(plan_path)

        log = TextLog(
            new_log_path(self.paths.logs_dir, prefix="forensic_log"),
            encoding=self.config.human_log_encoding,
            on_line=self.on_line,
            language=self.config.language,
        )
        try:
            log.line(f"FORENSIC. Каталог: {directory}")
            log.line("Переименование не выполняется.")
            for index, item in enumerate(plan.items, start=1):
                log.file_record(
                    index,
                    len(plan.items),
                    old_path=item.source_path,
                    proposed_path=item.target_path,
                    document_type=item.analysis.detected_type if item.analysis else "",
                    document_date="",
                    confidence=item.confidence,
                    sha_before=item.sha256,
                    result=item.status,
                    message=item.message,
                )
            log.summary(plan.counters())
        finally:
            log.close()

        return {"analysis_report": analysis_path, "rename_plan": plan_path, "log": log.path}

    def undo(self, manifest_path: Path) -> UndoReport:
        """Откатить сессию по manifest (раздел 52 ТЗ)."""
        return undo_session(
            Path(manifest_path),
            paths=self.paths,
            app_version=__version__,
            config_fingerprint=self.config.fingerprint(),
            log_encoding=self.config.human_log_encoding,
            on_line=self.on_line,
        )
