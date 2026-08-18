"""Выбор страниц для распознавания (раздел 16 ТЗ).

OCR — самая дорогая операция конвейера, поэтому распознаются только начало
документа (реквизиты, заголовок, номер, дата) и его конец (резолютивная часть,
подписи).
"""

from __future__ import annotations

from docrenamer.config import OCRConfig


def select_pages(page_count: int, config: OCRConfig) -> list[int]:
    """Вернуть 0-индексированные номера страниц для OCR."""
    if page_count <= 0:
        return []
    first = max(0, config.first_pages)
    last = max(0, config.last_pages)
    limit = max(1, config.pdf_max_pages)

    if page_count <= first + last:
        selected = list(range(page_count))
    else:
        selected = list(range(first)) + list(range(page_count - last, page_count))

    seen: list[int] = []
    for page in selected:
        if page not in seen:
            seen.append(page)
        if len(seen) >= limit:
            break
    return seen
