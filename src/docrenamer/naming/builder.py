"""Сборка предложенного имени файла (разделы 27, 43, 44, 45 ТЗ).

Базовая грамматика::

    DATE__TYPE__SUBJECT__ENTITIES__IDENTIFIER.ext

Не все сегменты обязательны. В имя попадают только принятые значения — те, у
которых есть источник и подтверждение (раздел 63 ТЗ).
"""

from __future__ import annotations

import re

from docrenamer.config import Config
from docrenamer.extractors.dates import extract_dates
from docrenamer.naming.dates import date_variants, format_date_for_name
from docrenamer.naming.review import dedupe_key, is_blocking, review_name, review_segments
from docrenamer.naming.sanitizer import (
    MAX_FILENAME_BYTES,
    SEPARATOR_CHAR,
    Segment,
    assemble_filename,
    sanitize_component,
    sanitize_filename,
)
from docrenamer.textquality import comparison_key
from docrenamer.types import Category, EntityRef, Field, FileAnalysis, Source, Status, nfc

#: Слова, которые не делают имя осмысленным.
GENERIC_STEM_RE = re.compile(
    r"^(?:"
    r"img|image|dsc|dscn|dscf|pict|photo|foto|pxl|vid|mvi|mov|movie|clip|"
    r"scan|scan0*\d*|skan|doc|docs?|document|file|copy|new|snapshot|screenshot|"
    r"изображение|снимок|фото|видео|скан|документ|копия|новый|безымянный|без[\s_-]?имени"
    r")[\s_\-]*\d*$",
    re.IGNORECASE,
)

#: Имя-«штамп» устройства или системы: 20260818_142203, IMG_0032, 8f3a91c2.
TIMESTAMP_STEM_RE = re.compile(
    r"^(?:\d{4}[-_.]?\d{2}[-_.]?\d{2})?[\s_\-]*\d{0,8}$|^[0-9a-f]{8,}$", re.IGNORECASE
)

#: Имена по умолчанию, которые предлагают сами программы: смысла в них нет,
#: сколько бы слов в них ни было.
GENERIC_PHRASES: frozenset[str] = frozenset(
    {
        "новый документ",
        "новая презентация",
        "новая книга",
        "новый лист",
        "новый файл",
        "документ без имени",
        "без имени",
        "безымянный",
        "копия документа",
        "отсканированный документ",
        "скан документа",
        "new document",
        "untitled document",
        "untitled",
        "presentation",
        "презентация без названия",
    }
)

#: Минимальная длина слова, которое считается содержательным.
MEANINGFUL_WORD_LENGTH = 3
#: Длина одиночного слова, при которой имя уже считается осмысленным.
SINGLE_WORD_LENGTH = 8

#: Длиннее этого авторское имя уже неудобно: его лучше пересобрать в компактный
#: формат, использовав сведения, которые в этом имени есть.
MAX_PRESERVED_LENGTH = 70

_TOKEN_SPLIT_RE = re.compile(r"[\s_\-–—.,()]+")

#: Слова, которые сами по себе ничего не сообщают о документе.
FILLER_TOKENS: frozenset[str] = frozenset(
    {
        "скан", "scan", "скан-копия", "копия", "copy", "фото", "foto", "photo",
        "изображение", "image", "img", "файл", "file", "документ", "document",
        "doc", "новый", "новая", "new", "стр", "страница", "page", "видео", "video",
    }
)

#: Сколько участников попадает в имя. Два — предел читаемости.
MAX_ENTITIES_IN_NAME = 2

#: Порядок сегментов в имени файла.
#:
#: ``type-first`` — сначала вид документа и предмет, дата в конце. Так файлы
#: удобно сортировать по имени: одинаковые документы оказываются рядом.
#: ``date-first`` — сначала дата. Полезно вместе с форматом ``YYYY-MM-DD``,
#: когда нужен хронологический порядок.
NAME_ORDERS: frozenset[str] = frozenset({"type-first", "date-first"})

#: Приоритеты сегментов: чем выше, тем позже сегмент будет отброшен при
#: нехватке длины (раздел 45 ТЗ).
PRIORITY_DATE = 95
PRIORITY_IDENTIFIER = 90
PRIORITY_TYPE = 80
PRIORITY_ENTITY = 60
PRIORITY_DEVICE = 55
PRIORITY_ORIGINAL = 45
PRIORITY_SUBJECT = 25

#: Виды сегментов, которые несут содержательную информацию о файле.
#: Одной даты недостаточно: если о файле не удалось узнать ничего, кроме его
#: времени изменения, имя не предлагается (раздел 92 ТЗ).
#: Слова, взятые из прежнего имени файла, сюда не входят: если кроме них
#: сказать нечего, переписывать имя не за чем — мы ничего нового не узнали.
INFORMATIVE_KINDS: frozenset[str] = frozenset(
    {
        "type",
        "identifier",
        "entities",
        "subject",
        "device",
        "duration",
        "count",
        "gps",
        "archive_hint",
    }
)

#: Организационно-правовые формы: полное наименование → аббревиатура.
LEGAL_FORMS: tuple[tuple[str, str], ...] = (
    ("общество с ограниченной ответственностью", "ООО"),
    ("публичное акционерное общество", "ПАО"),
    ("непубличное акционерное общество", "АО"),
    ("закрытое акционерное общество", "ЗАО"),
    ("открытое акционерное общество", "ОАО"),
    ("акционерное общество", "АО"),
    ("индивидуальный предприниматель", "ИП"),
    ("крестьянское фермерское хозяйство", "КФХ"),
    ("товарищество собственников жилья", "ТСЖ"),
    ("садоводческое некоммерческое товарищество", "СНТ"),
    ("некоммерческое партнёрство", "НП"),
    ("автономная некоммерческая организация", "АНО"),
    ("государственное бюджетное учреждение", "ГБУ"),
    ("федеральное государственное унитарное предприятие", "ФГУП"),
    ("муниципальное унитарное предприятие", "МУП"),
    ("публично-правовая компания", "ППК"),
)

_QUOTES = "«»\"'“”„‟‘’"
_INITIALS_RE = re.compile(r"\b([А-ЯЁ])\.\s*([А-ЯЁ])\.")
_SPACE_RE = re.compile(r"\s+")


def is_well_formed_name(stem: str, type_words: frozenset[str] = frozenset()) -> bool:
    """Действительно ли имя аккуратное, а не небрежная пометка.

    Осмысленности мало. «седой дом газ» суть отражает, но это сокращённая
    пометка для себя: строчные буквы, ни вида документа, ни номера. Такое имя
    лучше пересобрать по содержанию, сохранив его слова. А вот
    «Постановление по делу Иванова» — уже готовое название, его трогать нельзя.

    Имя считается аккуратным, если в нём назван вид документа либо оно
    начинается с заглавной буквы и состоит не менее чем из трёх слов.
    """
    text = nfc(str(stem or "")).strip()
    if not text or not is_meaningful_stem(text):
        return False

    key = comparison_key(text)
    if any(word and word in key for word in type_words):
        return True

    words = [t for t in _TOKEN_SPLIT_RE.split(text) if sum(c.isalpha() for c in t) >= 3]
    return text[0].isupper() and len(words) >= 3


def is_meaningful_stem(stem: str) -> bool:
    """Похоже ли, что имя файла придумал человек, а не устройство.

    Осмысленным считается имя не менее чем из двух содержательных слов либо из
    одного достаточно длинного слова. Технические имена вида ``IMG_0032``,
    ``scan0007``, ``20260818_142203`` и ``Новый документ`` осмысленными не
    считаются.
    """
    text = nfc(str(stem or "")).strip()
    if not text:
        return False
    if GENERIC_STEM_RE.match(text) or TIMESTAMP_STEM_RE.match(text):
        return False
    # «Новый документ 2» — то же самое, что «Новый документ».
    phrase = re.sub(r"[\s_\-]*\d+$", "", comparison_key(text)).strip()
    if phrase in GENERIC_PHRASES:
        return False

    tokens = [t for t in _TOKEN_SPLIT_RE.split(text) if t]
    words = [
        t
        for t in tokens
        if sum(ch.isalpha() for ch in t) >= MEANINGFUL_WORD_LENGTH
        and comparison_key(t) not in FILLER_TOKENS
    ]
    if not words:
        return False
    # Профиль RUSSIAN-FIRST: авторское имя почти всегда содержит кириллицу.
    # Латинское имя без пробелов («vaccine_deck», «final_v2») — это, как
    # правило, служебное имя выгрузки, а не название документа.
    has_cyrillic = any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in text)
    if not has_cyrillic and " " not in text:
        return False
    if len(words) >= 2:
        return True
    return len(words[0]) >= SINGLE_WORD_LENGTH


def build_preserved_name(analysis: FileAnalysis, config: Config) -> tuple[str, list[str]]:
    """Сохранить осмысленное имя, дополнив его по единому образцу.

    Единственное допустимое дополнение — дата документа в начале имени, и
    только если её там ещё нет. Сам текст имени сохраняется как есть, включая
    пробелы, «№», кавычки и регистр букв: ломать хорошее имя нельзя
    (раздел 92 ТЗ).
    """
    original = analysis.source_path.stem
    unchanged = analysis.source_path.name
    canonical = _value(analysis.document_date)
    if not canonical:
        return unchanged, []
    date_value = format_date_for_name(canonical, config.naming.date_format)

    # Дата уже в имени — в любом виде, хоть «18 августа 2026 года».
    existing = {c.value for c in extract_dates(original)}
    if canonical in existing or any(variant in original for variant in date_variants(canonical)):
        return unchanged, []
    if analysis.document_date is not None and analysis.document_date.source is Source.FILESYSTEM:
        # Дата из файловой системы не повод трогать хорошее имя.
        return unchanged, []
    if analysis.has_status(Status.DATE_SOURCE_FILE_PROPERTY):
        # И тем более не повод — дата создания файла из свойств Office.
        return unchanged, []

    stem = sanitize_component(original, keep_spaces=True)
    if not stem:
        return unchanged, []

    separator = config.naming.separator
    if config.naming.order == "date-first":
        combined = f"{date_value}{separator}{stem}"
    else:
        combined = f"{stem}{separator}{date_value}"
    name = sanitize_filename(
        combined,
        analysis.source_path.suffix,
        max_length=config.naming.max_filename_length,
        max_bytes=MAX_FILENAME_BYTES,
        keep_spaces=True,
    )
    return name, []


def normalize_organization(name: str) -> str:
    """Привести наименование организации к компактному виду (раздел 43 ТЗ).

    ``Общество с ограниченной ответственностью "Альфа"`` → ``ООО-Альфа``.
    Полное значение сохраняется в manifest и не теряется.
    """
    text = nfc(str(name)).strip()
    if not text:
        return ""
    lowered = text.lower()
    abbreviation = ""
    for full, short in LEGAL_FORMS:
        if full in lowered:
            abbreviation = short
            lowered = lowered.replace(full, " ")
            pattern = re.compile(re.escape(full), re.IGNORECASE)
            text = pattern.sub(" ", text)
            break
    core = text.strip().strip(_QUOTES).strip()
    core = _SPACE_RE.sub(" ", core)
    if not abbreviation:
        # Возможно, форма уже задана аббревиатурой в начале строки.
        match = re.match(r"^(ООО|ПАО|ЗАО|ОАО|АО|ИП|ФГУП|МУП|ГБУ|АНО|ТСЖ|СНТ|НП|КФХ)\b", core)
        if match:
            abbreviation = match.group(1)
            core = core[match.end() :].strip().strip(_QUOTES).strip()
    core = core.strip(_QUOTES).strip(" -—–")
    if abbreviation and core:
        return f"{abbreviation}{SEPARATOR_CHAR}{core}"
    return core or abbreviation


def format_person(entity: EntityRef) -> str:
    """Компактное представление ФИО для имени файла (раздел 42 ТЗ)."""
    text = nfc(entity.name).strip()
    if not text:
        return ""
    text = text.replace("ё", "ё")  # Значение сохраняется как есть: замена ё→е запрещена.
    match = _INITIALS_RE.search(text)
    initials = ""
    if match:
        initials = f"{match.group(1)}{match.group(2)}"
        text = _INITIALS_RE.sub("", text).strip()
    parts = [p for p in _SPACE_RE.split(text) if p]
    if not parts:
        return initials
    surname = max(parts, key=len) if len(parts) == 1 else parts[0]
    if len(parts) >= 3 and all(len(p) > 2 for p in parts[:3]):
        # «Иванов Иван Иванович» → «ИвановИИ»: фамилии с инициалами достаточно,
        # чтобы узнать человека, а полное ФИО сохраняется в manifest.
        surname = parts[0]
        initials = initials or f"{parts[1][0]}{parts[2][0]}"
    elif len(parts) == 2 and len(parts[1]) <= 4 and "." in parts[1]:
        initials = initials or parts[1].replace(".", "")
        surname = parts[0]
    if initials:
        # Инициалы пишутся вплотную к фамилии: «ИвановИИ». Отдельный разделитель
        # здесь только мешает — фамилия с инициалами читается как одно целое.
        return f"{surname}{initials}"
    return surname


def _entities_segment(
    persons: list[EntityRef],
    organizations: list[EntityRef],
    config: Config,
) -> str:
    """Собрать сегмент участников: не более заданного числа лиц и организаций."""
    people = [format_person(p) for p in persons]
    orgs = [normalize_organization(o.name) for o in organizations]

    # Полное и сокращённое наименование одной организации нормализуются в одно
    # и то же значение — повтор в имени файла недопустим.
    def unique(values: list[str], limit: int) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = comparison_key(value)
            if not value or key in seen:
                continue
            seen.add(key)
            result.append(value)
            if len(result) >= limit:
                break
        return result

    # Человек в документе важнее организации: именно по фамилии файл ищут.
    parts = [
        *unique(people, config.naming.max_persons_in_filename),
        *unique(orgs, config.naming.max_organizations_in_filename),
    ]
    return SEPARATOR_CHAR.join(parts[:MAX_ENTITIES_IN_NAME])


def _value(field: Field | None) -> str:
    """Значение принятого поля или пустая строка."""
    if field is None or not field.accepted:
        return ""
    return str(field.value)


def _date_value(analysis: FileAnalysis, config: Config) -> str:
    """Дата документа в том виде, в котором она попадёт в имя файла.

    Дата из свойств файла в имя не выносится: у шаблонов Office свойство
    «created» фиктивно (2013 год), и такая дата в имени вводит в заблуждение.
    В анализе и в manifest она сохраняется — с пометкой источника.
    """
    value = _value(analysis.document_date)
    if not value:
        return ""
    if analysis.has_status(Status.DATE_SOURCE_FILE_PROPERTY):
        return ""
    return format_date_for_name(value, config.naming.date_format)


def _document_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для документов: DATE__TYPE__SUBJECT__ENTITIES__IDENTIFIER."""
    segments: list[Segment] = []
    date_value = _date_value(analysis, config)
    if not date_value:
        # Таблица живёт не одним днём: у реестра или ведомости в имени стоит
        # период, а не случайная дата из ячейки.
        date_value = str((analysis.metadata or {}).get("period") or "")
    if date_value:
        segments.append(Segment(date_value, PRIORITY_DATE, droppable=False, kind="date"))

    type_value = _value(analysis.document_type)
    if type_value:
        metadata = analysis.metadata or {}
        if metadata.get("document_type_default"):
            kind = "type_default"
        elif metadata.get("document_type_from_filename"):
            kind = "type_from_name"
        else:
            kind = "type"
        segments.append(Segment(type_value, PRIORITY_TYPE, droppable=False, kind=kind))

    subject_value = _value(analysis.subject)
    if subject_value:
        from_filename = (
            analysis.subject is not None and analysis.subject.source is Source.FILENAME
        )
        segments.append(
            Segment(
                subject_value,
                PRIORITY_SUBJECT,
                kind="subject_from_name" if from_filename else "subject",
            )
        )

    entities = _entities_segment(analysis.main_persons, analysis.main_organizations, config)
    if entities:
        segments.append(Segment(entities, PRIORITY_ENTITY, kind="entities"))

    identifier_field = analysis.document_number
    identifier = _value(identifier_field)
    if not identifier and analysis.case_numbers:
        identifier_field = analysis.case_numbers[0]
        identifier = _value(identifier_field)
    if identifier:
        # Номер, прочитанный в самом имени файла, форму имени задаёт, но нового
        # о документе не сообщает — переименовывать файл только ради него не за чем.
        from_filename = identifier_field is not None and identifier_field.source is Source.FILENAME
        segments.append(
            Segment(
                identifier,
                PRIORITY_IDENTIFIER,
                droppable=False,
                kind="identifier_from_name" if from_filename else "identifier",
            )
        )
    return segments


#: Дата и время внутри имени файла: 2024-06-04, 20240604, 22-41-34, 224134123.
_STEM_DATE_RE = re.compile(
    r"(?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}"       # 2024-06-04, 20240604
    r"|\d{2}[-_.]\d{2}[-_.](?:19|20)\d{2}"        # 04.06.2024
    r"|\d{2}[-_.]\d{2}[-_.]\d{2}(?:[-_.]?\d{1,3})?"  # 22-41-34, 22-41-34-123
)

#: Что остаётся от имени после удаления даты: длинные числовые хвосты не нужны.
_STEM_DIGITS_RE = re.compile(r"^\d{5,}$")


def clean_original_stem(stem: str) -> str:
    """Очистить исходное имя от даты и служебных слов.

    Имена вида ``photo_2024-06-04_22-41-34`` целиком состоят из даты, которая
    и так стоит в начале нового имени. Дублировать её — да ещё в другом
    порядке — бессмысленно. А короткий серийный номер вроде ``IMG_7834``
    сохранить полезно: по нему файл узнаётся среди других снимков.
    """
    text = _STEM_DATE_RE.sub(" ", nfc(str(stem or "")))
    parts: list[str] = []
    # Разбиваем только по пробелам и подчёркиваниям: «33-52030» — это одно
    # значение, и рвать его по дефису нельзя.
    for token in re.split(r"[\s_]+", text):
        token = token.strip()
        if not token:
            continue
        if comparison_key(token) in FILLER_TOKENS:
            continue
        if _STEM_DIGITS_RE.match(token):
            continue
        parts.append(token)
    if not parts:
        return ""
    # Отдельно стоящие короткие числа осмысленны только рядом с буквами
    # (IMG 7834), сами по себе — нет.
    if all(part.isdigit() for part in parts):
        return ""
    return SEPARATOR_CHAR.join(parts)


def _media_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для фото, видео и аудио (разделы 27, 28, 29 ТЗ)."""
    segments: list[Segment] = []
    meta = analysis.metadata or {}

    date_value = _date_value(analysis, config)
    if date_value:
        segments.append(Segment(date_value, PRIORITY_DATE, droppable=False, kind="datetime"))

    type_value = _value(analysis.document_type)
    if type_value:
        segments.append(Segment(type_value, PRIORITY_TYPE, kind="type"))

    if config.media.include_device and not meta.get("photo_of_document"):
        device = str(meta.get("device") or "")
        if device:
            segments.append(Segment(device, PRIORITY_DEVICE, kind="device"))

    if config.media.include_gps_coordinates:
        gps = str(meta.get("gps_short") or "")
        if gps:
            segments.append(Segment(gps, PRIORITY_ENTITY, kind="gps"))

    duration = str(meta.get("duration_label") or "")
    if duration:
        segments.append(Segment(duration, PRIORITY_ENTITY, kind="duration"))

    subject_value = _value(analysis.subject)
    if subject_value:
        segments.append(Segment(subject_value, PRIORITY_SUBJECT, kind="subject"))

    if (analysis.metadata or {}).get("photo_of_document"):
        # Понятно, что это снимок, а не сам документ.
        segments.append(Segment("фото", PRIORITY_ORIGINAL, kind="media_hint"))
        identifier = _value(analysis.document_number)
        if identifier:
            segments.append(
                Segment(identifier, PRIORITY_IDENTIFIER, droppable=False, kind="identifier")
            )
        entities = _entities_segment(analysis.main_persons, analysis.main_organizations, config)
        if entities:
            segments.append(Segment(entities, PRIORITY_ENTITY, kind="entities"))
        return segments

    original = clean_original_stem(analysis.source_path.stem)
    if original:
        segments.append(Segment(original, PRIORITY_ORIGINAL, kind="original"))
    return segments


def _email_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для писем (раздел 30 ТЗ)."""
    segments: list[Segment] = []
    date_value = _date_value(analysis, config)
    if date_value:
        segments.append(Segment(date_value, PRIORITY_DATE, droppable=False, kind="date"))
    segments.append(Segment("Email", PRIORITY_TYPE, droppable=False, kind="type"))
    entities = _entities_segment(analysis.main_persons, analysis.main_organizations, config)
    if entities:
        segments.append(Segment(entities, PRIORITY_ENTITY, kind="entities"))
    subject_value = _value(analysis.subject)
    if subject_value:
        segments.append(Segment(subject_value, PRIORITY_SUBJECT, kind="subject"))
    return segments


def _archive_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для архивов (раздел 32 ТЗ).

    Архив чаще всего называет человек, и это имя точнее любого списка файлов:
    «иск Шахманова.zip» стоит оставить как есть, добавив, что внутри архив со
    сканами. Полностью строится имя только для технических имён вида
    ``archive (3).zip``.
    """
    metadata = analysis.metadata or {}
    original = clean_original_stem(analysis.source_path.stem)
    if config.naming.preserve_good_names and is_meaningful_stem(analysis.source_path.stem):
        segments = [Segment(original, PRIORITY_TYPE, droppable=False, kind="original_kept")]
        segments.append(Segment("архив", PRIORITY_ENTITY, kind="archive_hint"))
        if _archive_holds_scans(metadata):
            segments.append(Segment("сканы", PRIORITY_ENTITY, kind="archive_hint"))
        count = metadata.get("entry_count")
        if isinstance(count, int) and count > 1:
            segments.append(Segment(f"{count}_файлов", PRIORITY_SUBJECT, kind="count"))
        date_field = analysis.document_date
        if date_field is not None and date_field.source is not Source.FILESYSTEM:
            date_value = _date_value(analysis, config)
            if date_value:
                segments.append(
                    Segment(date_value, PRIORITY_DATE, droppable=False, kind="date")
                )
        return segments

    segments = []
    date_value = _date_value(analysis, config)
    if date_value:
        segments.append(Segment(date_value, PRIORITY_DATE, droppable=False, kind="date"))
    segments.append(Segment("Архив", PRIORITY_TYPE, droppable=False, kind="type"))
    subject_value = _value(analysis.subject)
    if subject_value:
        segments.append(Segment(subject_value, PRIORITY_SUBJECT, kind="subject"))
    entities = _entities_segment(analysis.main_persons, analysis.main_organizations, config)
    if entities:
        segments.append(Segment(entities, PRIORITY_ENTITY, kind="entities"))
    count = (analysis.metadata or {}).get("entry_count")
    if count:
        segments.append(Segment(f"{count}_файлов", PRIORITY_ENTITY, kind="count"))
    return segments


#: Расширения, по которым видно, что в архиве лежат сканы, а не что попало.
SCAN_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf", ".heic", ".bmp"}
)


def _archive_holds_scans(metadata: dict[str, object]) -> bool:
    """Лежат ли в архиве сканы или снимки страниц."""
    extensions = metadata.get("extensions")
    if not isinstance(extensions, dict) or not extensions:
        return False
    total = sum(int(count) for count in extensions.values())
    scans = sum(
        int(count) for suffix, count in extensions.items() if str(suffix).lower() in SCAN_EXTENSIONS
    )
    return total > 0 and scans >= total * 0.8


def _folder_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты имени папки: вид, участники, номер дела, период, число файлов."""
    segments: list[Segment] = []
    metadata = analysis.metadata or {}

    type_value = _value(analysis.document_type)
    if type_value:
        segments.append(Segment(type_value, PRIORITY_TYPE, droppable=False, kind="type"))

    entities = _entities_segment(analysis.main_persons, analysis.main_organizations, config)
    if entities:
        segments.append(Segment(entities, PRIORITY_ENTITY, kind="entities"))

    if analysis.case_numbers:
        identifier = _value(analysis.case_numbers[0])
        if identifier:
            segments.append(
                Segment(identifier, PRIORITY_IDENTIFIER, droppable=False, kind="identifier")
            )

    period = str(metadata.get("period") or "")
    if period:
        segments.append(Segment(period, PRIORITY_DATE, droppable=False, kind="date"))

    count = metadata.get("files_inside")
    if isinstance(count, int) and count > 1:
        segments.append(Segment(f"{count}_файлов", PRIORITY_SUBJECT, kind="count"))
    return segments


def _geodata_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для треков и карт (раздел 24 ТЗ)."""
    segments: list[Segment] = []
    metadata = analysis.metadata or {}

    date_value = _date_value(analysis, config)
    if date_value:
        segments.append(Segment(date_value, PRIORITY_DATE, droppable=False, kind="date"))

    type_value = _value(analysis.document_type)
    if type_value:
        segments.append(Segment(type_value, PRIORITY_TYPE, droppable=False, kind="type"))

    subject_value = _value(analysis.subject)
    if subject_value:
        segments.append(Segment(subject_value, PRIORITY_SUBJECT, kind="subject"))

    length = metadata.get("gpx_length_km")
    if isinstance(length, int | float) and length > 0:
        segments.append(Segment(f"{length:.1f}_км", PRIORITY_ENTITY, kind="duration"))
    points = metadata.get("gpx_points")
    if not length and isinstance(points, int) and points > 0:
        segments.append(Segment(f"{points}_точек", PRIORITY_ENTITY, kind="count"))
    placemarks = metadata.get("kml_placemarks")
    if isinstance(placemarks, int) and placemarks > 0:
        segments.append(Segment(f"{placemarks}_меток", PRIORITY_ENTITY, kind="count"))
    return segments


def _scan_page_segment(analysis: FileAnalysis) -> Segment | None:
    """Номер страницы в пачке сканов."""
    page = (analysis.metadata or {}).get("scan_page")
    if not isinstance(page, dict) or not page.get("segment"):
        return None
    return Segment(str(page["segment"]), PRIORITY_IDENTIFIER, droppable=False, kind="series")


def _series_segment(analysis: FileAnalysis) -> Segment | None:
    """Номер тома или части — он не должен потеряться при переименовании."""
    series = (analysis.metadata or {}).get("series")
    if not isinstance(series, dict) or not series.get("segment"):
        return None
    return Segment(str(series["segment"]), PRIORITY_IDENTIFIER, droppable=False, kind="series")


def build_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Выбрать стратегию сегментов по категории файла."""
    if analysis.category in (Category.IMAGE, Category.VIDEO, Category.AUDIO):
        segments = _media_segments(analysis, config)
    elif analysis.category is Category.EMAIL:
        segments = _email_segments(analysis, config)
    elif analysis.category is Category.ARCHIVE:
        segments = _archive_segments(analysis, config)
    elif analysis.category is Category.FOLDER:
        segments = _folder_segments(analysis, config)
    elif analysis.category is Category.GEODATA:
        segments = _geodata_segments(analysis, config)
    else:
        segments = _document_segments(analysis, config)
    part = _series_segment(analysis) or _scan_page_segment(analysis)
    if part is not None:
        segments.append(part)
    return segments


def _order_segments(segments: list[Segment], config: Config) -> list[Segment]:
    """Расставить сегменты в выбранном порядке.

    Дата — это уточнение, а не название документа, поэтому по умолчанию она
    уходит в конец: первым словом имени становится то, по чему файлы удобно
    искать и сортировать.
    """
    if config.naming.order == "date-first":
        return segments
    dates = [s for s in segments if s.kind in ("date", "datetime")]
    rest = [s for s in segments if s.kind not in ("date", "datetime")]
    # Вид документа — первое слово имени: именно его человек ищет глазами.
    type_kinds = ("type", "type_default", "type_from_name")
    types = [s for s in rest if s.kind in type_kinds]
    # Хвост имени: сначала пометка «фото», затем номер страницы. Так имя
    # начинается с сути, а сортировка по имени идёт по порядку страниц.
    tail_kinds = ("media_hint", "series")
    tail = [s for s in rest if s.kind in tail_kinds]
    others = [s for s in rest if s.kind not in type_kinds and s.kind not in tail_kinds]
    rest = types + others + sorted(tail, key=lambda s: tail_kinds.index(s.kind))
    return rest + dates if rest else segments


def _limit_segments(segments: list[Segment], config: Config) -> list[Segment]:
    """Оставить в имени только самое существенное.

    Длинное имя из семи частей нечитаемо. Ограничение считается по смысловым
    сегментам: дата и номер части сюда не входят, они короткие и всегда
    полезны.
    """
    limit = max(2, config.naming.max_segments)
    core = [
        s for s in segments if s.kind not in ("date", "datetime", "series", "media_hint")
    ]
    if len(core) <= limit:
        return segments
    keep = sorted(
        sorted(core, key=lambda s: -s.priority)[:limit],
        key=core.index,
    )
    return [s for s in segments if s in keep or s.kind in ("date", "datetime", "series")]


def _dedupe_segments(segments: list[Segment]) -> list[Segment]:
    """Убрать сегменты, дублирующие уже включённый по смыслу текст.

    Иначе имя вида ``Постановление__Постановление`` получается из совпадения
    типа документа и его же заголовка в свойствах файла.

    Длинный сегмент, начинающийся с уже сказанного слова, целиком не
    выбрасывается: из «Бюджет проекта Север» при типе «Бюджет» остаётся
    «проекта Север», и имя сохраняет то, чем эта таблица отличается от
    соседних.
    """
    result: list[Segment] = []
    seen: list[str] = []
    for segment in segments:
        key = dedupe_key(segment.text)
        if any(key == other or key in other for other in seen if other):
            continue
        covering = [other for other in seen if other and other in key]
        if covering:
            trimmed = _drop_repeated_words(segment.text, covering)
            trimmed_key = dedupe_key(trimmed)
            if len(trimmed_key) < 3 or any(
                trimmed_key == other or trimmed_key in other for other in seen if other
            ):
                continue
            segment = Segment(
                text=trimmed,
                priority=segment.priority,
                droppable=segment.droppable,
                kind=segment.kind,
            )
            key = trimmed_key
        seen.append(key)
        result.append(segment)
    return result


def _drop_repeated_words(text: str, covered: list[str]) -> str:
    """Убрать из текста слова, уже сказанные другими сегментами."""
    words = []
    for word in re.split(r"[\s_]+", text):
        word_key = dedupe_key(word)
        if not word or (word_key and any(word_key in other for other in covered)):
            continue
        words.append(word)
    return " ".join(words).strip()


def build_filename(analysis: FileAnalysis, config: Config) -> tuple[str, list[str]]:
    """Построить имя файла в два прохода.

    Первый проход собирает имя из найденных фактов. Второй перечитывает
    результат независимыми проверками и либо убирает лишнее, либо отказывается
    от имени: показать прежнее имя честнее, чем неверное новое (раздел 92 ТЗ).

    Returns:
        ``(имя, отброшенные_сегменты)``. Пустое имя означает, что осмысленное
        предложение построить не удалось.
    """
    segments = _dedupe_segments(
        [s for s in build_segments(analysis, config) if sanitize_component(s.text)]
    )
    # Второй проход, шаг первый: убрать сегменты, которым в имени не место.
    segments, issues = review_segments(segments)
    if issues:
        analysis.metadata["name_review"] = [
            {"code": issue.code, "message": issue.message, "value": issue.segment}
            for issue in issues
        ]
    segments = _limit_segments(_order_segments(segments, config), config)
    if not any(segment.kind in INFORMATIVE_KINDS for segment in segments):
        # Предложить нечего. Если человек уже дал имя — оставляем его, добавив
        # разве что дату (раздел 92 ТЗ).
        if config.naming.preserve_good_names and is_meaningful_stem(analysis.source_path.stem):
            return build_preserved_name(analysis, config)
        return "", []

    name, dropped = assemble_filename(
        segments,
        analysis.source_path.suffix,
        separator=config.naming.separator,
        max_length=config.naming.max_filename_length,
    )

    # Второй проход, шаг второй: перечитать готовое имя целиком.
    expected_date = _date_value(analysis, config)
    problems = review_name(
        name,
        max_length=config.naming.max_filename_length,
        expected_date=expected_date.split("_")[0] if expected_date else "",
    )
    if problems:
        analysis.metadata.setdefault("name_review", [])
        analysis.metadata["name_review"] = list(analysis.metadata["name_review"]) + [
            {"code": issue.code, "message": issue.message, "value": issue.segment}
            for issue in problems
        ]
    if is_blocking(problems):
        analysis.add_status(Status.NAME_REVIEW_FAILED)
        return "", dropped
    return name, dropped
