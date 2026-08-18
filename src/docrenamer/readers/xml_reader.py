"""XML, KML, KMZ и GPX (раздел 24 ТЗ).

Разбор выполняется ``defusedxml``: внешние сущности и сетевые ссылки запрещены.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrenamer.encoding import decode_bytes
from docrenamer.readers.base import apply_decode_result, finalize_text, guard_size, safe_metadata
from docrenamer.readers.html_reader import declared_encoding
from docrenamer.types import ReadResult, Status

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext


def _parse(data: bytes) -> Any:
    """Безопасный разбор XML."""
    from defusedxml import ElementTree as SafeElementTree

    return SafeElementTree.fromstring(data)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _iter_text(element: Any, limit: int = 4000) -> list[str]:
    """Собрать текстовые узлы документа."""
    parts: list[str] = []
    for node in element.iter():
        if node.text and node.text.strip():
            parts.append(node.text.strip())
            if len(parts) >= limit:
                break
    return parts


def read_xml(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать произвольный XML-документ."""
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_xml_bytes):
        return result

    with open(path, "rb") as handle:
        data = handle.read(limits.max_xml_bytes)

    decoded = decode_bytes(data, declared=declared_encoding(data))
    apply_decode_result(result, decoded)

    try:
        root = _parse(data)
    except Exception as exc:  # недоверенный вход: любая ошибка разбора допустима
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"XML не разобран: {exc}")
        return finalize_text(result, decoded.text, limits)

    root_tag = _localname(root.tag)
    result.metadata.update(safe_metadata({"xml_root": root_tag}))

    if root_tag == "gpx":
        result.metadata.update(_gpx_metadata(root))
    elif root_tag == "kml":
        result.metadata.update(_kml_metadata(root))

    return finalize_text(result, "\n".join(_iter_text(root)), limits)


def _gpx_metadata(root: Any) -> dict[str, Any]:
    """Извлечь сведения о треке (раздел 24 ТЗ)."""
    times: list[str] = []
    points: list[tuple[float, float]] = []
    name = ""
    for node in root.iter():
        tag = _localname(node.tag)
        if tag in ("trkpt", "wpt", "rtept"):
            try:
                points.append((float(node.get("lat")), float(node.get("lon"))))
            except (TypeError, ValueError):
                continue
        elif tag == "time" and node.text:
            times.append(node.text.strip())
        elif tag == "name" and node.text and not name:
            name = node.text.strip()

    metadata: dict[str, Any] = {
        "gpx_points": len(points),
        "gpx_name": name,
    }
    if times:
        metadata["gpx_start_time"] = min(times)
        metadata["gpx_end_time"] = max(times)
    if points:
        metadata["gpx_start_point"] = [round(points[0][0], 6), round(points[0][1], 6)]
        metadata["gpx_end_point"] = [round(points[-1][0], 6), round(points[-1][1], 6)]
        metadata["gpx_length_km"] = round(_track_length_km(points), 3)
    return safe_metadata(metadata)


def _track_length_km(points: list[tuple[float, float]]) -> float:
    """Приблизительная длина трека по формуле гаверсинуса."""
    import math
    from itertools import pairwise

    total = 0.0
    radius = 6371.0
    for (lat1, lon1), (lat2, lon2) in pairwise(points):
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        total += 2 * radius * math.asin(min(1.0, math.sqrt(a)))
    return total


def _kml_metadata(root: Any) -> dict[str, Any]:
    """Извлечь имя, метки и координаты KML."""
    names: list[str] = []
    placemarks = 0
    coordinates: list[str] = []
    timestamps: list[str] = []
    for node in root.iter():
        tag = _localname(node.tag)
        if tag == "placemark":
            placemarks += 1
        elif tag == "name" and node.text:
            names.append(node.text.strip())
        elif tag == "coordinates" and node.text:
            coordinates.append(node.text.strip().split()[0])
        elif tag in ("when", "begin", "end") and node.text:
            timestamps.append(node.text.strip())
    return safe_metadata(
        {
            "kml_name": names[0] if names else "",
            "kml_placemarks": placemarks,
            "kml_first_coordinate": coordinates[0] if coordinates else "",
            "kml_timestamps": timestamps[:5],
        }
    )


def read_kmz(path: Path, context: ReaderContext) -> ReadResult:
    """Прочитать KMZ — ZIP-контейнер с KML внутри.

    Архив не распаковывается на диск: нужный элемент читается в память.
    """
    result = ReadResult()
    limits = context.limits
    if not guard_size(path, limits, result, limits.max_xml_bytes):
        return result
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [n for n in archive.namelist() if n.lower().endswith(".kml")]
            if not candidates:
                result.add_status(Status.EMPTY_DOCUMENT)
                return result
            info = archive.getinfo(candidates[0])
            if info.file_size > limits.max_xml_bytes:
                result.add_status(Status.LIMIT_EXCEEDED)
                return result
            data = archive.read(candidates[0])
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"KMZ не прочитан: {exc}")
        return result

    decoded = decode_bytes(data, declared=declared_encoding(data))
    apply_decode_result(result, decoded)
    try:
        root = _parse(data)
    except Exception as exc:  # недоверенный вход: любая ошибка разбора допустима
        result.add_status(Status.READ_ERROR)
        result.decoding_warnings.append(f"KML внутри KMZ не разобран: {exc}")
        return finalize_text(result, decoded.text, limits)

    result.metadata.update(safe_metadata({"xml_root": "kml", "kmz_entry": candidates[0]}))
    result.metadata.update(_kml_metadata(root))
    return finalize_text(result, "\n".join(_iter_text(root)), limits)
