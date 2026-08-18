"""Сборка предложенного имени файла (разделы 27, 43, 44, 45 ТЗ).

Базовая грамматика::

    DATE__TYPE__SUBJECT__ENTITIES__IDENTIFIER.ext

Не все сегменты обязательны. В имя попадают только принятые значения — те, у
которых есть источник и подтверждение (раздел 63 ТЗ).
"""

from __future__ import annotations

import re

from docrenamer.config import Config
from docrenamer.naming.sanitizer import Segment, assemble_filename, sanitize_component
from docrenamer.textquality import comparison_key
from docrenamer.types import Category, EntityRef, Field, FileAnalysis, nfc

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
INFORMATIVE_KINDS: frozenset[str] = frozenset(
    {"type", "identifier", "entities", "subject", "device", "duration", "count", "gps"}
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
        return f"{abbreviation}-{core}"
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
        # «Иванов Иван Иванович» → «Иванов»: остальное хранится в manifest.
        surname = parts[0]
    elif len(parts) == 2 and len(parts[1]) <= 4 and "." in parts[1]:
        initials = initials or parts[1].replace(".", "")
        surname = parts[0]
    if initials:
        return f"{surname}-{initials}"
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

    parts = [
        *unique(orgs, config.naming.max_organizations_in_filename),
        *unique(people, config.naming.max_persons_in_filename),
    ]
    return "--".join(parts)


def _value(field: Field | None) -> str:
    """Значение принятого поля или пустая строка."""
    if field is None or not field.accepted:
        return ""
    return str(field.value)


def _document_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для документов: DATE__TYPE__SUBJECT__ENTITIES__IDENTIFIER."""
    segments: list[Segment] = []
    date_value = _value(analysis.document_date)
    if date_value:
        segments.append(Segment(date_value, PRIORITY_DATE, droppable=False, kind="date"))

    type_value = _value(analysis.document_type)
    if type_value:
        segments.append(Segment(type_value, PRIORITY_TYPE, droppable=False, kind="type"))

    subject_value = _value(analysis.subject)
    if subject_value:
        segments.append(Segment(subject_value, PRIORITY_SUBJECT, kind="subject"))

    entities = _entities_segment(analysis.main_persons, analysis.main_organizations, config)
    if entities:
        segments.append(Segment(entities, PRIORITY_ENTITY, kind="entities"))

    identifier = _value(analysis.document_number)
    if not identifier and analysis.case_numbers:
        identifier = _value(analysis.case_numbers[0])
    if identifier:
        segments.append(
            Segment(identifier, PRIORITY_IDENTIFIER, droppable=False, kind="identifier")
        )
    return segments


def _media_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для фото, видео и аудио (разделы 27, 28, 29 ТЗ)."""
    segments: list[Segment] = []
    meta = analysis.metadata or {}

    date_value = _value(analysis.document_date)
    if date_value:
        segments.append(Segment(date_value, PRIORITY_DATE, droppable=False, kind="datetime"))

    if config.media.include_device:
        device = str(meta.get("device") or "")
        if device:
            segments.append(Segment(device, PRIORITY_DEVICE, kind="device"))

    if config.media.include_gps_coordinates:
        gps = str(meta.get("gps_short") or "")
        if gps:
            segments.append(Segment(gps, PRIORITY_ENTITY, kind="gps"))

    type_value = _value(analysis.document_type)
    if type_value:
        segments.append(Segment(type_value, PRIORITY_TYPE, kind="type"))

    duration = str(meta.get("duration_label") or "")
    if duration:
        segments.append(Segment(duration, PRIORITY_ENTITY, kind="duration"))

    subject_value = _value(analysis.subject)
    if subject_value:
        segments.append(Segment(subject_value, PRIORITY_SUBJECT, kind="subject"))

    original = analysis.source_path.stem
    if original:
        segments.append(Segment(original, PRIORITY_ORIGINAL, kind="original"))
    return segments


def _email_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для писем (раздел 30 ТЗ)."""
    segments: list[Segment] = []
    date_value = _value(analysis.document_date)
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
    """Сегменты для архивов (раздел 32 ТЗ)."""
    segments: list[Segment] = []
    date_value = _value(analysis.document_date)
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
        segments.append(Segment(f"{count}-файлов", PRIORITY_ENTITY, kind="count"))
    return segments


def _geodata_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Сегменты для треков и карт (раздел 24 ТЗ)."""
    segments: list[Segment] = []
    metadata = analysis.metadata or {}

    date_value = _value(analysis.document_date)
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
        segments.append(Segment(f"{length:.1f}-км", PRIORITY_ENTITY, kind="duration"))
    points = metadata.get("gpx_points")
    if not length and isinstance(points, int) and points > 0:
        segments.append(Segment(f"{points}-точек", PRIORITY_ENTITY, kind="count"))
    placemarks = metadata.get("kml_placemarks")
    if isinstance(placemarks, int) and placemarks > 0:
        segments.append(Segment(f"{placemarks}-меток", PRIORITY_ENTITY, kind="count"))
    return segments


def build_segments(analysis: FileAnalysis, config: Config) -> list[Segment]:
    """Выбрать стратегию сегментов по категории файла."""
    if analysis.category in (Category.IMAGE, Category.VIDEO, Category.AUDIO):
        return _media_segments(analysis, config)
    if analysis.category is Category.EMAIL:
        return _email_segments(analysis, config)
    if analysis.category is Category.ARCHIVE:
        return _archive_segments(analysis, config)
    if analysis.category is Category.GEODATA:
        return _geodata_segments(analysis, config)
    return _document_segments(analysis, config)


def _dedupe_segments(segments: list[Segment]) -> list[Segment]:
    """Убрать сегменты, дублирующие уже включённый по смыслу текст.

    Иначе имя вида ``Постановление__Постановление`` получается из совпадения
    типа документа и его же заголовка в свойствах файла.
    """
    result: list[Segment] = []
    seen: list[str] = []
    for segment in segments:
        key = comparison_key(segment.text)
        if any(key == other or key in other or other in key for other in seen if other):
            continue
        seen.append(key)
        result.append(segment)
    return result


def build_filename(analysis: FileAnalysis, config: Config) -> tuple[str, list[str]]:
    """Построить имя файла.

    Returns:
        ``(имя, отброшенные_сегменты)``. Пустое имя означает, что осмысленное
        предложение построить не удалось.
    """
    segments = _dedupe_segments(
        [s for s in build_segments(analysis, config) if sanitize_component(s.text)]
    )
    if not segments:
        return "", []

    if not any(segment.kind in INFORMATIVE_KINDS for segment in segments):
        # Остались только дата и исходное имя — это не улучшение, а маскировка
        # того, что о файле ничего не известно.
        return "", []

    name, dropped = assemble_filename(
        segments,
        analysis.source_path.suffix,
        separator=config.naming.separator,
        max_length=config.naming.max_filename_length,
    )
    return name, dropped
