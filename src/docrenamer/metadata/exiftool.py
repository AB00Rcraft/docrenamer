"""Метаданные через локальный ExifTool (раздел 26 ТЗ).

Только операции чтения: запись EXIF/XMP запрещена (раздел 2 ТЗ).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docrenamer.paths import AppPaths
from docrenamer.security.subprocess_safe import run_tool

#: Поля, которые интересуют именование (раздел 26 ТЗ).
WANTED_TAGS = (
    "DateTimeOriginal",
    "CreateDate",
    "ModifyDate",
    "Make",
    "Model",
    "GPSLatitude",
    "GPSLongitude",
    "GPSAltitude",
    "ImageWidth",
    "ImageHeight",
    "Orientation",
    "Software",
    "FileType",
    "MIMEType",
    "Duration",
    "Title",
    "Artist",
    "Album",
    "Author",
    "Creator",
    "Subject",
    "LensModel",
    "ContentIdentifier",
)

_EXIF_DATE_RE = re.compile(r"^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})")


@dataclass(slots=True)
class ExifResult:
    """Результат опроса ExifTool."""

    available: bool = False
    values: dict[str, Any] = None  # type: ignore[assignment]
    error: str = ""

    def __post_init__(self) -> None:
        if self.values is None:
            self.values = {}


class ExifToolBackend:
    """Обёртка над локальным ``exiftool``."""

    def __init__(self, paths: AppPaths, *, timeout: int = 60, allow_system: bool = True) -> None:
        self.paths = paths
        self.timeout = timeout
        self.executable = paths.exiftool(allow_system)

    @property
    def available(self) -> bool:
        return self.executable is not None

    def read(self, path: Path) -> ExifResult:
        """Прочитать метаданные файла.

        Вызов соответствует рекомендации ТЗ: ``exiftool -json -G -n <file>``.
        """
        if self.executable is None:
            return ExifResult(available=False, error="ExifTool не найден.")
        result = run_tool(
            self.executable,
            ["-json", "-G", "-n", "-charset", "filename=utf8", str(path)],
            timeout=self.timeout,
        )
        if not result.ok and not result.stdout:
            return ExifResult(available=True, error=result.error or result.stderr[:200])
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            return ExifResult(available=True, error=f"ExifTool вернул некорректный JSON: {exc}")
        if not payload:
            return ExifResult(available=True, values={})
        return ExifResult(available=True, values=normalize(payload[0]))


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Привести ответ ExifTool к плоскому словарю нужных полей.

    Ключи приходят в виде ``EXIF:DateTimeOriginal`` — группа отбрасывается,
    приоритет у первой встреченной непустой величины.
    """
    values: dict[str, Any] = {}
    for key, value in raw.items():
        if value in (None, "", "-"):
            continue
        name = key.split(":")[-1]
        if name not in WANTED_TAGS:
            continue
        values.setdefault(name, value)
    return values


def exif_datetime(values: dict[str, Any]) -> tuple[str, str]:
    """Вернуть ``(ISO-дата-время, имя_поля)`` по приоритету раздела 41 ТЗ."""
    for field in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
        raw = values.get(field)
        if not raw:
            continue
        match = _EXIF_DATE_RE.match(str(raw))
        if not match:
            continue
        year, month, day, hour, minute, second = match.groups()
        if year == "0000":
            continue
        return f"{year}-{month}-{day}T{hour}:{minute}:{second}", field
    return "", ""


#: Длина модели, начиная с которой она считается самодостаточной.
MODEL_SELF_SUFFICIENT_LENGTH = 5


def device_label(values: dict[str, Any]) -> str:
    """Компактное название устройства съёмки для имени файла.

    Пример раздела 27 ТЗ — ``iPhone-16-Pro``, а не ``Apple-iPhone-16-Pro``:
    модель почти всегда узнаваема сама по себе, а полные значения Make и Model
    сохраняются в manifest.
    """
    make = str(values.get("Make") or "").strip()
    model = str(values.get("Model") or "").strip()
    if not model:
        return make
    if not make or model.lower().startswith(make.lower()):
        return model
    has_letters = any(ch.isalpha() for ch in model)
    if has_letters and len(model) >= MODEL_SELF_SUFFICIENT_LENGTH:
        return model
    return f"{make} {model}"


def gps_pair(values: dict[str, Any]) -> tuple[float, float] | None:
    """Координаты в десятичном виде, если они есть."""
    lat = values.get("GPSLatitude")
    lon = values.get("GPSLongitude")
    try:
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None
