"""HTML (раздел 23 ТЗ).

JavaScript не исполняется, внешние ресурсы не загружаются, по ссылкам переходов
нет. Кодировка определяется с учётом BOM, meta charset и общего русского
pipeline'а.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from docrenamer.encoding import decode_bytes, detect_bom
from docrenamer.readers.base import apply_decode_result, finalize_text, guard_size, safe_metadata
from docrenamer.types import ReadResult

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE
)
_XML_DECL_RE = re.compile(rb"""<\?xml[^>]+encoding\s*=\s*["']([a-zA-Z0-9_\-]+)""", re.IGNORECASE)

#: Теги, содержимое которых не является видимым текстом.
INVISIBLE_TAGS = ("script", "style", "noscript", "template", "head")


def declared_encoding(data: bytes) -> str:
    """Кодировка, объявленная самим документом."""
    bom, _ = detect_bom(data)
    if bom:
        return bom
    head = data[:8192]
    for pattern in (_META_CHARSET_RE, _XML_DECL_RE):
        match = pattern.search(head)
        if match:
            return match.group(1).decode("ascii", errors="replace").lower()
    return ""


def read_html(path: Path, context: ReaderContext) -> ReadResult:
    """Извлечь заголовок, видимый текст, заголовки разделов и meta-теги."""
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_plaintext_bytes):
        return result

    with open(path, "rb") as handle:
        data = handle.read(limits.max_plaintext_bytes)

    decoded = decode_bytes(data, declared=declared_encoding(data))
    apply_decode_result(result, decoded)

    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover — зависимость обязательна в сборке
        return finalize_text(result, decoded.text, limits)

    soup = BeautifulSoup(decoded.text, "html.parser")
    # Заголовок и meta читаются до удаления <head>.
    title = soup.title.get_text(strip=True) if soup.title else ""
    metas: dict[str, str] = {}
    for meta in soup.find_all("meta", limit=50):
        name = meta.get("name") or meta.get("property") or ""
        content = meta.get("content") or ""
        if name and content:
            metas[str(name).lower()] = str(content)

    for tag in soup(list(INVISIBLE_TAGS)):
        tag.decompose()

    headings = [
        h.get_text(" ", strip=True)
        for h in soup.find_all(["h1", "h2", "h3"], limit=20)
        if h.get_text(strip=True)
    ]
    result.metadata.update(
        safe_metadata(
            {
                "title": title,
                "headings": headings,
                "html_meta": metas,
                "declared_encoding": declared_encoding(data),
                "original_encoding": decoded.encoding,
            }
        )
    )
    text = soup.get_text("\n", strip=True)
    return finalize_text(result, "\n".join(part for part in (title, text) if part), limits)
