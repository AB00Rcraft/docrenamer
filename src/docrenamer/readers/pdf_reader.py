"""PDF (разделы 15, 15.1 ТЗ).

PDF открывается только на чтение. JavaScript из документа не исполняется.
Наличие непустого текстового слоя не считается доказательством того, что
русский текст извлечён корректно: качество слоя оценивается отдельно, и при
низком качестве выполняется локальный OCR отрендеренной страницы.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.textquality import assess
from docrenamer.types import ReadResult, Status, nfc

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

#: Сколько страниц читать из начала и конца документа.
HEAD_PAGES = 6
TAIL_PAGES = 3

#: Ниже этого порога текстовый слой считается непригодным (раздел 15.1 ТЗ).
LOW_QUALITY_THRESHOLD = 0.55

#: Минимум символов на страницу, ниже которого слой считается пустым.
MIN_CHARS_PER_PAGE = 24


def _select_pages(total: int, head: int = HEAD_PAGES, tail: int = TAIL_PAGES) -> list[int]:
    """Выбрать страницы для извлечения: начало и резолютивная часть."""
    if total <= head + tail:
        return list(range(total))
    return list(range(head)) + list(range(total - tail, total))


def read_pdf(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать PDF: метаданные, текстовый слой, при необходимости — OCR."""
    result = ReadResult()
    limits = context.limits

    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover — зависимость обязательна в сборке
        result.add_status(Status.UNSUPPORTED_FORMAT)
        return result

    try:
        reader = PdfReader(str(path), strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"PDF не открыт: {exc}")
        return result

    if getattr(reader, "is_encrypted", False):
        # Попытка пустого пароля — стандартный случай «шифрование без пароля».
        try:
            opened = bool(reader.decrypt(""))
        except (NotImplementedError, PdfReadError, ValueError):
            opened = False
        if not opened:
            result.add_status(Status.PASSWORD_PROTECTED)
            result.metadata["pdf_encrypted"] = True
            return result
        result.metadata["pdf_encrypted"] = True

    try:
        pages = list(reader.pages)
    except (PdfReadError, ValueError, OSError) as exc:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"Структура PDF повреждена: {exc}")
        return result

    result.page_count = len(pages)
    result.metadata.update(_pdf_metadata(reader, len(pages)))

    chunks: list[str] = []
    page_reports: list[dict[str, Any]] = []
    for index in _select_pages(len(pages)):
        try:
            text = pages[index].extract_text() or ""
        except (PdfReadError, KeyError, ValueError, TypeError, AttributeError) as exc:
            result.decoding_warnings.append(f"Страница {index + 1} не извлечена: {exc}")
            continue
        text = nfc(text)
        report = assess(text)
        page_reports.append({"page": index + 1, "chars": len(text), "quality": report.score})
        if text.strip():
            chunks.append(text)

    layer_text = "\n".join(chunks)
    layer_quality = assess(layer_text).score if layer_text.strip() else 0.0
    chars_per_page = len(layer_text) / max(1, len(page_reports))
    result.metadata["pdf_pages_sampled"] = page_reports

    needs_ocr = (
        not layer_text.strip()
        or chars_per_page < MIN_CHARS_PER_PAGE
        or layer_quality < LOW_QUALITY_THRESHOLD
    )
    if layer_text.strip() and layer_quality < LOW_QUALITY_THRESHOLD:
        result.add_status(Status.PDF_TEXT_LAYER_LOW_QUALITY)

    if needs_ocr:
        ocr_text, ocr_quality, ocr_status = _try_ocr(path, context, len(pages))
        if ocr_status:
            result.add_status(ocr_status)
        if ocr_text.strip() and ocr_quality > layer_quality + 0.1:
            result.add_status(Status.PDF_OCR_FALLBACK_USED)
            result.metadata["pdf_text_source"] = "ocr"
            result.metadata["pdf_layer_quality"] = round(layer_quality, 4)
            result.source_encoding = "ocr"
            result.encoding_confidence = ocr_quality
            return finalize_text(result, ocr_text, limits)

    if not layer_text.strip():
        # Изображение-PDF без доступного OCR: пустым документом не считаем,
        # но и текста для анализа нет (раздел 15 ТЗ).
        result.metadata["pdf_text_source"] = "none"
        result.add_status(Status.EMPTY_DOCUMENT)
        return finalize_text(result, "", limits)

    result.metadata["pdf_text_source"] = "text-layer"
    result.source_encoding = "pdf/text-layer"
    result.encoding_confidence = layer_quality
    return finalize_text(result, layer_text, limits)


def _pdf_metadata(reader: Any, page_count: int) -> dict[str, Any]:
    """Свойства документа PDF."""
    values: dict[str, Any] = {"page_count": page_count}
    try:
        info = reader.metadata or {}
    except (AttributeError, ValueError, TypeError):
        return safe_metadata(values)
    mapping = {
        "/Title": "title",
        "/Author": "author",
        "/Subject": "subject",
        "/Creator": "creator",
        "/Producer": "producer",
        "/CreationDate": "created_raw",
        "/ModDate": "modified_raw",
    }
    for key, name in mapping.items():
        try:
            value = info.get(key)
        except (AttributeError, TypeError):
            value = None
        if value:
            values[name] = nfc(str(value))
    return safe_metadata(values)


def _try_ocr(path: Path, context: ReaderContext, page_count: int) -> tuple[str, float, str]:
    """Выполнить OCR страниц PDF, если движок доступен (раздел 16 ТЗ)."""
    engine = context.extras.get("ocr")
    if engine is None or not context.config.ocr.enabled:
        return "", 0.0, ""
    try:
        text, status = engine.ocr_pdf(path, page_count)
    except Exception as exc:  # недоверенный вход и внешний процесс
        return "", 0.0, f"{Status.OCR_FAILED.value}: {exc}"[:200]
    if not text:
        return "", 0.0, status
    return text, assess(text).score, status
