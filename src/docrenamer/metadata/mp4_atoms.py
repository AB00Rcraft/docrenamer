"""Чтение метаданных MP4/MOV без внешних программ (раздел 28 ТЗ).

Основной backend для видео — локальный ffprobe. Этот модуль читает контейнер
ISO BMFF напрямую и нужен, когда ffprobe не поставлен рядом с программой: без
него у видео не было бы даты съёмки.

Разбирается только структура боксов, ни один поток не декодируется. Файл
открывается на чтение, размеры боксов проверяются — повреждённый или специально
сформированный файл не должен приводить к зацикливанию или чтению всей памяти.
"""

from __future__ import annotations

import re
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

#: Эпоха ISO BMFF: 1 января 1904 года UTC.
BMFF_EPOCH = datetime(1904, 1, 1, tzinfo=UTC)

#: Ограничения обхода: недоверенный вход (раздел 54 ТЗ).
MAX_DEPTH = 6
MAX_BOXES = 4000
MIN_BOX_SIZE = 8

#: Контейнеры, внутрь которых нужно спускаться.
CONTAINER_TYPES = frozenset({b"moov", b"trak", b"mdia", b"udta", b"meta", b"minf", b"stbl"})

_GPS_RE = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


class _Counter:
    """Счётчик прочитанных боксов — защита от «бомб» из миллионов записей."""

    def __init__(self) -> None:
        self.value = 0

    def hit(self) -> bool:
        self.value += 1
        return self.value <= MAX_BOXES


def _read_boxes(
    handle: BinaryIO, end: int, depth: int, counter: _Counter
) -> list[tuple[bytes, int, int]]:
    """Прочитать список боксов ``(тип, начало_данных, конец_данных)``."""
    boxes: list[tuple[bytes, int, int]] = []
    position = handle.tell()
    while position < end and depth <= MAX_DEPTH and counter.hit():
        handle.seek(position)
        header = handle.read(8)
        if len(header) < 8:
            break
        size = struct.unpack(">I", header[:4])[0]
        box_type = header[4:8]
        data_start = position + 8
        if size == 1:
            extended = handle.read(8)
            if len(extended) < 8:
                break
            size = struct.unpack(">Q", extended)[0]
            data_start = position + 16
        elif size == 0:
            size = end - position
        if size < MIN_BOX_SIZE or position + size > end:
            break
        boxes.append((box_type, data_start, position + size))
        position += size
    return boxes


def _parse_mvhd(handle: BinaryIO, start: int, end: int) -> dict[str, Any]:
    """Заголовок фильма: время создания и длительность."""
    handle.seek(start)
    data = handle.read(min(end - start, 120))
    if len(data) < 4:
        return {}
    version = data[0]
    values: dict[str, Any] = {}
    try:
        if version == 1 and len(data) >= 32:
            created, _modified, timescale, duration = struct.unpack(">QQIQ", data[4:32])
        elif len(data) >= 20:
            created, _modified, timescale, duration = struct.unpack(">IIII", data[4:20])
        else:
            return {}
    except struct.error:
        return {}

    if created > 0:
        try:
            moment = BMFF_EPOCH + timedelta(seconds=created)
            if 1970 <= moment.year <= 2100:
                values["creation_time"] = moment.strftime("%Y-%m-%dT%H:%M:%S")
        except (OverflowError, ValueError):
            pass
    if timescale > 0 and duration > 0:
        seconds = duration / timescale
        if 0 < seconds < 86400 * 30:
            values["duration_seconds"] = round(seconds, 3)
    return values


def _parse_hdlr(handle: BinaryIO, start: int, end: int) -> str:
    """Тип дорожки: ``vide``, ``soun`` и т. п."""
    handle.seek(start)
    data = handle.read(min(end - start, 24))
    if len(data) < 12:
        return ""
    return data[8:12].decode("ascii", errors="replace")


def _parse_location(handle: BinaryIO, start: int, end: int) -> list[float] | None:
    """Координаты из бокса ``©xyz`` в формате ISO 6709."""
    handle.seek(start)
    data = handle.read(min(end - start, 128))
    text = data.decode("utf-8", errors="replace")
    match = _GPS_RE.search(text)
    if not match:
        return None
    try:
        return [round(float(match.group(1)), 6), round(float(match.group(2)), 6)]
    except ValueError:
        return None


def _walk(
    handle: BinaryIO, start: int, end: int, depth: int, counter: _Counter, values: dict[str, Any]
) -> None:
    """Рекурсивный обход боксов с накоплением интересующих значений."""
    handle.seek(start)
    for box_type, data_start, data_end in _read_boxes(handle, end, depth, counter):
        if box_type == b"mvhd":
            values.update(_parse_mvhd(handle, data_start, data_end))
        elif box_type == b"hdlr":
            kind = _parse_hdlr(handle, data_start, data_end)
            if kind == "vide":
                values["has_video"] = True
            elif kind == "soun":
                values["has_audio"] = True
        elif box_type in (b"\xa9xyz", b"loci"):
            location = _parse_location(handle, data_start, data_end)
            if location:
                values["gps"] = location
        elif box_type == b"ftyp":
            handle.seek(data_start)
            brand = handle.read(4).decode("ascii", errors="replace").strip()
            if brand:
                values["major_brand"] = brand
        elif box_type in CONTAINER_TYPES:
            _walk(handle, data_start, data_end, depth + 1, counter, values)


def probe_mp4(path: Path) -> dict[str, Any]:
    """Прочитать метаданные контейнера MP4/MOV.

    Возвращает словарь в том же виде, что и
    :func:`docrenamer.metadata.ffprobe.summarize`, поэтому вызывающий код
    не различает источники.
    """
    path = Path(path)
    values: dict[str, Any] = {}
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            _walk(handle, 0, size, 0, _Counter(), values)
    except (OSError, struct.error, ValueError):
        return {}
    values.setdefault("has_video", False)
    values.setdefault("has_audio", False)
    return values


class Mp4Backend:
    """Запасной backend метаданных видео.

    Интерфейс совпадает с :class:`docrenamer.metadata.ffprobe.FFprobeBackend`.
    """

    #: Всегда доступен: разбор выполняется средствами стандартной библиотеки.
    available = True

    #: Расширения, которые умеет читать этот backend.
    SUPPORTED = frozenset({".mp4", ".m4v", ".mov", ".m4a", ".m4b", ".3gp", ".3g2", ".heic"})

    def read(self, path: Path) -> Any:
        from docrenamer.metadata.ffprobe import ProbeResult

        path = Path(path)
        if path.suffix.lower() not in self.SUPPORTED:
            return ProbeResult(available=True, values={})
        return ProbeResult(available=True, values=probe_mp4(path))
