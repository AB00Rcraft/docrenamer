"""JSON (раздел 25 ТЗ).

Анализируется структура и релевантные фрагменты, а не весь документ целиком.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.encoding import decode_bytes
from docrenamer.readers.base import apply_decode_result, finalize_text, guard_size, safe_metadata
from docrenamer.types import ReadResult, Status

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

#: Ключи, значения которых чаще всего описывают документ.
INTERESTING_KEYS = (
    "title",
    "name",
    "subject",
    "date",
    "number",
    "id",
    "author",
    "organization",
    "наименование",
    "название",
    "дата",
    "номер",
    "тема",
    "автор",
    "организация",
)


def _walk(value: Any, depth: int, max_depth: int, out: list[str], keys: list[str]) -> None:
    """Обойти структуру, собирая ключи и короткие строковые значения."""
    if depth > max_depth or len(out) > 2000:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(str(key))
            if isinstance(item, str) and item.strip():
                if str(key).lower() in INTERESTING_KEYS or len(item) <= 200:
                    out.append(f"{key}: {item.strip()[:200]}")
            else:
                _walk(item, depth + 1, max_depth, out, keys)
    elif isinstance(value, list):
        for item in value[:200]:
            _walk(item, depth + 1, max_depth, out, keys)
    elif isinstance(value, str) and value.strip():
        out.append(value.strip()[:200])


def read_json(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать JSON с ограничением размера и глубины."""
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_json_bytes):
        return result

    with open(path, "rb") as handle:
        data = handle.read(limits.max_json_bytes)

    decoded = decode_bytes(data)
    apply_decode_result(result, decoded)

    try:
        payload = json.loads(decoded.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"JSON не разобран: {exc}")
        return finalize_text(result, decoded.text[:20_000], limits)

    fragments: list[str] = []
    keys: list[str] = []
    _walk(payload, 0, limits.max_json_depth, fragments, keys)

    result.metadata.update(
        safe_metadata(
            {
                "json_root_type": type(payload).__name__,
                "json_keys": sorted(set(keys))[:50],
                "json_items": len(payload) if isinstance(payload, dict | list) else 1,
            }
        )
    )
    return finalize_text(result, "\n".join(fragments), limits)
