"""Электронная почта EML (раздел 30 ТЗ).

Используется стандартный модуль ``email``. Вложения не анализируются и не
распаковываются: берутся только их имена.
"""

from __future__ import annotations

import email
import email.policy
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.readers.base import finalize_text, guard_size, safe_metadata
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext


def decode_mime_header(value: str | None) -> str:
    """Декодировать MIME-заголовок, включая русские кодировки."""
    if not value:
        return ""
    try:
        return nfc(str(make_header(decode_header(value))))
    except (UnicodeDecodeError, LookupError, ValueError, TypeError):
        return nfc(str(value))


def read_eml(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать письмо в формате RFC 822."""
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_plaintext_bytes):
        return result

    try:
        with open(path, "rb") as handle:
            message = email.message_from_binary_file(handle, policy=email.policy.default)
    except Exception as exc:  # недоверенный вход
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"Письмо не разобрано: {exc}")
        return result

    metadata = _headers(message)
    body, attachments, charsets = _body_and_attachments(message, limits.max_text_chars_total)
    metadata["attachments"] = attachments[:30]
    metadata["attachment_count"] = len(attachments)
    result.metadata.update(safe_metadata(metadata))
    result.source_encoding = charsets[0] if charsets else "mime"
    result.encoding_confidence = 0.9 if charsets else 0.6

    header_text = "\n".join(
        f"{label}: {metadata.get(key, '')}"
        for label, key in (
            ("Тема", "subject"),
            ("От", "from"),
            ("Кому", "to"),
            ("Дата", "date"),
        )
        if metadata.get(key)
    )
    return finalize_text(result, "\n".join(part for part in (header_text, body) if part), limits)


def _headers(message: Any) -> dict[str, Any]:
    """Основные заголовки письма."""
    values: dict[str, Any] = {}
    for header, key in (
        ("Subject", "subject"),
        ("From", "from"),
        ("To", "to"),
        ("Cc", "cc"),
        ("Message-ID", "message_id"),
    ):
        raw = message.get(header)
        if raw:
            values[key] = decode_mime_header(str(raw))
    raw_date = message.get("Date")
    if raw_date:
        values["date_raw"] = str(raw_date)
        try:
            parsed = parsedate_to_datetime(str(raw_date))
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            values["date"] = parsed.date().isoformat()
            values["datetime"] = parsed.isoformat()
    return values


def _body_and_attachments(message: Any, limit: int) -> tuple[str, list[str], list[str]]:
    """Основной текст письма и имена вложений."""
    parts: list[str] = []
    attachments: list[str] = []
    charsets: list[str] = []
    html_parts: list[str] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename:
            attachments.append(decode_mime_header(filename))
            continue
        content_type = part.get_content_type()
        charset = part.get_content_charset()
        if charset:
            charsets.append(charset)
        try:
            payload = part.get_content()
        except (LookupError, UnicodeDecodeError, ValueError, KeyError):
            raw = part.get_payload(decode=True) or b""
            from docrenamer.encoding import decode_bytes

            payload = decode_bytes(raw, declared=charset or "").text
        if not isinstance(payload, str):
            continue
        if content_type == "text/plain":
            parts.append(payload)
        elif content_type == "text/html":
            html_parts.append(payload)
        if sum(len(p) for p in parts) > limit:
            break

    if not parts and html_parts:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_parts[0], "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            parts.append(soup.get_text("\n", strip=True))
        except ImportError:  # pragma: no cover
            parts.append(html_parts[0])

    return "\n".join(parts)[:limit], attachments, charsets
