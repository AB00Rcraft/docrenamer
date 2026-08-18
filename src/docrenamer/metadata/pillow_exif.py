"""Чтение EXIF средствами Pillow (раздел 26 ТЗ).

Основной backend метаданных — ExifTool. Этот модуль нужен, когда ExifTool не
поставлен рядом с программой: без него у фотографий не было бы даты съёмки, и
единственным источником оставалось бы время файла. Формат результата совпадает
с :mod:`docrenamer.metadata.exiftool`, поэтому вызывающий код не различает
источники.

Файл открывается только на чтение, EXIF не изменяется.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Теги EXIF, которые нас интересуют: номер → имя как у ExifTool.
EXIF_TAGS: dict[int, str] = {
    0x010F: "Make",
    0x0110: "Model",
    0x0131: "Software",
    0x0112: "Orientation",
    0x0132: "ModifyDate",
    0x9003: "DateTimeOriginal",
    0x9004: "CreateDate",
    0xA002: "ImageWidth",
    0xA003: "ImageHeight",
    0xA434: "LensModel",
}

#: Теги внутри GPS-IFD.
GPS_LATITUDE_REF = 1
GPS_LATITUDE = 2
GPS_LONGITUDE_REF = 3
GPS_LONGITUDE = 4
GPS_ALTITUDE = 6

#: Идентификатор GPS-IFD в основном наборе тегов.
GPS_IFD_TAG = 0x8825


def _to_float(value: Any) -> float | None:
    """Привести рациональное число EXIF к float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dms_to_degrees(value: Any, ref: Any) -> float | None:
    """Перевести координату из градусов-минут-секунд в десятичные градусы."""
    try:
        degrees, minutes, seconds = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    result = degrees + minutes / 60.0 + seconds / 3600.0
    if str(ref).upper().strip() in ("S", "W"):
        result = -result
    return round(result, 6)


def read_exif(path: Path) -> dict[str, Any]:
    """Прочитать EXIF изображения. Пустой словарь — данных нет или формат чужой."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # pragma: no cover — Pillow обязателен в сборке
        return {}

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:  # pragma: no cover — HEIC без плагина недоступен
        pass

    values: dict[str, Any] = {}
    try:
        with Image.open(path) as image:
            values["ImageWidth"] = image.width
            values["ImageHeight"] = image.height
            try:
                exif = image.getexif()
            except (OSError, ValueError, AttributeError):
                return values
            if not exif:
                return values

            for tag, name in EXIF_TAGS.items():
                raw = exif.get(tag)
                if raw in (None, ""):
                    continue
                if name in ("ImageWidth", "ImageHeight", "Orientation"):
                    number = _to_float(raw)
                    if number is not None:
                        values[name] = int(number)
                else:
                    values[name] = str(raw).strip().strip("\x00")

            values.update(_gps_values(exif))
    except UnidentifiedImageError:
        return values
    except (OSError, ValueError) as exc:  # недоверенный вход
        values.setdefault("_error", str(exc))
    return {k: v for k, v in values.items() if not str(k).startswith("_")}


def _gps_values(exif: Any) -> dict[str, Any]:
    """Координаты из GPS-IFD в десятичном виде."""
    try:
        gps = exif.get_ifd(GPS_IFD_TAG)
    except (AttributeError, KeyError, OSError, ValueError):
        return {}
    if not gps:
        return {}

    values: dict[str, Any] = {}
    latitude = _dms_to_degrees(gps.get(GPS_LATITUDE), gps.get(GPS_LATITUDE_REF, "N"))
    longitude = _dms_to_degrees(gps.get(GPS_LONGITUDE), gps.get(GPS_LONGITUDE_REF, "E"))
    if latitude is not None and longitude is not None:
        values["GPSLatitude"] = latitude
        values["GPSLongitude"] = longitude
    altitude = _to_float(gps.get(GPS_ALTITUDE))
    if altitude is not None:
        values["GPSAltitude"] = round(altitude, 2)
    return values


class PillowExifBackend:
    """Запасной backend метаданных изображений.

    Интерфейс совпадает с :class:`docrenamer.metadata.exiftool.ExifToolBackend`,
    поэтому reader работает с ними одинаково.
    """

    #: Всегда доступен: Pillow входит в дистрибутив.
    available = True

    def read(self, path: Path) -> Any:
        from docrenamer.metadata.exiftool import ExifResult

        values = read_exif(Path(path))
        return ExifResult(available=True, values=values)
