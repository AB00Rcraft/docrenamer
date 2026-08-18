"""Метаданные видео и аудио через локальный ffprobe (раздел 28 ТЗ).

Медиафайлы не перекодируются: выполняется только опрос контейнера.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docrenamer.paths import AppPaths
from docrenamer.security.subprocess_safe import run_tool

_ISO_TIME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})")
_GPS_RE = re.compile(r"([+-]\d+\.\d+)([+-]\d+\.\d+)")


@dataclass(slots=True)
class ProbeResult:
    """Результат опроса ffprobe."""

    available: bool = False
    values: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class FFprobeBackend:
    """Обёртка над локальным ``ffprobe``."""

    def __init__(self, paths: AppPaths, *, timeout: int = 60, allow_system: bool = True) -> None:
        self.paths = paths
        self.timeout = timeout
        self.executable = paths.ffprobe(allow_system)

    @property
    def available(self) -> bool:
        return self.executable is not None

    def read(self, path: Path) -> ProbeResult:
        """Получить сведения о контейнере и потоках."""
        if self.executable is None:
            return ProbeResult(available=False, error="ffprobe не найден.")
        result = run_tool(
            self.executable,
            [
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout=self.timeout,
        )
        if not result.stdout:
            return ProbeResult(available=True, error=result.error or result.stderr[:200])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return ProbeResult(available=True, error=f"ffprobe вернул некорректный JSON: {exc}")
        return ProbeResult(available=True, values=summarize(payload))


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    """Свести ответ ffprobe к нужным полям."""
    values: dict[str, Any] = {}
    container = payload.get("format", {}) or {}
    tags = {str(k).lower(): v for k, v in (container.get("tags") or {}).items()}

    duration = container.get("duration")
    try:
        if duration is not None:
            values["duration_seconds"] = float(duration)
    except (TypeError, ValueError):
        pass
    for key, name in (
        ("format_name", "container"),
        ("bit_rate", "bit_rate"),
        ("size", "size"),
    ):
        if container.get(key):
            values[name] = container[key]

    for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
        if tags.get(key):
            values["creation_time"] = str(tags[key])
            break
    for key, name in (
        ("title", "title"),
        ("artist", "artist"),
        ("album", "album"),
        ("comment", "comment"),
        ("com.apple.quicktime.model", "model"),
        ("com.apple.quicktime.make", "make"),
        ("model", "model"),
        ("make", "make"),
        ("encoder", "encoder"),
    ):
        if tags.get(key) and name not in values:
            values[name] = str(tags[key])

    location = tags.get("location") or tags.get("com.apple.quicktime.location.iso6709")
    if location:
        match = _GPS_RE.match(str(location))
        if match:
            try:
                values["gps"] = [float(match.group(1)), float(match.group(2))]
            except ValueError:
                pass

    streams = payload.get("streams", []) or []
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and "video_codec" not in values:
            values["video_codec"] = stream.get("codec_name", "")
            values["width"] = stream.get("width")
            values["height"] = stream.get("height")
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""
            values["frame_rate"] = _parse_rate(str(rate))
        elif kind == "audio" and "audio_codec" not in values:
            values["audio_codec"] = stream.get("codec_name", "")
            values["sample_rate"] = stream.get("sample_rate")
            values["channels"] = stream.get("channels")
    values["has_video"] = any(s.get("codec_type") == "video" for s in streams)
    values["has_audio"] = any(s.get("codec_type") == "audio" for s in streams)
    return {k: v for k, v in values.items() if v not in (None, "", [])}


def _parse_rate(rate: str) -> float:
    """Преобразовать ``30000/1001`` в число кадров в секунду."""
    if "/" in rate:
        numerator, _, denominator = rate.partition("/")
        try:
            den = float(denominator)
            return round(float(numerator) / den, 3) if den else 0.0
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(rate)
    except (TypeError, ValueError):
        return 0.0


def media_datetime(values: dict[str, Any]) -> str:
    """ISO-дата-время съёмки/записи из метаданных контейнера."""
    raw = values.get("creation_time")
    if not raw:
        return ""
    match = _ISO_TIME_RE.match(str(raw))
    if not match:
        return ""
    year, month, day, hour, minute, second = match.groups()
    if year == "0000":
        return ""
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}"


def duration_label(seconds: float) -> str:
    """Компактная длительность для имени файла: ``01m42s`` или ``1h05m``."""
    if not seconds or seconds <= 0:
        return ""
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes:02d}m{secs:02d}s"
