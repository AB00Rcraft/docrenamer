"""Reader'ы форматов (разделы 15–32 ТЗ).

Каждый reader получает путь и :class:`docrenamer.analysis.ReaderContext`, а
возвращает :class:`docrenamer.types.ReadResult`. Reader'ы никогда не открывают
пользовательский файл на запись и не исполняют встроенный в него код.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docrenamer.readers.archive_reader import read_archive
from docrenamer.readers.docx_reader import read_docx
from docrenamer.readers.eml_reader import read_eml
from docrenamer.readers.html_reader import read_html
from docrenamer.readers.image_reader import read_image
from docrenamer.readers.json_reader import read_json
from docrenamer.readers.legacy_ole_reader import read_ole
from docrenamer.readers.media_reader import read_media
from docrenamer.readers.msg_reader import read_msg
from docrenamer.readers.pdf_reader import read_pdf
from docrenamer.readers.pptx_reader import read_pptx
from docrenamer.readers.text_reader import read_csv, read_rtf, read_text
from docrenamer.readers.xls_reader import read_xls
from docrenamer.readers.xlsx_reader import read_xlsx
from docrenamer.readers.xml_reader import read_kmz, read_xml

if TYPE_CHECKING:  # pragma: no cover
    from docrenamer.analysis import ReaderContext

#: Полная таблица «тип файла → reader» (support matrix из ARCHITECTURE.md).
READERS: dict[str, Any] = {
    # Документы
    "pdf": read_pdf,
    "docx": read_docx,
    "xlsx": read_xlsx,
    "xlsm": read_xlsx,
    "pptx": read_pptx,
    "doc": read_ole,
    "ppt": read_ole,
    "ole2": read_ole,
    "xls": read_xls,
    "rtf": read_rtf,
    # Текст и разметка
    "txt": read_text,
    "md": read_text,
    "log": read_text,
    "csv": read_csv,
    "html": read_html,
    "xml": read_xml,
    "gpx": read_xml,
    "kml": read_xml,
    "kmz": read_kmz,
    "json": read_json,
    # Почта
    "eml": read_eml,
    "msg": read_msg,
    # Изображения
    "jpg": read_image,
    "png": read_image,
    "gif": read_image,
    "bmp": read_image,
    "tiff": read_image,
    "webp": read_image,
    "heic": read_image,
    "avif": read_image,
    "dng": read_image,
    "raw": read_image,
    # Видео и аудио
    "mp4": read_media,
    "mov": read_media,
    "avi": read_media,
    "mkv": read_media,
    "webm": read_media,
    "mts": read_media,
    "mp3": read_media,
    "m4a": read_media,
    "wav": read_media,
    "flac": read_media,
    "ogg": read_media,
    "wma": read_media,
    "aiff": read_media,
    "amr": read_media,
    # Архивы — только инспекция
    "zip": read_archive,
    "7z": read_archive,
    "rar": read_archive,
    "tar": read_archive,
    "gz": read_archive,
    # Резервные обработчики по категории, если конкретный тип неизвестен
    "category:image": read_image,
    "category:video": read_media,
    "category:audio": read_media,
    "category:archive": read_archive,
}


def build_reader_registry(context: ReaderContext) -> dict[str, Any]:
    """Собрать таблицу reader'ов для текущей конфигурации."""
    return dict(READERS)


__all__ = ["READERS", "build_reader_registry"]
