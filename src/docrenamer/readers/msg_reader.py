"""Outlook MSG (раздел 31 ТЗ). Ничего не пересохраняется."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext


def read_msg(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать письмо Outlook."""
    result = ReadResult()
    limits = context.limits
    try:
        import extract_msg
    except ImportError:  # pragma: no cover
        result.add_status(Status.UNSUPPORTED_FORMAT)
        return result

    message = None
    try:
        message = extract_msg.Message(str(path))
        metadata = _headers(message)
        attachments = []
        for attachment in getattr(message, "attachments", [])[:30]:
            name = getattr(attachment, "longFilename", None) or getattr(
                attachment, "shortFilename", None
            )
            if name:
                attachments.append(nfc(str(name)))
        metadata["attachments"] = attachments
        metadata["attachment_count"] = len(attachments)
        body = nfc(str(getattr(message, "body", "") or ""))
    except Exception as exc:  # недоверенный вход
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"MSG не разобран: {exc}")
        return result
    finally:
        if message is not None:
            try:
                message.close()
            except Exception as exc:  # закрытие не должно ломать анализ
                result.decoding_warnings.append(f"MSG закрыт с ошибкой: {exc}")

    result.metadata.update(safe_metadata(metadata))
    result.source_encoding = "msg/ole2"
    result.encoding_confidence = 0.9

    header_text = "\n".join(
        f"{label}: {metadata.get(key, '')}"
        for label, key in (("Тема", "subject"), ("От", "from"), ("Кому", "to"), ("Дата", "date"))
        if metadata.get(key)
    )
    return finalize_text(result, "\n".join(part for part in (header_text, body) if part), limits)


def _headers(message: Any) -> dict[str, Any]:
    """Заголовки письма Outlook."""
    values: dict[str, Any] = {}
    for attribute, key in (
        ("subject", "subject"),
        ("sender", "from"),
        ("to", "to"),
        ("cc", "cc"),
        ("messageId", "message_id"),
    ):
        value = getattr(message, attribute, None)
        if value:
            values[key] = nfc(str(value))
    date = getattr(message, "date", None)
    if date is not None:
        values["date_raw"] = str(date)
        try:
            values["date"] = date.date().isoformat()
            values["datetime"] = date.isoformat()
        except AttributeError:
            pass
    return values
