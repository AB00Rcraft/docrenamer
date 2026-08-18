"""JSON-manifest сессии (разделы 51, 52, 83, 84 ТЗ).

Manifest — единственный источник истины для undo и для восстановления после
сбоя. Он пишется инкрементально: рядом ведётся append-only журнал ``.jsonl``,
который переживает аварийное завершение процесса.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import TracebackType
from typing import Any

from docrenamer.config import write_json_atomic
from docrenamer.logging.text_log import timestamp_for_filename
from docrenamer.types import RenameRecord, utcstamp

MANIFEST_FORMAT_VERSION = 1

#: Минимальный интервал между атомарными перезаписями JSON, секунды.
#: Журнал ``.jsonl`` пишется всегда, поэтому данные не теряются.
REWRITE_DEBOUNCE_SECONDS = 0.5


class ManifestWriter:
    """Инкрементальная запись manifest сессии."""

    def __init__(
        self,
        path: Path,
        *,
        session_id: str,
        app_version: str,
        config_fingerprint: str,
        strict_local_mode: bool = True,
        mode: str = "apply",
        model_info: dict[str, Any] | None = None,
        root_directory: str = "",
        encoding: str = "utf-8",
    ) -> None:
        self.path = Path(path)
        self.journal_path = self.path.with_suffix(".jsonl")
        self.encoding = encoding
        self.records: list[dict[str, Any]] = []
        self.header: dict[str, Any] = {
            "manifest_format_version": MANIFEST_FORMAT_VERSION,
            "session_id": session_id,
            "app_version": app_version,
            "config_fingerprint": config_fingerprint,
            "strict_local_mode": strict_local_mode,
            "mode": mode,
            "root_directory": root_directory,
            "model": model_info or {},
            "started_at": utcstamp(),
            "finished_at": "",
            "completed": False,
            "counters": {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._journal = open(self.journal_path, "a", encoding="utf-8", newline="\n")
        self._write_journal({"type": "header", **self.header})
        self._last_rewrite = 0.0
        self._flush(force=True)

    # --- запись -----------------------------------------------------------

    def _write_journal(self, payload: dict[str, Any]) -> None:
        """Append-only запись с fsync: переживает аварию процесса."""
        self._journal.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self._journal.flush()
        os.fsync(self._journal.fileno())

    def _document(self) -> dict[str, Any]:
        return {**self.header, "records": self.records}

    def _flush(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_rewrite) < REWRITE_DEBOUNCE_SECONDS:
            return
        write_json_atomic(self.path, self._document(), encoding=self.encoding)
        self._last_rewrite = now

    def append(self, record: RenameRecord | dict[str, Any]) -> None:
        """Зафиксировать транзакцию сразу после её завершения (раздел 83 ТЗ)."""
        payload = record.to_dict() if isinstance(record, RenameRecord) else dict(record)
        self.records.append(payload)
        self._write_journal({"type": "record", **payload})
        self._flush()

    def set_counters(self, counters: dict[str, int]) -> None:
        self.header["counters"] = dict(counters)

    def complete(self, counters: dict[str, int] | None = None) -> Path:
        """Закрыть manifest: пометить сессию завершённой."""
        if counters is not None:
            self.set_counters(counters)
        self.header["finished_at"] = utcstamp()
        self.header["completed"] = True
        self._write_journal({"type": "footer", **self.header})
        self._flush(force=True)
        self.close()
        return self.path

    def close(self) -> None:
        if not self._journal.closed:
            self._journal.close()

    def __enter__(self) -> ManifestWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self._flush(force=True)
        self.close()


def new_manifest_path(manifests_dir: Path, prefix: str = "rename_manifest") -> Path:
    """Путь нового manifest: ``manifests/rename_manifest_YYYY-MM-DD_HHMMSS.json``."""
    return Path(manifests_dir) / f"{prefix}_{timestamp_for_filename()}.json"


def load_manifest(path: Path) -> dict[str, Any]:
    """Прочитать manifest.

    Если JSON повреждён или обрезан аварией, данные восстанавливаются из
    append-only журнала ``.jsonl``.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and "records" in data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return recover_from_journal(path.with_suffix(".jsonl"))


def recover_from_journal(journal_path: Path) -> dict[str, Any]:
    """Собрать документ manifest из журнала (раздел 83 ТЗ)."""
    journal_path = Path(journal_path)
    if not journal_path.is_file():
        raise FileNotFoundError(f"Manifest не найден и журнал отсутствует: {journal_path}")
    header: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    with open(journal_path, encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue  # Обрезанная последняя строка после аварии.
            kind = payload.pop("type", "")
            if kind in ("header", "footer"):
                header.update(payload)
            elif kind == "record":
                records.append(payload)
    header.setdefault("completed", False)
    return {**header, "records": records}


def find_incomplete_sessions(manifests_dir: Path) -> list[Path]:
    """Найти manifest незавершённых сессий (раздел 83 ТЗ)."""
    directory = Path(manifests_dir)
    if not directory.is_dir():
        return []
    result: list[Path] = []
    for candidate in sorted(directory.glob("*.json")):
        try:
            data = load_manifest(candidate)
        except (OSError, FileNotFoundError, json.JSONDecodeError):
            continue
        if not data.get("completed") and data.get("records"):
            result.append(candidate)
    return result
