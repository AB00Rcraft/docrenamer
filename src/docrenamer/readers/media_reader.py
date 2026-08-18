"""Видео и аудио (разделы 28, 29 ТЗ).

Медиафайлы не перекодируются: читаются только метаданные контейнера и теги.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.metadata.ffprobe import duration_label, media_datetime
from docrenamer.readers.base import finalize_text, safe_metadata
from docrenamer.types import ReadResult

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext


def read_media(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать метаданные видео или аудио."""
    result = ReadResult()
    limits = context.limits
    metadata: dict[str, Any] = {}

    tags = _mutagen_tags(path, result)
    if tags:
        metadata.update(tags)

    probe = context.extras.get("ffprobe")
    if probe is not None and context.config.media.use_ffprobe:
        probe_result = probe.read(path)
        if probe_result.error:
            result.decoding_warnings.append(probe_result.error)
        values = probe_result.values or {}
        if values:
            metadata["ffprobe"] = values
            stamp = media_datetime(values)
            if stamp:
                metadata.setdefault("datetime", stamp)
                metadata.setdefault("datetime_source", "creation_time")
            duration = values.get("duration_seconds")
            if duration:
                metadata.setdefault("duration_seconds", duration)
            for key in ("width", "height", "video_codec", "audio_codec", "frame_rate"):
                if values.get(key) is not None:
                    metadata.setdefault(key, values[key])
            device = " ".join(
                str(values.get(part, "")).strip() for part in ("make", "model")
            ).strip()
            if device:
                metadata.setdefault("device", device)
            if values.get("gps"):
                latitude, longitude = values["gps"][0], values["gps"][1]
                metadata.setdefault("gps", [latitude, longitude])
                metadata.setdefault("gps_short", f"GPS-{latitude:.4f}_{longitude:.4f}")

    exif_backend = context.extras.get("exiftool")
    if exif_backend is not None and context.config.media.use_exif and "datetime" not in metadata:
        from docrenamer.metadata.exiftool import device_label, exif_datetime

        exif_result = exif_backend.read(path)
        values = exif_result.values or {}
        if values:
            metadata.setdefault("exif", values)
            stamp, source_field = exif_datetime(values)
            if stamp:
                metadata.setdefault("datetime", stamp)
                metadata.setdefault("datetime_source", source_field)
            device = device_label(values)
            if device:
                metadata.setdefault("device", device)

    duration = float(metadata.get("duration_seconds") or 0.0)
    if duration:
        metadata["duration_label"] = duration_label(duration)

    result.metadata.update(safe_metadata(metadata))
    result.source_encoding = "media/metadata"
    result.encoding_confidence = 0.9

    text_parts = [
        str(metadata.get(key, ""))
        for key in ("title", "artist", "album", "comment")
        if metadata.get(key)
    ]
    return finalize_text(result, "\n".join(text_parts), limits, check_mixed_alphabet=False)


def _mutagen_tags(path: Path, result: ReadResult) -> dict[str, Any]:
    """Теги аудиофайла через ``mutagen`` (раздел 29 ТЗ)."""
    values: dict[str, Any] = {}
    try:
        import mutagen
    except ImportError:  # pragma: no cover
        return values
    try:
        media = mutagen.File(str(path), easy=True)
    except Exception as exc:  # недоверенный вход
        result.decoding_warnings.append(f"Теги не прочитаны: {exc}")
        return values
    if media is None:
        return values

    tags = getattr(media, "tags", None) or {}
    for key, name in (
        ("title", "title"),
        ("artist", "artist"),
        ("album", "album"),
        ("date", "tag_date"),
        ("genre", "genre"),
    ):
        try:
            value = tags.get(key)
        except (AttributeError, TypeError):
            continue
        if isinstance(value, list) and value:
            value = value[0]
        if value:
            values[name] = str(value)

    info = getattr(media, "info", None)
    if info is not None:
        length = getattr(info, "length", 0.0)
        if length:
            values["duration_seconds"] = float(length)
        bitrate = getattr(info, "bitrate", 0)
        if bitrate:
            values["bitrate"] = int(bitrate)
        channels = getattr(info, "channels", 0)
        if channels:
            values["channels"] = int(channels)
    return values
