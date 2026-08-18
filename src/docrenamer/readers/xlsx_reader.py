"""XLSX / XLSM (раздел 18 ТЗ).

Книга открывается только на чтение, макросы не исполняются, целиком в LLM не
передаётся: берётся ограниченный набор непустых ячеек.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

#: Сколько ячеек максимум берём из книги и сколько строк — из листа.
MAX_CELLS = 1500
MAX_ROWS_PER_SHEET = 200
MAX_COLS_PER_SHEET = 30


def read_xlsx(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать книгу Excel формата OOXML."""
    result = ReadResult()
    limits = context.limits
    try:
        import openpyxl
    except ImportError:  # pragma: no cover
        result.add_status(Status.UNSUPPORTED_FORMAT)
        return result

    try:
        # data_only=True: берём вычисленные значения, формулы не исполняем.
        workbook = openpyxl.load_workbook(
            str(path), read_only=True, data_only=True, keep_links=False
        )
    except Exception as exc:  # недоверенный вход
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"Книга Excel не открыта: {exc}")
        return result

    if path.suffix.lower() == ".xlsm":
        result.metadata["contains_macros"] = True
        result.decoding_warnings.append("Файл содержит макросы; они не исполняются.")

    parts: list[str] = []
    headers: dict[str, list[str]] = {}
    cells = 0
    try:
        for sheet in workbook.worksheets:
            parts.append(f"[Лист] {sheet.title}")
            first_row: list[str] = []
            for row_index, row in enumerate(
                sheet.iter_rows(max_row=MAX_ROWS_PER_SHEET, max_col=MAX_COLS_PER_SHEET)
            ):
                row_values: list[str] = []
                for cell in row:
                    value = cell.value
                    if value is None or value == "":
                        continue
                    cells += 1
                    row_values.append(nfc(str(value)).strip()[:200])
                    if cells >= MAX_CELLS:
                        break
                if row_values:
                    if row_index == 0 or not first_row:
                        first_row = row_values
                    parts.append(" | ".join(row_values))
                if cells >= MAX_CELLS:
                    result.add_status(Status.LIMIT_EXCEEDED)
                    break
            if first_row:
                headers[sheet.title] = first_row[:MAX_COLS_PER_SHEET]
            if cells >= MAX_CELLS:
                break
        result.metadata.update(_workbook_properties(workbook))
        result.metadata.update(
            safe_metadata(
                {
                    "sheet_names": [s.title for s in workbook.worksheets],
                    "sheet_count": len(workbook.worksheets),
                    "table_headers": headers,
                    "cells_read": cells,
                }
            )
        )
    finally:
        try:
            workbook.close()
        except Exception as exc:  # закрытие не должно ломать анализ
            result.decoding_warnings.append(f"Книга закрыта с ошибкой: {exc}")

    result.source_encoding = "ooxml/utf-8"
    result.encoding_confidence = 1.0
    return finalize_text(result, "\n".join(parts), limits)


def _workbook_properties(workbook: Any) -> dict[str, Any]:
    """Свойства книги."""
    values: dict[str, Any] = {}
    properties = getattr(workbook, "properties", None)
    if properties is None:
        return values
    for attribute, name in (
        ("title", "title"),
        ("creator", "author"),
        ("subject", "subject"),
        ("created", "created"),
        ("modified", "modified"),
        ("lastModifiedBy", "last_modified_by"),
    ):
        value = getattr(properties, attribute, None)
        if value:
            values[name] = nfc(str(value))
    return safe_metadata(values)
