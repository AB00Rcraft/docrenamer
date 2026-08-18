"""Лимиты обработки недоверенного входа (раздел 54 ТЗ).

Любой пользовательский файл считается потенциально повреждённым или специально
сформированным. Лимиты не дают одному файлу исчерпать память или время.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Limits:
    """Действующие ограничения обработки."""

    max_text_chars_total: int = 400_000
    max_text_chars_for_ai: int = 24_000
    max_plaintext_bytes: int = 50 * 1024 * 1024
    max_single_file_bytes: int = 4096 * 1024 * 1024
    max_archive_entries: int = 5000
    max_archive_ratio: float = 200.0
    subprocess_timeout: int = 120
    max_xml_bytes: int = 64 * 1024 * 1024
    max_json_bytes: int = 64 * 1024 * 1024
    max_json_depth: int = 40

    @classmethod
    def from_config(cls, config: object) -> Limits:
        """Собрать лимиты из :class:`docrenamer.config.Config`."""
        limits = getattr(config, "limits", None)
        if limits is None:
            return cls()
        return cls(
            max_text_chars_total=limits.max_text_chars_total,
            max_text_chars_for_ai=limits.max_text_chars_for_ai,
            max_plaintext_bytes=limits.max_plaintext_file_mb * 1024 * 1024,
            max_single_file_bytes=limits.max_single_file_mb * 1024 * 1024,
            max_archive_entries=limits.max_archive_entries,
            subprocess_timeout=limits.subprocess_timeout_seconds,
        )


def truncate_text(text: str, limit: int) -> tuple[str, bool]:
    """Обрезать текст до ``limit`` символов.

    Возвращает ``(text, truncated)``. Обрезка выполняется по границе символа,
    поэтому кириллица не может быть разорвана посередине.
    """
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit], True


def file_too_large(path: Path, limit_bytes: int) -> bool:
    """Превышает ли файл лимит размера."""
    try:
        return path.stat().st_size > limit_bytes
    except OSError:
        return False
