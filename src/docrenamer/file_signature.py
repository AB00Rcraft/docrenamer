"""Определение реального типа файла (раздел 10 ТЗ).

Расширению доверять нельзя. Тип определяется по сигнатуре, при необходимости —
по внутренней структуре контейнера. Расширение при расхождении автоматически
не меняется: фиксируется код ``EXTENSION_MISMATCH``.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from docrenamer.types import Category, Status

#: Сколько байт заголовка достаточно для всех проверяемых сигнатур.
HEADER_SIZE = 4096

#: Соответствие «тип → категория».
TYPE_CATEGORY: dict[str, Category] = {
    "pdf": Category.DOCUMENT,
    "docx": Category.DOCUMENT,
    "xlsx": Category.DOCUMENT,
    "xlsm": Category.DOCUMENT,
    "pptx": Category.DOCUMENT,
    "doc": Category.DOCUMENT,
    "xls": Category.DOCUMENT,
    "ppt": Category.DOCUMENT,
    "rtf": Category.DOCUMENT,
    "txt": Category.DOCUMENT,
    "md": Category.DOCUMENT,
    "csv": Category.DATA,
    "log": Category.DOCUMENT,
    "html": Category.DOCUMENT,
    "xml": Category.DATA,
    "json": Category.DATA,
    "jpg": Category.IMAGE,
    "png": Category.IMAGE,
    "gif": Category.IMAGE,
    "bmp": Category.IMAGE,
    "tiff": Category.IMAGE,
    "webp": Category.IMAGE,
    "heic": Category.IMAGE,
    "avif": Category.IMAGE,
    "dng": Category.IMAGE,
    "raw": Category.IMAGE,
    "mp4": Category.VIDEO,
    "mov": Category.VIDEO,
    "avi": Category.VIDEO,
    "mkv": Category.VIDEO,
    "webm": Category.VIDEO,
    "mts": Category.VIDEO,
    "mp3": Category.AUDIO,
    "m4a": Category.AUDIO,
    "wav": Category.AUDIO,
    "flac": Category.AUDIO,
    "ogg": Category.AUDIO,
    "wma": Category.AUDIO,
    "aiff": Category.AUDIO,
    "amr": Category.AUDIO,
    "eml": Category.EMAIL,
    "msg": Category.EMAIL,
    "zip": Category.ARCHIVE,
    "7z": Category.ARCHIVE,
    "rar": Category.ARCHIVE,
    "tar": Category.ARCHIVE,
    "gz": Category.ARCHIVE,
    "gpx": Category.GEODATA,
    "kml": Category.GEODATA,
    "kmz": Category.GEODATA,
}

#: Расширения, которые считаются равнозначными обнаруженному типу.
EXTENSION_ALIASES: dict[str, set[str]] = {
    "jpg": {".jpg", ".jpeg", ".jpe"},
    "tiff": {".tif", ".tiff"},
    "heic": {".heic", ".heif", ".hif"},
    "mp4": {".mp4", ".m4v", ".3gp", ".3g2"},
    "mov": {".mov", ".qt"},
    "mkv": {".mkv", ".mka"},
    "webm": {".webm"},
    "m4a": {".m4a", ".m4b", ".aac"},
    "html": {".html", ".htm", ".xhtml"},
    "txt": {".txt", ".log", ".md", ".ini", ".cfg", ".srt", ".sub"},
    "xml": {".xml", ".kml", ".gpx", ".rss", ".svg", ".xsd", ".xsl"},
    "zip": {".zip", ".kmz", ".epub", ".odt", ".ods", ".odp", ".jar", ".apk"},
    "gpx": {".gpx", ".xml"},
    "kml": {".kml", ".xml"},
    "kmz": {".kmz", ".zip"},
    "gz": {".gz", ".tgz"},
    "tar": {".tar"},
    "dng": {".dng", ".tif", ".tiff"},
    "raw": {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef"},
    "ogg": {".ogg", ".oga", ".opus", ".ogv"},
    "doc": {".doc", ".dot"},
    "xls": {".xls", ".xlt"},
    "ppt": {".ppt", ".pps", ".pot"},
    "msg": {".msg"},
    "docx": {".docx", ".docm", ".dotx"},
    "xlsx": {".xlsx", ".xlsm", ".xltx"},
    "pptx": {".pptx", ".pptm", ".potx", ".ppsx"},
    "mp3": {".mp3"},
    "rtf": {".rtf"},
}

#: Расширения, для которых тип определяется только расширением: сигнатуры нет.
TEXTUAL_EXTENSIONS = {
    ".txt": "txt",
    ".md": "md",
    ".csv": "csv",
    ".log": "log",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".gpx": "gpx",
    ".kml": "kml",
    ".eml": "eml",
}


@dataclass(frozen=True, slots=True)
class DetectedType:
    """Результат определения типа."""

    kind: str
    category: Category
    confidence: float
    method: str
    detail: str = ""

    @property
    def is_known(self) -> bool:
        return bool(self.kind)


def read_header(path: Path, size: int = HEADER_SIZE) -> bytes:
    """Прочитать заголовок файла (только чтение)."""
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _zip_inner_type(path: Path) -> tuple[str, str]:
    """Определить конкретный тип ZIP-контейнера по списку записей.

    Архив не распаковывается: читается только центральный каталог.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()[:200]
    except (zipfile.BadZipFile, OSError):
        return "zip", "повреждённый или нестандартный ZIP"
    joined = "\n".join(names)
    if "word/document.xml" in joined:
        return "docx", "OOXML word/"
    if "xl/workbook.xml" in joined:
        has_macros = "xl/vbaProject.bin" in joined
        return ("xlsm" if has_macros else "xlsx"), "OOXML xl/"
    if "ppt/presentation.xml" in joined:
        return "pptx", "OOXML ppt/"
    if "mimetypeapplication/epub" in joined.replace(" ", ""):
        return "epub", "EPUB"
    if any(name.lower().endswith(".kml") for name in names):
        return "kmz", "KMZ"
    if "mimetype" in names or any(name.startswith("ODF") for name in names):
        return "odf", "OpenDocument"
    return "zip", "обычный ZIP"


def _ftyp_brand(header: bytes) -> str:
    """Марка ISO BMFF (``ftyp``) для MP4/MOV/HEIC/AVIF."""
    if len(header) < 12 or header[4:8] != b"ftyp":
        return ""
    return header[8:12].decode("ascii", errors="replace").strip().lower()


def detect_by_signature(path: Path, header: bytes | None = None) -> DetectedType:
    """Определить тип по сигнатуре содержимого."""
    data = header if header is not None else read_header(path)
    if not data:
        return DetectedType("", Category.OTHER, 0.0, "signature", "пустой файл")

    def result(kind: str, detail: str = "", confidence: float = 0.98) -> DetectedType:
        return DetectedType(
            kind, TYPE_CATEGORY.get(kind, Category.OTHER), confidence, "signature", detail
        )

    if data.startswith(b"%PDF-"):
        return result("pdf", "%PDF-")
    if data.startswith(b"PK\x03\x04") or data.startswith(b"PK\x05\x06"):
        kind, detail = _zip_inner_type(path)
        return result(kind, detail)
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return DetectedType("ole2", Category.DOCUMENT, 0.9, "signature", "OLE2 контейнер")
    if data.startswith(b"{\\rtf"):
        return result("rtf", "{\\rtf")
    if data.startswith(b"\xff\xd8\xff"):
        return result("jpg", "JFIF/EXIF")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return result("png")
    if data.startswith((b"GIF87a", b"GIF89a")):
        return result("gif")
    if data.startswith(b"BM"):
        return result("bmp", "", 0.8)
    if data.startswith((b"II*\x00", b"MM\x00*")):
        # DNG и большинство RAW — контейнеры TIFF.
        suffix = path.suffix.lower()
        if suffix in EXTENSION_ALIASES["raw"]:
            return result("raw", "TIFF-контейнер RAW", 0.85)
        if suffix == ".dng":
            return result("dng", "TIFF-контейнер DNG")
        return result("tiff")
    if data.startswith(b"RIFF") and len(data) >= 12:
        form = data[8:12]
        if form == b"WEBP":
            return result("webp")
        if form == b"WAVE":
            return result("wav")
        if form == b"AVI ":
            return result("avi")
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        kind = "webm" if b"webm" in data[:64].lower() else "mkv"
        return result(kind, "EBML")
    if data.startswith(b"OggS"):
        return result("ogg")
    if data.startswith(b"fLaC"):
        return result("flac")
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return result("mp3", "", 0.85)
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return result("7z")
    if data.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return result("rar")
    if data.startswith(b"\x1f\x8b"):
        return result("gz")
    if len(data) > 262 and data[257:262] == b"ustar":
        return result("tar")
    if data.startswith(b"#!AMR"):
        return result("amr")
    if data.startswith(b"FORM") and len(data) >= 12 and data[8:12] in (b"AIFF", b"AIFC"):
        return result("aiff")
    if data.startswith(b"0&\xb2u\x8ef\xcf\x11"):
        return result("wma", "ASF")

    brand = _ftyp_brand(data)
    if brand:
        if brand.startswith(("heic", "heix", "hevc", "mif1", "msf1", "heim")):
            return result("heic", f"ftyp {brand}")
        if brand.startswith("avif") or brand.startswith("avis"):
            return result("avif", f"ftyp {brand}")
        if brand.startswith("qt"):
            return result("mov", f"ftyp {brand}")
        if brand.startswith("crx"):
            return result("raw", f"ftyp {brand} (CR3)")
        if brand.startswith(("isom", "mp4", "m4a", "m4v", "3gp", "dash", "iso2", "avc1")):
            kind = "m4a" if brand.startswith("m4a") else "mp4"
            return result(kind, f"ftyp {brand}")
        return result("mp4", f"ftyp {brand}", 0.7)

    head = data.lstrip()[:512].lower()
    if head.startswith(b"<?xml"):
        if b"<gpx" in data[:2048].lower():
            return result("gpx", "XML/GPX")
        if b"<kml" in data[:2048].lower():
            return result("kml", "XML/KML")
        return result("xml", "XML declaration", 0.9)
    if head.startswith((b"<!doctype html", b"<html")):
        return result("html", "HTML", 0.9)
    if head.startswith((b"return-path:", b"received:", b"message-id:", b"from:")):
        return result("eml", "RFC 822 headers", 0.85)

    return DetectedType("", Category.OTHER, 0.0, "signature", "сигнатура не распознана")


def _looks_like_text(data: bytes) -> bool:
    """Грубая проверка «это текст, а не двоичные данные»."""
    if not data:
        return False
    if b"\x00" in data[:4096]:
        return False
    control = sum(1 for byte in data[:4096] if byte < 9 or (13 < byte < 32))
    return control / max(1, min(len(data), 4096)) < 0.02


def detect_type(path: Path) -> DetectedType:
    """Определить тип файла: сигнатура, затем расширение как подсказка."""
    path = Path(path)
    header = read_header(path)
    detected = detect_by_signature(path, header)
    suffix = path.suffix.lower()

    if detected.kind == "ole2":
        # Конкретный legacy-формат уточняется по расширению: точное определение
        # требует разбора OLE-структуры и выполняется reader'ом.
        mapping = {".doc": "doc", ".xls": "xls", ".ppt": "ppt", ".msg": "msg"}
        kind = mapping.get(suffix, "ole2")
        return DetectedType(
            kind,
            TYPE_CATEGORY.get(kind, Category.DOCUMENT),
            0.85,
            "signature+extension",
            detected.detail,
        )

    if detected.is_known:
        return detected

    if _looks_like_text(header):
        kind = TEXTUAL_EXTENSIONS.get(suffix, "txt")
        if kind == "txt" and suffix and suffix not in TEXTUAL_EXTENSIONS:
            kind = "txt"
        return DetectedType(
            kind,
            TYPE_CATEGORY.get(kind, Category.DOCUMENT),
            0.6,
            "text-heuristic",
            "текстовый файл",
        )

    kind = suffix.lstrip(".") or ""
    if kind:
        return DetectedType(
            kind,
            TYPE_CATEGORY.get(kind, Category.OTHER),
            0.3,
            "extension",
            "тип определён только по расширению",
        )
    return DetectedType("", Category.OTHER, 0.0, "unknown", "тип не определён")


def extension_matches(detected: DetectedType, path: Path) -> bool:
    """Соответствует ли расширение обнаруженному типу."""
    suffix = path.suffix.lower()
    if not detected.is_known or not suffix:
        return True
    allowed = EXTENSION_ALIASES.get(detected.kind, {f".{detected.kind}"})
    return suffix in allowed


def check_extension(path: Path, detected: DetectedType) -> str:
    """Вернуть ``EXTENSION_MISMATCH`` при расхождении, иначе пустую строку.

    Само расширение не меняется (раздел 10 ТЗ).
    """
    if detected.method == "extension" or detected.confidence < 0.6:
        return ""
    return "" if extension_matches(detected, path) else Status.EXTENSION_MISMATCH.value
