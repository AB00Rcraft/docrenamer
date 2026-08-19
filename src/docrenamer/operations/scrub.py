"""Очистка метаданных файла — отдельная явная операция.

Основное правило программы — не менять содержимое пользовательских файлов
(раздел 6 ТЗ), и переименование его не нарушает: там сверяется контрольная
сумма до и после. Очистка метаданных — единственное исключение, и потому она
устроена как отдельная операция: запускается только по прямой команде, по
умолчанию создаёт очищенные копии, а замену исходных файлов подтверждает
человек.

Что снимается:

* JPEG — все сегменты ``APPn`` и комментарии: EXIF, GPS, миниатюра, IPTC, XMP,
  профиль ICC. Сжатые данные изображения переписываются побайтно, поэтому
  картинка не теряет качества;
* PNG — все необязательные блоки, кроме нужных для показа: подписи, время,
  EXIF;
* PDF — свойства документа (автор, программа, даты) и XMP;
* DOCX, XLSX, PPTX — ``docProps``: автор, кем изменён, организация, время
  правки, номер редакции; отметки времени внутри архива обнуляются.

Чего очистка не делает — об этом честно сказано в интерфейсе:

* не трогает сам текст: подпись и фамилия, набранные внутри документа,
  остаются;
* не убирает исправления и примечания Word — это содержимое, а не метаданные;
* не отменяет того, что копия файла могла остаться в другом месте.
"""

from __future__ import annotations

import os
import shutil
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from docrenamer.types import Status

#: Больше этого файл не обрабатывается: очистка должна быть быстрой и
#: предсказуемой по памяти.
MAX_SCRUB_BYTES = 512 * 1024 * 1024

#: Имя папки, куда складываются очищенные копии.
CLEAN_SUBDIR = "Без метаданных"

#: Сегменты JPEG, которые несут метаданные: APP0–APP15 и комментарий.
JPEG_METADATA_MARKERS = frozenset(range(0xE0, 0xF0)) | {0xFE}

#: Блоки PNG, без которых картинка всё равно покажется правильно.
PNG_KEEP_CHUNKS = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"sRGB", b"gAMA"})

#: Части OOXML-пакета, где хранятся сведения об авторе и правках.
OOXML_PROPERTY_PARTS = {
    "docProps/core.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
    ),
    "docProps/app.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Properties '
        'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>'
    ),
    "docProps/custom.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Properties '
        'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>'
    ),
}

#: Неизменная отметка времени для записей архива: иначе по ним видно, когда
#: документ правили.
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

OOXML_SUFFIXES = frozenset({".docx", ".xlsx", ".xlsm", ".pptx", ".docm", ".pptm"})
PILLOW_SUFFIXES = frozenset({".tif", ".tiff", ".webp", ".bmp", ".gif"})


@dataclass(slots=True)
class ScrubOutcome:
    """Результат очистки одного файла."""

    source_path: Path
    target_path: Path | None = None
    ok: bool = False
    status: str = ""
    message: str = ""
    #: Что именно удалено — по-русски, для журнала и отчёта.
    removed: list[str] = field(default_factory=list)
    #: Что осталось и о чём стоит знать.
    warnings: list[str] = field(default_factory=list)
    size_before: int = 0
    size_after: int = 0
    replaced: bool = False


def can_scrub(path: Path) -> bool:
    """Умеет ли программа снимать метаданные с такого файла."""
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".pdf"}:
        return True
    return suffix in OOXML_SUFFIXES or suffix in PILLOW_SUFFIXES


def scrub_file(
    path: Path, *, replace: bool = False, output_dir: Path | None = None
) -> ScrubOutcome:
    """Снять метаданные с файла.

    Args:
        path: исходный файл.
        replace: заменить исходный файл очищенным. По умолчанию рядом
            создаётся очищенная копия, а исходный файл остаётся нетронутым.
        output_dir: куда класть копию. По умолчанию — подпапка «Без
            метаданных» рядом с файлом.

    Returns:
        Результат операции. Исходный файл не изменяется, пока очищенная копия
        не построена и не проверена.
    """
    outcome = ScrubOutcome(source_path=path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        outcome.status = Status.READ_ERROR.value
        outcome.message = f"Файл недоступен: {exc}"
        return outcome
    outcome.size_before = size

    if size > MAX_SCRUB_BYTES:
        outcome.status = Status.LIMIT_EXCEEDED.value
        outcome.message = "Файл слишком велик для очистки."
        return outcome
    if not can_scrub(path):
        outcome.status = Status.UNSUPPORTED_FORMAT.value
        outcome.message = "Для этого формата очистка метаданных не поддержана."
        return outcome

    # Очищенный файл сначала строится во временном файле рядом: пока он не
    # готов и не проверен, исходный не трогается.
    temporary = path.with_name(f".{path.name}.scrub")
    try:
        removed, warnings = _write_clean(path, temporary)
    except Exception as exc:  # недоверенный вход: любой сбой — это отказ
        _remove_quietly(temporary)
        outcome.status = Status.READ_ERROR.value
        outcome.message = f"Очистка не выполнена: {exc}"
        return outcome

    if not temporary.is_file() or temporary.stat().st_size == 0:
        _remove_quietly(temporary)
        outcome.status = Status.READ_ERROR.value
        outcome.message = "Очищенный файл не построен."
        return outcome

    outcome.removed = removed
    outcome.warnings = warnings
    outcome.size_after = temporary.stat().st_size

    if replace:
        try:
            os.replace(temporary, path)
        except OSError as exc:
            _remove_quietly(temporary)
            outcome.status = Status.ACCESS_DENIED.value
            outcome.message = f"Не удалось заменить файл: {exc}"
            return outcome
        outcome.target_path = path
        outcome.replaced = True
    else:
        directory = output_dir or (path.parent / CLEAN_SUBDIR)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = _free_name(directory / path.name)
            shutil.move(str(temporary), str(target))
        except OSError as exc:
            _remove_quietly(temporary)
            outcome.status = Status.ACCESS_DENIED.value
            outcome.message = f"Копия не сохранена: {exc}"
            return outcome
        outcome.target_path = target

    outcome.ok = True
    outcome.status = Status.OK.value
    outcome.message = "Метаданные удалены." if removed else "Метаданных в файле не было."
    return outcome


def _write_clean(path: Path, target: Path) -> tuple[list[str], list[str]]:
    """Построить очищенную копию. Возвращает, что удалено и о чём предупредить."""
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return _clean_jpeg(path, target)
    if suffix == ".png":
        return _clean_png(path, target)
    if suffix == ".pdf":
        return _clean_pdf(path, target)
    if suffix in OOXML_SUFFIXES:
        return _clean_ooxml(path, target)
    return _clean_with_pillow(path, target)


# --- изображения --------------------------------------------------------


def _clean_jpeg(path: Path, target: Path) -> tuple[list[str], list[str]]:
    """Убрать из JPEG все сегменты метаданных, не трогая само изображение.

    Сжатые данные переписываются байт в байт: снимок не пережимается и не
    теряет качества, исчезают только EXIF, GPS, миниатюра, IPTC и XMP.
    """
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Файл не является JPEG.")

    removed: list[str] = []
    output = bytearray(b"\xff\xd8")
    position = 2
    length = len(data)
    while position < length - 1:
        if data[position] != 0xFF:
            # Рассинхронизация структуры — дальше данные не разбираем.
            output += data[position:]
            break
        marker = data[position + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            output += data[position : position + 2]
            position += 2
            continue
        if marker == 0xDA:  # начало данных изображения — дальше всё как есть
            output += data[position:]
            break
        if position + 4 > length:
            output += data[position:]
            break
        segment_length = struct.unpack(">H", data[position + 2 : position + 4])[0]
        end = position + 2 + segment_length
        if marker in JPEG_METADATA_MARKERS:
            removed.append(_jpeg_segment_name(marker, data[position + 4 : min(end, length)]))
        else:
            output += data[position:end]
        position = end

    target.write_bytes(bytes(output))
    return sorted(set(removed)), []


def _jpeg_segment_name(marker: int, payload: bytes) -> str:
    """Понятное название сегмента JPEG."""
    head = payload[:6].split(b"\x00")[0].decode("ascii", "replace")
    if marker == 0xFE:
        return "комментарий"
    if head.startswith("Exif"):
        return "EXIF (дата съёмки, камера, GPS)"
    if head.startswith("http") or head.startswith("XMP"):
        return "XMP"
    if head.startswith("Photoshop"):
        return "IPTC (подписи Photoshop)"
    if head.startswith("ICC"):
        return "цветовой профиль ICC"
    if head.startswith("JFIF"):
        return "JFIF (плотность, миниатюра)"
    return f"служебный сегмент APP{marker - 0xE0}"


def _clean_png(path: Path, target: Path) -> tuple[list[str], list[str]]:
    """Оставить в PNG только блоки, нужные для показа изображения."""
    data = path.read_bytes()
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise ValueError("Файл не является PNG.")

    removed: list[str] = []
    output = bytearray(signature)
    position = len(signature)
    while position + 8 <= len(data):
        size = struct.unpack(">I", data[position : position + 4])[0]
        name = data[position + 4 : position + 8]
        end = position + 12 + size
        if end > len(data):
            break
        if name in PNG_KEEP_CHUNKS:
            output += data[position:end]
        else:
            removed.append(_png_chunk_name(name))
        position = end
        if name == b"IEND":
            break

    target.write_bytes(bytes(output))
    return sorted(set(removed)), []


def _png_chunk_name(name: bytes) -> str:
    """Понятное название блока PNG."""
    label = name.decode("ascii", "replace")
    known = {
        "tEXt": "текстовые подписи",
        "iTXt": "текстовые подписи",
        "zTXt": "текстовые подписи",
        "tIME": "время изменения",
        "eXIf": "EXIF (дата съёмки, камера, GPS)",
        "iCCP": "цветовой профиль ICC",
    }
    return known.get(label, f"блок {label}")


def _clean_with_pillow(path: Path, target: Path) -> tuple[list[str], list[str]]:
    """Пересохранить изображение без метаданных средствами Pillow."""
    from PIL import Image

    with Image.open(path) as image:
        image.load()
        clean = Image.new(image.mode, image.size)
        clean.putdata(list(image.getdata()))
        clean.save(target, format=image.format)
    return ["метаданные изображения"], [
        "Файл пересохранён: возможны отличия сжатия от исходного."
    ]


# --- документы ----------------------------------------------------------


def _clean_pdf(path: Path, target: Path) -> tuple[list[str], list[str]]:
    """Убрать свойства документа и XMP из PDF."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    reader = PdfReader(str(path))
    removed: list[str] = []
    if reader.metadata:
        removed.append("свойства документа (автор, программа, даты)")

    writer = PdfWriter(clone_from=str(path))
    writer.metadata = None
    root = writer.root_object
    if NameObject("/Metadata") in root:
        del root[NameObject("/Metadata")]
        removed.append("XMP")
    with target.open("wb") as handle:
        writer.write(handle)

    warnings: list[str] = []
    if reader.is_encrypted:
        warnings.append("Файл был защищён паролем — защита не восстанавливается.")
    return removed, warnings


def _clean_ooxml(path: Path, target: Path) -> tuple[list[str], list[str]]:
    """Обнулить свойства документа Office, не трогая его содержимое.

    Части ``docProps`` не удаляются, а заменяются пустыми: так пакет остаётся
    правильным для любого редактора, а автор, организация, число правок и
    время работы над документом исчезают.
    """
    removed: list[str] = []
    warnings: list[str] = []
    with zipfile.ZipFile(path) as source:
        names = source.namelist()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as destination:
            for name in names:
                data = source.read(name)
                if name in OOXML_PROPERTY_PARTS:
                    if data.strip():
                        removed.append(_ooxml_part_name(name))
                    data = OOXML_PROPERTY_PARTS[name].encode("utf-8")
                elif name.endswith(".xml") and (b"w:ins " in data or b"w:del " in data):
                    warnings.append(
                        "В документе есть исправления и примечания — это содержимое, "
                        "и очистка их не трогает."
                    )
                info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                destination.writestr(info, data)
    if not removed:
        removed.append("отметки времени внутри документа")
    return sorted(set(removed)), sorted(set(warnings))


def _ooxml_part_name(part: str) -> str:
    """Понятное название части пакета Office."""
    return {
        "docProps/core.xml": "автор, кем изменён, даты",
        "docProps/app.xml": "организация, время правки, число редакций",
        "docProps/custom.xml": "дополнительные свойства",
    }.get(part, part)


# --- проверка результата ------------------------------------------------


def metadata_left(path: Path) -> list[str]:
    """Что ещё осталось в файле после очистки.

    Проверка выполняется теми же средствами, что и обычное чтение файла:
    если что-то видно программе, то видно и любому другому читателю.
    """
    suffix = path.suffix.lower()
    left: list[str] = []
    try:
        if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}:
            from PIL import Image

            with Image.open(path) as image:
                if getattr(image, "_getexif", lambda: None)():
                    left.append("EXIF")
                if getattr(image, "info", None):
                    keys = {
                        key
                        for key in image.info
                        if key
                        not in {"jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi",
                                "transparency", "gamma", "srgb", "aspect"}
                    }
                    left.extend(sorted(str(key) for key in keys))
        elif suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            if reader.metadata:
                left.extend(sorted(str(key) for key in reader.metadata))
        elif suffix in OOXML_SUFFIXES:
            with zipfile.ZipFile(path) as archive:
                for part in OOXML_PROPERTY_PARTS:
                    if part not in archive.namelist():
                        continue
                    text = archive.read(part).decode("utf-8", "replace")
                    if "<dc:" in text or "<cp:lastModifiedBy>" in text or "<Company>" in text:
                        left.append(part)
    except Exception:
        # Проверка вспомогательная: её сбой не отменяет самой очистки.
        return left
    return left


def _free_name(target: Path) -> Path:
    """Не затирать уже существующую очищенную копию."""
    if not target.exists():
        return target
    for number in range(2, 1000):
        candidate = target.with_name(f"{target.stem}__{number:02d}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError("Слишком много копий с таким именем.")


def _remove_quietly(path: Path) -> None:
    """Убрать собственный временный файл программы."""
    try:
        if path.is_file():
            os.remove(path)
    except OSError:
        return
