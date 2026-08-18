"""Откат переименований по manifest (раздел 52 ТЗ).

Undo — такая же транзакция, как и rename: с проверками, контрольными суммами,
собственным журналом и собственным manifest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docrenamer.logging.manifest import ManifestWriter, load_manifest, new_manifest_path
from docrenamer.logging.text_log import TextLog, new_log_path
from docrenamer.operations.hashing import HashError, sha256_file
from docrenamer.operations.rename import CriticalSafetyError, RenameOutcome, rename_file
from docrenamer.paths import AppPaths, default_paths, new_session_id
from docrenamer.types import RenameRecord, Status, utcstamp


@dataclass(slots=True)
class UndoReport:
    """Итог сессии отката."""

    manifest_path: Path
    log_path: Path | None = None
    undo_manifest_path: Path | None = None
    total: int = 0
    restored: int = 0
    skipped: int = 0
    failed: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    critical: str = ""

    def counters(self) -> dict[str, int]:
        return {
            "Всего записей": self.total,
            "Восстановлено": self.restored,
            "Пропущено": self.skipped,
            "Ошибок": self.failed,
        }


def _validate(record: dict[str, Any]) -> tuple[bool, str, str]:
    """Проверки раздела 52 ТЗ до попытки отката.

    Returns:
        ``(можно_откатывать, код, сообщение)``.
    """
    current = Path(record.get("target_path", ""))
    original = Path(record.get("source_path", ""))

    if not str(current) or not str(original):
        return False, Status.SKIPPED.value, "Неполная запись manifest."
    if record.get("status") != Status.RENAMED.value:
        return False, Status.SKIPPED.value, "Запись не является выполненным переименованием."
    if not current.exists():
        return False, Status.SKIPPED.value, f"Файл не найден: {current}"
    if current.is_dir():
        return False, Status.UNSAFE_PATH.value, f"Это каталог: {current}"
    if current.parent != original.parent:
        return False, Status.UNSAFE_PATH.value, "Откат между каталогами запрещён."
    if original.exists():
        return (
            False,
            Status.UNDO_TARGET_EXISTS.value,
            f"Исходное имя занято: {original.name}",
        )
    if current.suffix.lower() != Path(record.get("new_filename", current.name)).suffix.lower():
        return False, Status.EXTENSION_MISMATCH.value, "Расширение файла не соответствует manifest."

    expected = str(record.get("sha256_after") or record.get("sha256_before") or "")
    if not expected:
        return False, Status.HASH_ERROR.value, "В manifest нет контрольной суммы."
    try:
        actual = sha256_file(current)
    except HashError as exc:
        return False, Status.HASH_ERROR.value, str(exc)
    if actual != expected:
        return (
            False,
            Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
            "Содержимое файла изменилось после переименования — откат небезопасен.",
        )
    return True, Status.OK.value, ""


def undo_record(record: dict[str, Any]) -> RenameOutcome:
    """Откатить одну запись manifest."""
    allowed, status, message = _validate(record)
    current = Path(record.get("target_path", ""))
    original = Path(record.get("source_path", ""))
    if not allowed:
        return RenameOutcome(ok=False, status=status, message=message, target_path=original)

    expected = str(record.get("sha256_after") or record.get("sha256_before") or "")
    return rename_file(
        current,
        original,
        expected_sha256=expected,
        detected_type=str(record.get("detected_type", "")),
        confidence=float(record.get("confidence", 0.0) or 0.0),
    )


def undo_session(
    manifest_path: Path,
    *,
    paths: AppPaths | None = None,
    app_version: str = "",
    config_fingerprint: str = "",
    log_encoding: str = "utf-8",
    on_line: Callable[[str], None] | None = None,
    write_log: bool = True,
) -> UndoReport:
    """Откатить все переименования сессии в обратном порядке."""
    app_paths = paths or default_paths()
    manifest_path = Path(manifest_path)
    data = load_manifest(manifest_path)
    records = [r for r in data.get("records", []) if isinstance(r, dict)]
    report = UndoReport(manifest_path=manifest_path, total=len(records))

    log: TextLog | None = None
    writer: ManifestWriter | None = None
    if write_log:
        app_paths.ensure_service_dirs()
        log = TextLog(
            new_log_path(app_paths.logs_dir, prefix="undo_log"),
            encoding=log_encoding,
            on_line=on_line,
        )
        report.log_path = log.path
        writer = ManifestWriter(
            new_manifest_path(app_paths.manifests_dir, prefix="undo_manifest"),
            session_id=new_session_id(),
            app_version=app_version,
            config_fingerprint=config_fingerprint,
            mode="undo",
            root_directory=str(data.get("root_directory", "")),
            encoding=log_encoding if log_encoding == "utf-8" else "utf-8",
        )
        report.undo_manifest_path = writer.path
        log.line(f"Откат по manifest: {manifest_path}")
        log.line(f"Записей к откату: {len(records)}")

    try:
        # Обратный порядок: последние переименования откатываются первыми.
        for index, record in enumerate(reversed(records), start=1):
            try:
                outcome = undo_record(record)
            except CriticalSafetyError as exc:
                report.critical = str(exc)
                report.failed += 1
                if log:
                    log.line(f"КРИТИЧЕСКАЯ ОШИБКА: {exc}")
                break

            original = Path(record.get("source_path", ""))
            current = Path(record.get("target_path", ""))
            entry = {
                "source_path": str(current),
                "target_path": str(original),
                "status": outcome.status,
                "message": outcome.message,
            }
            report.outcomes.append(entry)

            if outcome.ok:
                report.restored += 1
            elif outcome.status in (
                Status.UNDO_TARGET_EXISTS.value,
                Status.SKIPPED.value,
                Status.NAME_UNCHANGED.value,
            ):
                report.skipped += 1
            else:
                report.failed += 1

            if log:
                log.file_record(
                    index,
                    len(records),
                    old_path=current,
                    proposed_path=original,
                    document_type=str(record.get("detected_type", "")),
                    document_date="",
                    confidence=float(record.get("confidence", 0.0) or 0.0),
                    sha_before=outcome.record.sha256_before if outcome.record else "",
                    sha_after=outcome.record.sha256_after if outcome.record else "",
                    result="RESTORED" if outcome.ok else outcome.status,
                    message=outcome.message,
                )
            if writer:
                if outcome.record is not None:
                    writer.append(outcome.record)
                else:
                    writer.append(
                        RenameRecord(
                            source_path=current,
                            target_path=original,
                            original_filename=current.name,
                            new_filename=original.name,
                            sha256_before="",
                            sha256_after="",
                            size=int(record.get("size", 0) or 0),
                            mtime=float(record.get("mtime", 0.0) or 0.0),
                            detected_type=str(record.get("detected_type", "")),
                            confidence=0.0,
                            status=outcome.status,
                            timestamp=utcstamp(),
                            message=outcome.message,
                        )
                    )
    finally:
        if writer:
            writer.complete(report.counters())
        if log:
            log.summary(report.counters())
            log.close()

    return report
