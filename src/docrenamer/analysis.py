"""Конвейер анализа файла (разделы 13, 14, 46, 64 ТЗ).

Порядок «от дешёвого к дорогому» (раздел 64 ТЗ)::

    metadata → детерминированные правила → reader → OCR → локальная LLM

Локальная LLM запускается последней и только тогда, когда без неё имя собрать
не удаётся.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from docrenamer.config import Config, load_document_types
from docrenamer.extractors.amounts import extract_amounts
from docrenamer.extractors.dates import extract_dates, select_document_date
from docrenamer.extractors.document_types import DocumentTypeMatcher, select_document_type
from docrenamer.extractors.identifiers import (
    extract_identifiers,
    select_case_numbers,
    select_identifier,
)
from docrenamer.extractors.organizations import extract_organizations, select_organizations
from docrenamer.extractors.persons import extract_persons, select_persons
from docrenamer.file_signature import check_extension, detect_type
from docrenamer.naming.builder import build_filename
from docrenamer.paths import AppPaths, default_paths
from docrenamer.security.limits import Limits
from docrenamer.security.temp_cleanup import SessionTemp
from docrenamer.textquality import comparison_key
from docrenamer.types import (
    Candidate,
    Category,
    EntityRef,
    Field,
    FileAnalysis,
    ReadResult,
    ScannedFile,
    Source,
    Status,
)

#: Названия категорий для сегмента типа в имени файла.
CATEGORY_LABELS: dict[Category, str] = {
    Category.IMAGE: "Фото",
    Category.VIDEO: "Видео",
    Category.AUDIO: "Аудиозапись",
}


class Analyzer(Protocol):
    """Контракт анализатора для :class:`docrenamer.app.Application`."""

    def analyze(self, scanned: ScannedFile) -> FileAnalysis:
        """Проанализировать один файл."""
        ...

    def model_info(self) -> dict[str, Any]:
        """Сведения о локальной модели для manifest."""
        ...


@dataclass(slots=True)
class ReaderContext:
    """Всё, что нужно reader'у, кроме самого файла."""

    config: Config
    paths: AppPaths
    limits: Limits
    temp: SessionTemp | None = None
    extras: dict[str, Any] = field(default_factory=dict)


#: Тип reader-функции: путь + контекст → результат чтения.
ReaderFunc = Any


class Pipeline:
    """Полный конвейер анализа."""

    def __init__(
        self,
        config: Config,
        paths: AppPaths | None = None,
        *,
        temp: SessionTemp | None = None,
        readers: dict[str, ReaderFunc] | None = None,
    ) -> None:
        self.config = config
        self.paths = paths or default_paths()
        self.limits = Limits.from_config(config)
        self.context = ReaderContext(
            config=config, paths=self.paths, limits=self.limits, temp=temp
        )
        self.readers: dict[str, ReaderFunc] = readers if readers is not None else {}
        try:
            entries = load_document_types(paths=self.paths)
        except Exception:  # словарь типов не должен ломать запуск
            entries = []
        self.type_matcher = DocumentTypeMatcher(entries)
        self.ai: Any = None

    # --- вспомогательное ---------------------------------------------------

    def reader_for(self, kind: str, category: Category) -> ReaderFunc | None:
        """Подобрать reader по типу, затем по категории."""
        reader = self.readers.get(kind)
        if reader is not None:
            return reader
        return self.readers.get(f"category:{category.value}")

    def model_info(self) -> dict[str, Any]:
        """Сведения о локальной модели (раздел 51 ТЗ)."""
        if self.ai is None:
            return {
                "enabled": self.config.ai.enabled,
                "available": False,
                "engine": "",
                "model_id": "",
            }
        info = self.ai.model_info().to_dict()
        info["enabled"] = self.config.ai.enabled
        return info

    # --- основной метод ----------------------------------------------------

    def analyze(self, scanned: ScannedFile) -> FileAnalysis:
        """Проанализировать файл и предложить имя."""
        path = Path(scanned.path)
        analysis = FileAnalysis(source_path=path)

        detected = detect_type(path)
        analysis.detected_type = detected.kind or path.suffix.lstrip(".").lower()
        analysis.category = detected.category
        analysis.metadata["detection"] = {
            "kind": detected.kind,
            "confidence": detected.confidence,
            "method": detected.method,
            "detail": detected.detail,
        }
        mismatch = check_extension(path, detected)
        if mismatch:
            analysis.add_status(mismatch)

        if scanned.size > self.limits.max_single_file_bytes:
            analysis.add_status(Status.LIMIT_EXCEEDED)
            analysis.error = "Файл превышает допустимый размер обработки."
            return analysis

        reader = self.reader_for(analysis.detected_type, analysis.category)
        if reader is None:
            analysis.add_status(Status.UNSUPPORTED_FORMAT)
        else:
            try:
                result = reader(path, self.context)
            except PermissionError:
                analysis.add_status(Status.ACCESS_DENIED)
                result = None
            except (OSError, ValueError, RuntimeError) as exc:
                analysis.add_status(Status.READ_ERROR)
                analysis.error = str(exc)
                result = None
            if isinstance(result, ReadResult):
                analysis.read_result = result
                for code in result.statuses:
                    analysis.add_status(code)
                if result.metadata:
                    analysis.metadata.update(result.metadata)

        self.enrich(analysis)
        self.finalize(analysis)
        return analysis

    # --- расширяемые этапы -------------------------------------------------

    def enrich(self, analysis: FileAnalysis) -> None:
        """Детерминированные extractors, затем — при необходимости — локальная LLM.

        Порядок раздела 64 ТЗ: сначала метаданные и правила, и только если
        уверенности не хватает, вызывается локальная модель.
        """
        text = analysis.read_result.text if analysis.read_result else ""
        if analysis.category in (Category.IMAGE, Category.VIDEO, Category.AUDIO):
            self._enrich_media(analysis, text)
        elif analysis.category is Category.EMAIL:
            self._enrich_email(analysis, text)
        elif analysis.category is Category.ARCHIVE:
            self._enrich_archive(analysis)
        elif analysis.category is Category.GEODATA:
            self._enrich_geodata(analysis)
        else:
            self._enrich_document(analysis, text)

        self._apply_ai(analysis, text)

    # --- ветви по категориям ----------------------------------------------

    def _enrich_document(self, analysis: FileAnalysis, text: str) -> None:
        """Документы: тип, дата, номера, участники, предмет."""
        filename = analysis.source_path.name

        type_candidates = self.type_matcher.match(text, filename=filename)
        analysis.candidates["document_type"] = type_candidates[:5]
        best_type = select_document_type(type_candidates)
        if best_type is not None:
            analysis.document_type = Field(
                value=self.type_matcher.abbreviation_for(best_type.value),
                source=Source.TEXT,
                evidence=best_type.context,
                confidence=best_type.confidence,
            )
            analysis.metadata["document_type_canonical"] = best_type.value

        date_candidates = extract_dates(text)
        analysis.candidates["dates"] = date_candidates[:10]
        # Приоритет раздела 41 ТЗ. Свойство «created» у DOCX/XLSX/PPTX — это
        # дата создания файла, а не дата документа: у шаблонов Office она
        # фиктивна (2013 год). Поэтому она приравнена к запасному источнику и
        # никогда не перебивает дату, найденную в самом тексте.
        best_date = select_document_date(date_candidates)
        if best_date is None and self.config.naming.allow_filesystem_date_fallback:
            best_date = self._file_property_date(analysis)
        if best_date is None and self.config.naming.allow_filesystem_date_fallback:
            best_date = self._filesystem_date(analysis)
        if best_date is not None:
            analysis.document_date = Field(
                value=best_date.value,
                source=best_date.source,
                evidence=best_date.context,
                confidence=best_date.confidence,
            )

        identifiers = extract_identifiers(text)
        for kind, values in identifiers.items():
            analysis.candidates[kind] = values[:5]
        main_identifier = select_identifier(identifiers)
        if main_identifier is not None:
            analysis.document_number = Field(
                value=main_identifier.value,
                source=Source.REGEX,
                evidence=main_identifier.context,
                confidence=main_identifier.confidence,
            )
        analysis.case_numbers = [
            Field(
                value=c.value,
                source=Source.REGEX,
                evidence=c.context,
                confidence=c.confidence,
            )
            for c in select_case_numbers(identifiers)
        ]

        person_candidates = extract_persons(text)
        organization_candidates = extract_organizations(text)
        analysis.candidates["persons"] = person_candidates[:10]
        analysis.candidates["organizations"] = organization_candidates[:10]
        analysis.main_persons = select_persons(
            person_candidates, self.config.naming.max_persons_in_filename
        )
        analysis.main_organizations = select_organizations(
            organization_candidates, self.config.naming.max_organizations_in_filename
        )

        amounts = extract_amounts(text)
        if amounts:
            analysis.candidates["amounts"] = amounts[:5]

        subject = self._subject_for_document(analysis, text)
        if subject is not None:
            analysis.subject = subject
        self._collect_evidence(analysis)

    def _enrich_media(self, analysis: FileAnalysis, text: str) -> None:
        """Фото, видео и аудио: стратегия metadata-first (разделы 27–29 ТЗ)."""
        metadata = analysis.metadata
        stamp = str(metadata.get("datetime") or "")
        if stamp:
            analysis.document_date = Field(
                value=_media_stamp(stamp),
                source=Source.METADATA,
                evidence=f"{metadata.get('datetime_source', 'metadata')}={stamp}",
                confidence=0.97,
            )
        elif self.config.naming.allow_filesystem_date_fallback:
            fallback = self._filesystem_date(analysis, with_time=True)
            if fallback is not None:
                analysis.document_date = Field(
                    value=fallback.value,
                    source=Source.FILESYSTEM,
                    evidence=fallback.context,
                    confidence=fallback.confidence,
                )

        label = CATEGORY_LABELS.get(analysis.category, "")
        document_text = text.strip()
        if analysis.category is Category.IMAGE and document_text:
            # Снимок документа: тип определяется по фактически распознанному
            # тексту, а не выдумывается (раздел 27 ТЗ).
            type_candidates = self.type_matcher.match(document_text)
            analysis.candidates["document_type"] = type_candidates[:5]
            best_type = select_document_type(type_candidates)
            if best_type is not None and best_type.confidence >= 0.75:
                analysis.document_type = Field(
                    value="Фото-документа",
                    source=Source.TEXT,
                    evidence=best_type.context,
                    confidence=min(0.9, best_type.confidence),
                )
                analysis.subject = Field(
                    value=self.type_matcher.abbreviation_for(best_type.value),
                    source=Source.TEXT,
                    evidence=best_type.context,
                    confidence=best_type.confidence,
                )
                organizations = extract_organizations(document_text)
                analysis.main_organizations = select_organizations(
                    organizations, self.config.naming.max_organizations_in_filename
                )
                label = ""
        # «Фото»/«Видео» добавляется, только когда устройство неизвестно: при
        # наличии модели камеры подпись категории избыточна (примеры разделов
        # 27–29 ТЗ).
        device_known = bool(metadata.get("device")) and self.config.media.include_device
        if label and device_known:
            label = ""
        if label and analysis.document_type is None:
            analysis.document_type = Field(
                value=label,
                source=Source.METADATA,
                evidence=f"category={analysis.category.value}",
                confidence=0.9,
            )
        self._collect_evidence(analysis)

    def _enrich_email(self, analysis: FileAnalysis, text: str) -> None:
        """Письма: дата, тема и корреспонденты (разделы 30, 31 ТЗ)."""
        metadata = analysis.metadata
        date_value = str(metadata.get("date") or "")
        if date_value:
            analysis.document_date = Field(
                value=date_value,
                source=Source.METADATA,
                evidence=str(metadata.get("date_raw", "")),
                confidence=0.97,
            )
        subject = str(metadata.get("subject") or "").strip()
        if subject:
            analysis.subject = Field(
                value=subject[:80],
                source=Source.METADATA,
                evidence=f"Subject: {subject}",
                confidence=0.95,
            )
        people: list[EntityRef] = []
        for key, role in (("from", "автор"), ("to", "адресат")):
            raw = str(metadata.get(key) or "").strip()
            if not raw:
                continue
            display = _person_from_address(raw)
            if display:
                people.append(
                    EntityRef(
                        name=display,
                        role=role,
                        confidence=0.9,
                        evidence=raw,
                        source=Source.METADATA,
                    )
                )
        analysis.main_persons = people[: self.config.naming.max_persons_in_filename]
        organizations = extract_organizations(text)
        analysis.main_organizations = select_organizations(
            organizations, self.config.naming.max_organizations_in_filename
        )
        self._collect_evidence(analysis)

    def _enrich_geodata(self, analysis: FileAnalysis) -> None:
        """Треки и карты: дата и название берутся из самих геоданных (раздел 24 ТЗ)."""
        metadata = analysis.metadata
        is_track = bool(metadata.get("gpx_points"))
        label = "Трек" if is_track else "Карта"
        analysis.document_type = Field(
            value=label,
            source=Source.METADATA,
            evidence=f"xml_root={metadata.get('xml_root', '')}",
            confidence=0.92,
        )

        stamp = str(metadata.get("gpx_start_time") or "")
        if not stamp:
            timestamps = metadata.get("kml_timestamps") or []
            stamp = str(timestamps[0]) if timestamps else ""
        if len(stamp) >= 10 and stamp[:4].isdigit():
            analysis.document_date = Field(
                value=stamp[:10],
                source=Source.METADATA,
                evidence=f"время первой точки: {stamp}",
                confidence=0.95,
            )
        elif self.config.naming.allow_filesystem_date_fallback:
            fallback = self._filesystem_date(analysis)
            if fallback is not None:
                analysis.document_date = Field(
                    value=fallback.value,
                    source=Source.FILESYSTEM,
                    evidence=fallback.context,
                    confidence=fallback.confidence,
                )

        name = str(metadata.get("gpx_name") or metadata.get("kml_name") or "").strip()
        if name:
            analysis.subject = Field(
                value=name[:60],
                source=Source.METADATA,
                evidence=f"название в файле: {name}",
                confidence=0.93,
            )
        self._collect_evidence(analysis)

    def _enrich_archive(self, analysis: FileAnalysis) -> None:
        """Архивы: имя строится по списку содержимого (раздел 32 ТЗ)."""
        metadata = analysis.metadata
        if self.config.naming.allow_filesystem_date_fallback:
            fallback = self._filesystem_date(analysis)
            if fallback is not None:
                analysis.document_date = Field(
                    value=fallback.value,
                    source=Source.FILESYSTEM,
                    evidence=fallback.context,
                    confidence=fallback.confidence,
                )
        theme = str(metadata.get("archive_theme") or "")
        if theme:
            analysis.subject = Field(
                value=theme,
                source=Source.METADATA,
                evidence=f"общая тема элементов архива: {theme}",
                confidence=0.8,
            )
        self._collect_evidence(analysis)

    # --- вспомогательное ---------------------------------------------------

    def _file_property_date(self, analysis: FileAnalysis) -> Candidate | None:
        """Дата из свойств документа — запасной источник (раздел 41 ТЗ).

        Обязательно помечается ``DATE_SOURCE_FILE_PROPERTY``: свойство
        «created» описывает файл, а не событие, которому посвящён документ.
        """
        metadata = analysis.metadata
        for key in ("created", "date"):
            raw = str(metadata.get(key) or "")
            if len(raw) >= 10 and raw[:4].isdigit() and raw[4] == "-":
                analysis.add_status(Status.DATE_SOURCE_FILE_PROPERTY)
                return Candidate(
                    value=raw[:10],
                    position=-1,
                    context=f"свойство документа {key}={raw}",
                    source=Source.METADATA,
                    role_guess="file_property",
                    confidence=0.55,
                    kind="file_property",
                )
        return None

    def _document_title_is_type(self, analysis: FileAnalysis) -> bool:
        """Совпадает ли заголовок из свойств файла с определённым типом."""
        title = comparison_key(str(analysis.metadata.get("title") or ""))
        canonical = comparison_key(str(analysis.metadata.get("document_type_canonical") or ""))
        return bool(title) and bool(canonical) and (title in canonical or canonical in title)

    def _filesystem_date(
        self, analysis: FileAnalysis, *, with_time: bool = False
    ) -> Candidate | None:
        """Дата из файловой системы — только как запасной вариант.

        Обязательно помечается ``DATE_SOURCE_FILESYSTEM``: выдавать mtime за
        установленную дату документа запрещено (разделы 41, 65 ТЗ).
        """
        try:
            stat = analysis.source_path.stat()
        except OSError:
            return None
        from datetime import datetime

        moment = datetime.fromtimestamp(stat.st_mtime)
        value = (
            moment.strftime("%Y-%m-%d_%H-%M-%S") if with_time else moment.strftime("%Y-%m-%d")
        )
        analysis.add_status(Status.DATE_SOURCE_FILESYSTEM)
        return Candidate(
            value=value,
            position=-1,
            context="filesystem mtime",
            source=Source.FILESYSTEM,
            role_guess="fallback_date",
            confidence=0.5,
            kind="filesystem",
        )

    def _subject_for_document(self, analysis: FileAnalysis, text: str) -> Field | None:
        """Краткий предмет документа на основе проверяемых признаков."""
        metadata = analysis.metadata
        title = str(metadata.get("title") or "").strip()
        if (
            title
            and 3 <= len(title) <= 80
            and title.lower() not in ("документ", "document")
            and not self._document_title_is_type(analysis)
        ):
            return Field(
                value=title,
                source=Source.METADATA,
                evidence=f"свойство документа title={title}",
                confidence=0.85,
            )
        lowered = text.lower()
        for phrase in (
            "исполнительное производство",
            "исполнительного производства",
            "уголовное дело",
            "административное правонарушение",
            "взыскание задолженности",
            "договор займа",
            "договор поставки",
            "договор аренды",
            "договор подряда",
            "купли-продажи",
        ):
            index = lowered.find(phrase)
            if index >= 0:
                from docrenamer.extractors.common import context_window

                return Field(
                    value=phrase,
                    source=Source.TEXT,
                    evidence=context_window(text, index, index + len(phrase)),
                    confidence=0.85,
                )
        return None

    def _collect_evidence(self, analysis: FileAnalysis) -> None:
        """Сохранить подтверждения принятых значений (раздел 63 ТЗ)."""
        evidence: list[dict[str, Any]] = []
        for name, field_value in (
            ("document_type", analysis.document_type),
            ("document_date", analysis.document_date),
            ("document_number", analysis.document_number),
            ("subject", analysis.subject),
        ):
            if field_value is not None and field_value.accepted:
                evidence.append({"field": name, **field_value.to_dict()})
        for person in analysis.main_persons:
            evidence.append({"field": "person", **person.to_dict()})
        for organization in analysis.main_organizations:
            evidence.append({"field": "organization", **organization.to_dict()})
        analysis.evidence = evidence

    def _apply_ai(self, analysis: FileAnalysis, text: str) -> None:
        """Локальная модель вызывается последней и только при необходимости."""
        if self.ai is None:
            analysis.add_status(
                Status.AI_DISABLED if not self.config.ai.enabled else Status.AI_NOT_NEEDED
            )
            return
        self.ai.enrich(analysis, text)

    def finalize(self, analysis: FileAnalysis) -> None:
        """Построить имя и итоговую уверенность (разделы 44, 46 ТЗ)."""
        analysis.overall_confidence = compute_confidence(analysis)
        name, dropped = build_filename(analysis, self.config)
        if dropped:
            analysis.metadata["dropped_segments"] = dropped
        if name and name != analysis.source_path.name:
            analysis.proposed_filename = name
        else:
            analysis.proposed_filename = ""
            if not name:
                analysis.add_status(Status.NO_NAME_PROPOSED)
            else:
                analysis.add_status(Status.NAME_UNCHANGED)


def _media_stamp(iso_value: str) -> str:
    """Преобразовать ISO-метку в формат имени файла ``2026-08-03_18-42-17``."""
    value = iso_value.strip().replace("T", " ")
    date_part, _, time_part = value.partition(" ")
    if not time_part:
        return date_part
    return f"{date_part}_{time_part[:8].replace(':', '-')}"


def _person_from_address(raw: str) -> str:
    """Извлечь отображаемое имя из адреса электронной почты."""
    value = raw.strip()
    if "<" in value:
        value = value.split("<", 1)[0].strip().strip('"')
    if not value or "@" in value:
        value = raw.split("@", 1)[0].strip().strip("<\"'")
    return value[:60]


def compute_confidence(analysis: FileAnalysis) -> float:
    """Итоговая уверенность (раздел 46 ТЗ).

    Складывается из уверенности типа, даты, идентификатора, участников и
    предмета с учётом надёжности источника. Самооценка LLM отдельно не
    используется как единственный критерий.
    """
    weights: list[tuple[float, float]] = []

    def add(value: float | None, weight: float, *, source: Source | None = None) -> None:
        if value is None:
            return
        reliability = 1.0
        if source is Source.LLM:
            reliability = 0.9
        elif source is Source.FILESYSTEM:
            reliability = 0.5
        weights.append((min(1.0, max(0.0, value)) * reliability, weight))

    if analysis.document_type is not None and analysis.document_type.accepted:
        add(analysis.document_type.confidence, 3.0, source=analysis.document_type.source)
    if analysis.document_date is not None and analysis.document_date.accepted:
        add(analysis.document_date.confidence, 3.0, source=analysis.document_date.source)
    if analysis.document_number is not None and analysis.document_number.accepted:
        add(analysis.document_number.confidence, 2.0, source=analysis.document_number.source)
    if analysis.case_numbers:
        best = max(analysis.case_numbers, key=lambda f: f.confidence)
        add(best.confidence, 2.0, source=best.source)
    if analysis.main_persons:
        add(max(p.confidence for p in analysis.main_persons), 1.0)
    if analysis.main_organizations:
        add(max(o.confidence for o in analysis.main_organizations), 1.0)
    if analysis.subject is not None and analysis.subject.accepted:
        add(analysis.subject.confidence, 1.0, source=analysis.subject.source)

    if not weights:
        return 0.0

    total_weight = sum(weight for _, weight in weights)
    score = sum(value * weight for value, weight in weights) / total_weight

    # Штрафы за диагностические состояния.
    if analysis.has_status(Status.ENCODING_UNCERTAIN):
        score *= 0.8
    if analysis.has_status(Status.MOJIBAKE_SUSPECTED):
        score *= 0.6
    if analysis.has_status(Status.PDF_TEXT_LAYER_LOW_QUALITY):
        score *= 0.9
    if analysis.has_status(Status.DATE_SOURCE_FILESYSTEM):
        score *= 0.85
    if analysis.has_status(Status.DATE_SOURCE_FILE_PROPERTY):
        score *= 0.9
    if analysis.has_status(Status.PARTIAL_SUPPORT_LEGACY_OFFICE):
        score *= 0.9
    return round(min(1.0, max(0.0, score)), 4)


def build_analyzer(
    config: Config,
    paths: AppPaths | None = None,
    *,
    temp: SessionTemp | None = None,
) -> Analyzer:
    """Собрать конвейер анализа со всеми доступными компонентами.

    Порядок раздела 64 ТЗ соблюдается за счёт того, что дорогие backend'ы
    (OCR, локальная LLM) вызываются только при необходимости.
    """
    from docrenamer.ai.enricher import AIEnricher
    from docrenamer.ai.llama_cli import build_model
    from docrenamer.metadata.exiftool import ExifToolBackend
    from docrenamer.metadata.ffprobe import FFprobeBackend
    from docrenamer.metadata.mp4_atoms import Mp4Backend
    from docrenamer.metadata.pillow_exif import PillowExifBackend
    from docrenamer.ocr.engine import build_ocr_engine
    from docrenamer.readers import build_reader_registry

    pipeline = Pipeline(config, paths, temp=temp)
    pipeline.readers = build_reader_registry(pipeline.context)

    allow_system = config.allow_system_binaries
    timeout = config.limits.subprocess_timeout_seconds
    if config.media.use_exif:
        backend = ExifToolBackend(pipeline.paths, timeout=timeout, allow_system=allow_system)
        # Без ExifTool у фотографий не было бы даты съёмки, поэтому включается
        # запасной разбор средствами Pillow.
        pipeline.context.extras["exiftool"] = (
            backend if backend.available else PillowExifBackend()
        )
    if config.media.use_ffprobe:
        probe = FFprobeBackend(pipeline.paths, timeout=timeout, allow_system=allow_system)
        # Аналогично для видео: контейнер MP4/MOV читается своими силами.
        pipeline.context.extras["ffprobe"] = probe if probe.available else Mp4Backend()
    engine = build_ocr_engine(config, pipeline.paths, temp=temp)
    if engine is not None and engine.available:
        pipeline.context.extras["ocr"] = engine

    model = build_model(config, pipeline.paths)
    if model is not None:
        pipeline.ai = AIEnricher(model, config, pipeline.limits)
    return pipeline
