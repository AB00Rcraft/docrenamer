"""Устаревшие форматы Office и другие OLE2-контейнеры (раздел 21 ТЗ).

Полнотекстовое извлечение из ``.doc``/``.ppt`` ненадёжно, поэтому ограничение
помечается честно: ``PARTIAL_SUPPORT_LEGACY_OFFICE``. Тяжёлая обязательная
конвертация через LibreOffice в MVP не используется.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.textquality import assess
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

#: Свойства SummaryInformation, интересные для именования.
SUMMARY_FIELDS = {
    "title": "title",
    "subject": "subject",
    "author": "author",
    "last_saved_by": "last_modified_by",
    "keywords": "keywords",
    "comments": "comments",
    "create_time": "created",
    "last_saved_time": "modified",
}

_WORD_TEXT_RE = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё\s.,№\-]{12,}")


def read_ole(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать OLE2-контейнер: свойства документа и, по возможности, текст."""
    result = ReadResult()
    limits = context.limits
    try:
        import olefile
    except ImportError:  # pragma: no cover
        result.add_status(Status.UNSUPPORTED_FORMAT)
        return result

    if not olefile.isOleFile(str(path)):
        result.add_status(Status.UNSUPPORTED_FORMAT)
        result.decoding_warnings.append("Файл не является контейнером OLE2.")
        return result

    ole = None
    try:
        ole = olefile.OleFileIO(str(path))
        result.metadata.update(_summary_metadata(ole))
        streams = ["/".join(entry) for entry in ole.listdir()]
        result.metadata.update(safe_metadata({"ole_streams": streams[:40]}))
        text = _extract_word_text(ole, streams, limits.max_text_chars_total)
    except Exception as exc:  # недоверенный вход
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"OLE2 не прочитан: {exc}")
        text = ""
    finally:
        if ole is not None:
            try:
                ole.close()
            except Exception as exc:  # закрытие не должно ломать анализ
                result.decoding_warnings.append(f"OLE2 закрыт с ошибкой: {exc}")

    result.add_status(Status.PARTIAL_SUPPORT_LEGACY_OFFICE)
    result.add_status(Status.PARTIAL_SUPPORT)
    result.source_encoding = "ole2"
    result.encoding_confidence = 0.7

    metadata_text = "\n".join(
        str(result.metadata.get(key, ""))
        for key in ("title", "subject", "author", "keywords", "comments")
        if result.metadata.get(key)
    )
    combined = "\n".join(part for part in (metadata_text, text) if part)
    return finalize_text(result, combined, limits)


def _summary_metadata(ole: Any) -> dict[str, Any]:
    """Свойства SummaryInformation / DocumentSummaryInformation."""
    values: dict[str, Any] = {}
    try:
        meta = ole.get_metadata()
    except Exception:  # недоверенный вход: битые свойства не должны ронять анализ
        return values
    for attribute, name in SUMMARY_FIELDS.items():
        value = getattr(meta, attribute, None)
        if isinstance(value, bytes):
            # Свойства старых документов часто в CP1251.
            for encoding in ("cp1251", "utf-8", "latin-1"):
                try:
                    decoded = value.decode(encoding)
                except UnicodeDecodeError:
                    continue
                if assess(decoded).score > 0.5:
                    value = decoded
                    break
            else:
                continue
        if value:
            values[name] = nfc(str(value))
    for attribute, name in (("num_pages", "page_count"), ("num_words", "word_count")):
        value = getattr(meta, attribute, None)
        if isinstance(value, int) and value > 0:
            values[name] = value
    return safe_metadata(values)


def _extract_word_text(ole: Any, streams: list[str], limit: int) -> str:
    """Достать читаемые фрагменты из потока WordDocument.

    Это эвристика, а не полноценный парсер бинарного формата: результат
    используется как подсказка и всегда сопровождается кодом частичной
    поддержки.
    """
    target = next((name for name in streams if name.lower() == "worddocument"), "")
    if not target:
        return ""
    try:
        with ole.openstream(target) as stream:
            raw = stream.read(min(limit * 2, 4_000_000))
    except Exception:  # недоверенный вход
        return ""

    candidates: list[str] = []
    for encoding in ("utf-16-le", "cp1251"):
        try:
            decoded = raw.decode(encoding, errors="replace")
        except (UnicodeDecodeError, LookupError):
            continue
        fragments = _WORD_TEXT_RE.findall(decoded)
        if fragments:
            candidates.append("\n".join(fragment.strip() for fragment in fragments[:200]))
    if not candidates:
        return ""
    return max(candidates, key=lambda text: assess(text).score)
