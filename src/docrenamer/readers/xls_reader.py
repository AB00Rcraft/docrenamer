"""XLS — устаревший формат Excel (раздел 19 ТЗ). Только чтение через ``xlrd``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

MAX_CELLS = 1500
MAX_ROWS_PER_SHEET = 200
MAX_COLS_PER_SHEET = 30


def read_xls(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать книгу Excel 97-2003."""
    result = ReadResult()
    limits = context.limits
    try:
        import xlrd
    except ImportError:  # pragma: no cover
        result.add_status(Status.UNSUPPORTED_FORMAT)
        return result

    try:
        book = xlrd.open_workbook(str(path), on_demand=True)
    except Exception as exc:  # недоверенный вход
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"Книга XLS не открыта: {exc}")
        return result

    parts: list[str] = []
    cells = 0
    sheet_names: list[str] = []
    try:
        for sheet in book.sheets():
            sheet_names.append(sheet.name)
            parts.append(f"[Лист] {sheet.name}")
            for row_index in range(min(sheet.nrows, MAX_ROWS_PER_SHEET)):
                row_values: list[str] = []
                for col_index in range(min(sheet.ncols, MAX_COLS_PER_SHEET)):
                    value = sheet.cell_value(row_index, col_index)
                    if value in ("", None):
                        continue
                    cells += 1
                    row_values.append(nfc(str(value)).strip()[:200])
                    if cells >= MAX_CELLS:
                        break
                if row_values:
                    parts.append(" | ".join(row_values))
                if cells >= MAX_CELLS:
                    result.add_status(Status.LIMIT_EXCEEDED)
                    break
            if cells >= MAX_CELLS:
                break
    finally:
        try:
            book.release_resources()
        except Exception as exc:  # закрытие не должно ломать анализ
            result.decoding_warnings.append(f"Книга закрыта с ошибкой: {exc}")

    result.metadata.update(
        safe_metadata(
            {
                "sheet_names": sheet_names,
                "sheet_count": len(sheet_names),
                "cells_read": cells,
            }
        )
    )
    result.source_encoding = "xls/binary"
    result.encoding_confidence = 0.9
    result.add_status(Status.PARTIAL_SUPPORT)
    return finalize_text(result, "\n".join(parts), limits)
