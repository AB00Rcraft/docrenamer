"""Человекочитаемый журнал запуска (разделы 50, 14A.6 ТЗ).

Файл пишется в UTF-8 (или utf-8-sig, если так задано в config) и начинается с
явного указания кодировки и языкового профиля, чтобы русский текст гарантированно
открывался сторонними программами Windows.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType

from docrenamer.types import RenameRecord, nfc


def timestamp_for_filename(moment: datetime | None = None) -> str:
    """Метка вида ``2026-08-18_142203`` для имён журналов и manifest."""
    return (moment or datetime.now()).strftime("%Y-%m-%d_%H%M%S")


class TextLog:
    """Потоковый текстовый журнал.

    Каждая строка дублируется в ``on_line`` — так GUI получает живой лог, не
    перечитывая файл.
    """

    def __init__(
        self,
        path: Path,
        *,
        encoding: str = "utf-8",
        on_line: Callable[[str], None] | None = None,
        language: str = "ru-RU",
    ) -> None:
        self.path = Path(path)
        self.encoding = encoding
        self.on_line = on_line
        self.language = language
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "w", encoding=encoding, newline="\n")
        self._write_header()

    def _write_header(self) -> None:
        declared = "UTF-8 with BOM" if self.encoding == "utf-8-sig" else "UTF-8"
        self._raw(f"Encoding: {declared}")
        self._raw(f"Language profile: {self.language}")
        self._raw(f"Started: {datetime.now().astimezone().isoformat(timespec='seconds')}")
        self._raw("=" * 70)

    def _raw(self, text: str) -> None:
        self._handle.write(nfc(text) + "\n")
        self._handle.flush()

    def line(self, message: str, *, echo: bool = True) -> None:
        """Строка журнала с временной меткой."""
        stamped = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self._raw(stamped)
        if echo and self.on_line:
            self.on_line(stamped)

    def block(self, text: str) -> None:
        """Многострочный блок без временной метки."""
        self._raw(text)

    def file_record(
        self,
        index: int,
        total: int,
        *,
        old_path: Path,
        proposed_path: Path,
        document_type: str,
        document_date: str,
        confidence: float,
        sha_before: str = "",
        sha_after: str = "",
        result: str,
        message: str = "",
    ) -> None:
        """Блок по одному файлу в формате раздела 50 ТЗ."""
        self.line(f"FILE {index}/{total}", echo=False)
        parts = [
            "",
            "OLD:",
            str(old_path),
            "",
            "PROPOSED:",
            str(proposed_path),
            "",
            "TYPE:",
            document_type or "—",
            "",
            "DATE:",
            document_date or "—",
            "",
            "CONFIDENCE:",
            f"{confidence:.2f}",
        ]
        if sha_before:
            parts += ["", "SHA256 BEFORE:", sha_before]
        if sha_after:
            parts += ["", "SHA256 AFTER:", sha_after]
        parts += ["", "RESULT:", result]
        if message:
            parts += ["", "NOTE:", message]
        parts += ["", "-" * 70]
        self.block("\n".join(parts))

    def record(self, index: int, total: int, record: RenameRecord) -> None:
        """Записать блок по готовой транзакции."""
        self.file_record(
            index,
            total,
            old_path=record.source_path,
            proposed_path=record.target_path,
            document_type=record.detected_type,
            document_date="",
            confidence=record.confidence,
            sha_before=record.sha256_before,
            sha_after=record.sha256_after,
            result=record.status,
            message=record.message,
        )

    def summary(self, counters: dict[str, int]) -> None:
        """Итоговая сводка запуска."""
        self.block("=" * 70)
        self.line("ИТОГИ", echo=False)
        for key, value in counters.items():
            self.line(f"  {key}: {value}")

    def close(self) -> None:
        if not self._handle.closed:
            self._raw("=" * 70)
            self._raw(f"Finished: {datetime.now().astimezone().isoformat(timespec='seconds')}")
            self._handle.close()

    def __enter__(self) -> TextLog:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def new_log_path(logs_dir: Path, prefix: str = "rename_log") -> Path:
    """Путь нового журнала: ``logs/rename_log_YYYY-MM-DD_HHMMSS.txt``."""
    return Path(logs_dir) / f"{prefix}_{timestamp_for_filename()}.txt"
