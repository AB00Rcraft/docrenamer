"""Предпросмотр выбранного файла (раздел 79 ТЗ по смыслу).

Правильность имени видна не из имени, а из содержимого: достаточно взглянуть
на первую страницу скана или на начало документа, чтобы понять, то ли это.
Поэтому в окне рядом со списком показывается сам файл — снимок и первая
страница PDF картинкой, документ — началом распознанного текста.

Модуль намеренно не зависит от Tkinter: это упрощает проверку и позволяет
готовить предпросмотр там, где графической подсистемы нет.

Файл открывается только на чтение. Ничего не распаковывается, макросы не
исполняются, размер ограничен — предпросмотр не имеет права стать способом
подсунуть программе тяжёлый или враждебный файл.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from docrenamer.types import Category, FileAnalysis, PlanItem, Source

#: Больше этого файл не открывается ради картинки: предпросмотр должен быть
#: мгновенным, а не «подождите, читаю 300 мегабайт».
MAX_PREVIEW_BYTES = 60 * 1024 * 1024

#: Размер миниатюры по умолчанию.
DEFAULT_SIZE = (460, 340)

#: Сколько знаков текста показывать.
TEXT_LIMIT = 900

#: Сколько имён показывать для папки.
FOLDER_ENTRIES = 15


def thumbnail_png(path: Path, size: tuple[int, int] = DEFAULT_SIZE) -> bytes | None:
    """Миниатюра файла в формате PNG.

    Снимки читаются Pillow, PDF — первой страницей через pypdfium2: у скана
    первая страница и есть то, что нужно увидеть.

    Returns:
        Данные PNG либо ``None``, если показать нечего.
    """
    try:
        if not path.is_file() or path.stat().st_size > MAX_PREVIEW_BYTES:
            return None
    except OSError:
        return None

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_thumbnail(path, size)
    return _image_thumbnail(path, size)


def _image_thumbnail(path: Path, size: tuple[int, int]) -> bytes | None:
    """Миниатюра снимка."""
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover — Pillow входит в сборку
        return None
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:  # pragma: no cover — HEIC без плагина недоступен
        pass

    try:
        with Image.open(path) as image:
            # Снимок с телефона хранится повёрнутым: без учёта EXIF
            # предпросмотр ляжет на бок.
            prepared = ImageOps.exif_transpose(image) or image
            prepared.thumbnail(size)
            return _to_png(prepared)
    except Exception:
        # Предпросмотр — вспомогательная возможность: испорченный файл не
        # должен мешать работе со списком.
        return None


def _pdf_thumbnail(path: Path, size: tuple[int, int]) -> bytes | None:
    """Первая страница PDF картинкой."""
    try:
        import pypdfium2
    except ImportError:  # pragma: no cover — зависимость входит в сборку
        return None

    document = None
    try:
        document = pypdfium2.PdfDocument(str(path))
        if len(document) == 0:
            return None
        page = document[0]
        width, height = page.get_size()
        if not width or not height:
            return None
        scale = min(size[0] / width, size[1] / height)
        bitmap = page.render(scale=max(0.1, min(scale, 4.0)))
        return _to_png(bitmap.to_pil())
    except Exception:
        return None
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:  # noqa: S110 — закрытие не должно ломать интерфейс
                pass


def _to_png(image: object) -> bytes | None:
    """Перевести изображение Pillow в PNG."""
    try:
        buffer = io.BytesIO()
        prepared = image.convert("RGB")  # type: ignore[attr-defined]
        prepared.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def text_preview(item: PlanItem, *, limit: int = TEXT_LIMIT) -> str:
    """Начало содержимого файла словами.

    Показывается то, что программа действительно прочитала: по этому тексту и
    строилось имя, поэтому по нему же видно, справедливо ли оно.
    """
    analysis: FileAnalysis | None = item.analysis
    if item.is_folder:
        return folder_preview(item.source_path)
    if analysis is None:
        return "Файл ещё не разобран — нажмите «Предпросмотр»."

    text = (analysis.read_result.text if analysis.read_result else "") or ""
    text = " ".join(text.split())
    if text:
        head = text[:limit]
        return head + ("…" if len(text) > limit else "")

    lines = [_metadata_line(analysis)]
    if analysis.category is Category.IMAGE:
        lines.append("Текст на снимке не распознан.")
    elif analysis.error:
        lines.append(analysis.error)
    else:
        lines.append("Текст не извлечён — имя построено по свойствам файла.")
    return "\n".join(line for line in lines if line)


def _metadata_line(analysis: FileAnalysis) -> str:
    """Короткая строка о том, что известно о файле помимо текста."""
    metadata = analysis.metadata or {}
    parts: list[str] = []
    width, height = metadata.get("width"), metadata.get("height")
    if width and height:
        parts.append(f"{width}×{height}")
    device = metadata.get("device")
    if device:
        parts.append(str(device))
    duration = metadata.get("duration_seconds")
    if duration:
        parts.append(f"{float(duration):.0f} с")
    entries = metadata.get("entry_count")
    if entries:
        parts.append(f"файлов внутри: {entries}")
    pages = metadata.get("page_count")
    if pages:
        parts.append(f"страниц: {pages}")
    return "   ".join(parts)


def folder_preview(path: Path, *, limit: int = FOLDER_ENTRIES) -> str:
    """Что лежит в папке — по этому и предлагается её имя."""
    try:
        entries = sorted(
            path.iterdir(), key=lambda entry: (entry.is_file(), entry.name.casefold())
        )
    except OSError as exc:
        return f"Папка не прочитана: {exc}"
    if not entries:
        return "Папка пуста."
    names = [f"{'📁 ' if entry.is_dir() else ''}{entry.name}" for entry in entries[:limit]]
    if len(entries) > limit:
        names.append(f"…ещё {len(entries) - limit}")
    return "\n".join(names)


def format_size(size: int) -> str:
    """Размер файла по-человечески."""
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} КБ"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} МБ"
    return f"{size / (1024 * 1024 * 1024):.1f} ГБ"


def format_stamp(moment: float) -> str:
    """Время файла в российском формате."""
    if moment <= 0:
        return ""
    try:
        return datetime.fromtimestamp(moment).strftime("%d.%m.%Y %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def metadata_cell(item: PlanItem) -> str:
    """Строка метаданных для колонки списка.

    Размер и время изменения — то, что при переименовании обязано остаться
    прежним. Их видно прямо в списке, до и после операции.
    """
    if item.is_folder:
        return ""
    parts = [format_size(item.size)]
    stamp = format_stamp(item.mtime)
    if stamp:
        parts.append(stamp)
    return " · ".join(parts)


def metadata_summary(item: PlanItem) -> str:
    """Метаданные выбранного файла — подробно.

    Переименование меняет запись в каталоге, а не сам файл: размер, время и
    содержимое остаются прежними, и это проверяется контрольной суммой до и
    после операции.
    """
    if item.is_folder:
        return "Папка: метаданные файлов внутри не затрагиваются."
    lines = [
        f"Размер: {format_size(item.size)}    Изменён: {format_stamp(item.mtime)}",
        f"SHA-256: {item.sha256[:16]}…" if item.sha256 else "",
    ]
    analysis = item.analysis
    metadata = (analysis.metadata if analysis is not None else {}) or {}
    extra: list[str] = []
    for key, label in (
        ("datetime", "снят"),
        ("device", "камера"),
        ("author", "автор"),
        ("title", "заголовок"),
        ("created", "создан"),
        ("page_count", "страниц"),
        ("width", "ширина"),
        ("height", "высота"),
    ):
        value = metadata.get(key)
        if value:
            extra.append(f"{label}: {value}")
    if extra:
        lines.append("Из файла: " + ", ".join(extra[:6]))
    lines.append("Переименование не меняет ни содержимое, ни время файла.")
    return "\n".join(line for line in lines if line)


def file_card(item: PlanItem, root: Path | None = None) -> str:
    """Сведения о выбранном файле — карточка под предпросмотром.

    Здесь собрано всё, из чего сложилось предложенное имя: где файл лежит, что
    программа в нём распознала и на каком основании, насколько уверена, а
    также метаданные, которые переименование не тронет.
    """
    lines = [f"Сейчас:  {item.source_path.name}"]
    if item.is_rename:
        lines.append(f"Станет:  {item.proposed_filename}")
    else:
        lines.append("Станет:  имя остаётся прежним")
    if root is not None:
        try:
            inside = item.source_path.parent.relative_to(root)
            lines.append(f"Папка:   {inside if str(inside) != '.' else 'корень выбранной папки'}")
        except ValueError:
            lines.append(f"Папка:   {item.source_path.parent}")

    analysis = item.analysis
    if analysis is not None:
        for label, value in _facts(analysis):
            lines.append(f"{label:9}{value}")

    lines.append(
        f"Уверенность: {item.confidence * 100:.0f}%    Состояние: {item.status}"
    )
    if item.message:
        lines.append(item.message)
    lines.append(metadata_summary(item))
    return "\n".join(line for line in lines if line)


def _facts(analysis: FileAnalysis) -> list[tuple[str, str]]:
    """Что распознано в файле и на каком основании (раздел 63 ТЗ)."""
    facts: list[tuple[str, str]] = []
    metadata = analysis.metadata or {}

    document_type = analysis.document_type
    if document_type is not None and document_type.accepted:
        canonical = str(metadata.get("document_type_canonical") or document_type.value)
        facts.append(("Вид:", f"{canonical}{_from(document_type.source)}"))

    document_date = analysis.document_date
    if document_date is not None and document_date.accepted:
        # Дата показывается так же, как пишется в имени.
        shown = _russian_date(str(document_date.value))
        facts.append(("Дата:", f"{shown}{_from(document_date.source)}"))

    number = analysis.document_number
    number_value = str(number.value) if number is not None and number.accepted else ""
    if number_value:
        facts.append(("Номер:", number_value))
    if analysis.case_numbers:
        case = str(analysis.case_numbers[0].value)
        # Номер документа и номер дела часто совпадают — повторять не за чем.
        if case != number_value:
            facts.append(("Дело:", case))
    if analysis.main_persons:
        facts.append(("Кто:", ", ".join(person.name for person in analysis.main_persons)))
    if analysis.main_organizations:
        facts.append(("Кем:", ", ".join(org.name for org in analysis.main_organizations)))

    page = metadata.get("scan_page")
    if isinstance(page, dict):
        facts.append(("Страница:", f"{page.get('page')} из {page.get('total')}"))
    series = metadata.get("series")
    if isinstance(series, dict):
        facts.append(("Часть:", str(series.get("segment", ""))))
    review = metadata.get("name_review")
    if isinstance(review, list) and review:
        notes = "; ".join(str(issue.get("message", "")) for issue in review[:2])
        facts.append(("Проверка:", notes))
    return facts


def _russian_date(value: str) -> str:
    """ISO-дату показать в привычном виде: день, месяц, год."""
    head = value[:10]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        year, month, day = head.split("-")
        return f"{day}.{month}.{year}" + value[10:]
    return value


def _from(source: Source) -> str:
    """Откуда взято значение — по-русски и коротко."""
    labels = {
        Source.TEXT: " (из текста)",
        Source.REGEX: " (из текста)",
        Source.METADATA: " (из свойств файла)",
        Source.FILENAME: " (из имени файла)",
        Source.FILESYSTEM: " (время файла)",
        Source.LLM: " (по разбору модели)",
    }
    return labels.get(source, "")
