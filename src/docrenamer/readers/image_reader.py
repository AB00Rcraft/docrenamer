"""Изображения (разделы 26, 27, 65 ТЗ).

Pillow используется только для чтения, preview и подготовки к OCR. Исходник
никогда не пересохраняется, EXIF не изменяется.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.metadata.exiftool import device_label, exif_datetime, gps_pair
from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.types import ReadResult, Status

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

#: Соотношение сторон и размеры, характерные для снимков документов.
DOCUMENT_HINT_MIN_PIXELS = 700_000


def read_image(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать метаданные изображения и, при необходимости, распознать текст."""
    result = ReadResult()
    limits = context.limits
    metadata: dict[str, Any] = {}

    exif_backend = context.extras.get("exiftool")
    exif_values: dict[str, Any] = {}
    if exif_backend is not None and context.config.media.use_exif:
        exif_result = exif_backend.read(path)
        if exif_result.error:
            result.decoding_warnings.append(exif_result.error)
        exif_values = exif_result.values or {}

    if exif_values:
        metadata["exif"] = exif_values
        stamp, source_field = exif_datetime(exif_values)
        if stamp:
            metadata["datetime"] = stamp
            metadata["datetime_source"] = source_field
        device = device_label(exif_values)
        if device:
            metadata["device"] = device
        coordinates = gps_pair(exif_values)
        if coordinates:
            metadata["gps"] = [round(coordinates[0], 6), round(coordinates[1], 6)]
            metadata["gps_short"] = f"GPS-{coordinates[0]:.4f}_{coordinates[1]:.4f}"
        for key, name in (
            ("ImageWidth", "width"),
            ("ImageHeight", "height"),
            ("Software", "software"),
            ("Orientation", "orientation"),
        ):
            if exif_values.get(key):
                metadata[name] = exif_values[key]

    pillow_values = _pillow_metadata(path, result)
    for key, value in pillow_values.items():
        metadata.setdefault(key, value)

    result.metadata.update(safe_metadata(metadata))

    text, ocr_status = _maybe_ocr(path, context, metadata)
    if ocr_status:
        result.add_status(ocr_status)
    if text:
        result.source_encoding = "ocr"
        result.encoding_confidence = 0.8
        result.metadata["ocr_used"] = True
    return finalize_text(result, text, limits)


def _pillow_metadata(path: Path, result: ReadResult) -> dict[str, Any]:
    """Размеры и формат изображения через Pillow (только чтение)."""
    values: dict[str, Any] = {}
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # pragma: no cover
        return values

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:  # pragma: no cover — HEIC/AVIF без плагина недоступны
        pass

    try:
        with Image.open(path) as image:
            values["width"] = image.width
            values["height"] = image.height
            values["image_format"] = image.format or ""
            values["image_mode"] = image.mode
    except UnidentifiedImageError:
        result.add_status(Status.UNSUPPORTED_FORMAT)
        result.decoding_warnings.append("Формат изображения не распознан Pillow.")
    except (OSError, ValueError) as exc:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"Изображение не прочитано: {exc}")
    return values


def looks_like_document(metadata: dict[str, Any]) -> bool:
    """Похоже ли изображение на снимок документа.

    Эвристика намеренно осторожна: при сомнении OCR всё равно выполняется, а
    решение о типе принимается позже по фактически распознанному тексту.
    """
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    if width <= 0 or height <= 0:
        return True
    return width * height >= DOCUMENT_HINT_MIN_PIXELS


def _maybe_ocr(path: Path, context: ReaderContext, metadata: dict[str, Any]) -> tuple[str, str]:
    """Выполнить OCR изображения, если это оправдано и движок доступен."""
    engine = context.extras.get("ocr")
    if engine is None or not context.config.ocr.enabled:
        return "", ""
    if not looks_like_document(metadata):
        return "", ""
    try:
        text, status = engine.ocr_image(path)
    except Exception as exc:  # внешний процесс и недоверенный вход
        return "", f"{Status.OCR_FAILED.value}: {exc}"[:200]
    return text, status
