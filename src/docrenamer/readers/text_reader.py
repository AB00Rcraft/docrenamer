"""TXT / CSV / LOG / MD и RTF (разделы 22, 11 ТЗ).

Кодировка определяется общим русским pipeline'ом. Молчаливая потеря символов
запрещена: сомнительный результат помечается ``ENCODING_UNCERTAIN``.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import TYPE_CHECKING

from docrenamer.encoding import read_text_file
from docrenamer.readers.base import apply_decode_result, finalize_text, guard_size, safe_metadata
from docrenamer.types import ReadResult

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

#: Управляющие последовательности RTF, которые нужно снять при извлечении текста.
_RTF_CONTROL_RE = re.compile(r"\\\*?\\?[a-zA-Z]{1,32}(-?\d{1,10})?[ ]?")
_RTF_UNICODE_RE = re.compile(r"\\u(-?\d+)\s?\??")
_RTF_HEX_RE = re.compile(r"\\'([0-9a-fA-F]{2})")


def read_text(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать простой текстовый файл."""
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_plaintext_bytes):
        return result

    decoded = read_text_file(path)
    apply_decode_result(result, decoded)
    return finalize_text(result, decoded.text, limits)


def read_csv(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать CSV.

    Кодировка и разделитель определяются раздельно: русский Excel и старые
    учётные системы часто дают legacy-encoded текст с «;» (раздел 22 ТЗ).
    """
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_plaintext_bytes):
        return result

    decoded = read_text_file(path, limit=min(limits.max_plaintext_bytes, 8 * 1024 * 1024))
    apply_decode_result(result, decoded)

    sample = decoded.text[:8192]
    delimiter = ";"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in ",;\t|"}
        delimiter = max(counts, key=lambda d: counts[d]) if any(counts.values()) else ","

    headers: list[str] = []
    rows = 0
    try:
        reader = csv.reader(io.StringIO(decoded.text), delimiter=delimiter)
        for index, row in enumerate(reader):
            if index == 0:
                headers = [cell.strip() for cell in row][:32]
            rows += 1
            if rows > 5000:
                break
    except csv.Error as exc:
        result.decoding_warnings.append(f"CSV разобран частично: {exc}")

    result.metadata.update(
        safe_metadata({"csv_delimiter": delimiter, "csv_rows": rows, "csv_headers": headers})
    )
    return finalize_text(result, decoded.text, limits)


def _rtf_to_text(raw: str) -> str:
    """Извлечь читаемый текст из RTF без исполнения чего-либо."""
    text = raw
    text = re.sub(r"\{\\\*[^{}]*\}", " ", text)
    def _unicode_escape(match: re.Match[str]) -> str:
        code = int(match.group(1))
        return chr(code if code >= 0 else 65536 + code)

    text = _RTF_UNICODE_RE.sub(_unicode_escape, text)
    text = _RTF_HEX_RE.sub(lambda m: bytes([int(m.group(1), 16)]).decode("cp1251", "replace"), text)
    text = _RTF_CONTROL_RE.sub(" ", text)
    text = text.replace("{", " ").replace("}", " ").replace("\\\\", "\\")
    return re.sub(r"[ \t]{2,}", " ", text)


def read_rtf(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать RTF (частичная поддержка: только текстовый слой)."""
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_plaintext_bytes):
        return result

    with open(path, "rb") as handle:
        raw = handle.read(limits.max_plaintext_bytes)
    # RTF по стандарту семибитный; кириллица приходит через \'hh и \uN.
    source = raw.decode("ascii", errors="replace")
    result.source_encoding = "rtf/ascii+escapes"
    result.encoding_confidence = 0.8
    return finalize_text(result, _rtf_to_text(source), limits)
