"""Общая основа reader'ов (разделы 14A.1, 54 ТЗ).

Reader обязан вернуть Unicode-текст и метаданные, никогда не открывая файл на
запись и не исполняя встроенный в него код.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.encoding import DecodeResult
from docrenamer.security.limits import Limits, truncate_text
from docrenamer.textquality import assess, mixed_alphabet_words
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext


def language_hint(text: str) -> str:
    """Грубая подсказка о языке текста: ``ru``, ``en``, ``mixed`` или пусто."""
    if not text:
        return ""
    report = assess(text)
    if report.cyrillic_ratio > report.latin_ratio * 1.5:
        return "ru"
    if report.latin_ratio > report.cyrillic_ratio * 1.5:
        return "en"
    if report.cyrillic_ratio > 0 and report.latin_ratio > 0:
        return "mixed"
    return ""


def finalize_text(
    result: ReadResult,
    text: str,
    limits: Limits,
    *,
    check_mixed_alphabet: bool = True,
) -> ReadResult:
    """Нормализовать, ограничить и оценить извлечённый текст."""
    normalized = nfc(text or "")
    trimmed, truncated = truncate_text(normalized, limits.max_text_chars_total)
    result.text = trimmed
    result.truncated = result.truncated or truncated
    if truncated:
        result.add_status(Status.LIMIT_EXCEEDED)

    report = assess(trimmed)
    result.text_quality = report.score
    result.text_language_hint = language_hint(trimmed)
    for warning in report.warnings:
        if warning not in result.decoding_warnings:
            result.decoding_warnings.append(warning)
    for code in report.statuses:
        result.add_status(code)

    if check_mixed_alphabet and trimmed:
        mixed = mixed_alphabet_words(trimmed, limit=5)
        if mixed:
            result.add_status(Status.MIXED_ALPHABET_SUSPECTED)
            result.metadata.setdefault("mixed_alphabet_words", mixed)

    if not trimmed.strip():
        result.add_status(Status.EMPTY_DOCUMENT)
    return result


def apply_decode_result(result: ReadResult, decoded: DecodeResult) -> None:
    """Перенести сведения о декодировании в результат чтения."""
    result.source_encoding = decoded.encoding
    result.encoding_confidence = decoded.confidence
    for warning in decoded.warnings:
        if warning not in result.decoding_warnings:
            result.decoding_warnings.append(warning)
    for code in decoded.statuses:
        result.add_status(code)


def guard_size(path: Path, limits: Limits, result: ReadResult, max_bytes: int) -> bool:
    """Проверить лимит размера. ``False`` — файл читать не следует."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size > max_bytes:
        result.add_status(Status.LIMIT_EXCEEDED)
        result.decoding_warnings.append(
            f"Файл {size / 1048576:.1f} МБ превышает лимит {max_bytes / 1048576:.0f} МБ."
        )
        return False
    return True


def safe_metadata(values: dict[str, Any]) -> dict[str, Any]:
    """Оставить только сериализуемые и непустые значения метаданных."""
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, str):
            cleaned[key] = nfc(value.strip())
        elif isinstance(value, int | float | bool | list | dict):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def context_limits(context: ReaderContext) -> Limits:
    """Лимиты из контекста (упрощает сигнатуры reader'ов)."""
    return context.limits
