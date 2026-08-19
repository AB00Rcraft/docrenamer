"""Конвейер анализа файла (разделы 13, 14, 46, 64 ТЗ).

Порядок «от дешёвого к дорогому» (раздел 64 ТЗ)::

    metadata → детерминированные правила → reader → OCR → локальная LLM

Локальная LLM запускается последней и только тогда, когда без неё имя собрать
не удаётся.
"""

from __future__ import annotations

import re
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
from docrenamer.extractors.series import detect_series
from docrenamer.file_signature import check_extension, detect_type
from docrenamer.naming.builder import build_filename, is_well_formed_name
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

#: Нейтральное обозначение по виду файла. Используется, когда вид документа
#: определить не удалось: это честная характеристика файла, а не догадка о его
#: юридическом смысле.
FILE_KIND_LABELS: dict[str, str] = {
    "pptx": "Презентация",
    "ppt": "Презентация",
    "xlsx": "Таблица",
    "xlsm": "Таблица",
    "xls": "Таблица",
    "csv": "Таблица",
}

#: Если вид документа определить не удалось, имя всё равно начинается с
#: обозначения вида: первое слово имени — это то, что человек ищет глазами.
DEFAULT_DOCUMENT_LABEL = "Документ"


class Analyzer(Protocol):
    """Контракт анализатора для :class:`docrenamer.app.Application`."""

    def analyze(self, scanned: ScannedFile) -> FileAnalysis:
        """Проанализировать один файл."""
        ...

    def model_info(self) -> dict[str, Any]:
        """Сведения о локальной модели для manifest."""
        ...

    def postprocess(self, analyses: list[FileAnalysis]) -> None:
        """Уточнения, которые видны только на уровне всего каталога."""
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

    def postprocess(self, analyses: list[FileAnalysis]) -> None:
        """Уточнения, которые видны только на уровне всего каталога.

        Сейчас это многотомные документы: «Дело 1», «Дело 2» — части одного
        целого. Номер части обязан сохраниться в новом имени, иначе порядок
        томов теряется, а разрешение коллизий выдаёт их за случайно совпавшие
        файлы.
        """
        series = detect_series([a.source_path for a in analyses])
        if not series:
            return
        by_path = {a.source_path: a for a in analyses}

        groups: dict[tuple[Any, str, str], list[Path]] = {}
        for path, info in series.items():
            key = (path.parent, info.base.casefold(), path.suffix.lower())
            groups.setdefault(key, []).append(path)

        for members in groups.values():
            ordered = sorted(members, key=lambda p: series[p].part)
            self._share_series_facts([by_path[p] for p in ordered if p in by_path], series)

        for path, info in series.items():
            analysis = by_path.get(path)
            if analysis is None:
                continue
            analysis.metadata["series"] = info.to_dict()
            analysis.add_status(Status.SERIES_PART_DETECTED)
            self.finalize(analysis)

    def _share_series_facts(
        self, group: list[FileAnalysis], series: dict[Path, Any]
    ) -> None:
        """Дополнить тома недостающими реквизитами из соседних томов.

        Второй том часто идёт без шапки: даты и номера дела в нём просто нет.
        Значение берётся у соседа явно — с указанием файла-источника и с
        пониженной уверенностью, чтобы происхождение факта не терялось
        (раздел 63 ТЗ).
        """
        if len(group) < 2:
            return
        def is_own_fact(field_value: Field | None) -> bool:
            """Установлен ли факт по самому документу, а не по файловой системе."""
            if field_value is None or not field_value.accepted:
                return False
            return field_value.source not in (Source.FILESYSTEM,)

        for attribute in ("document_date", "document_type", "document_number"):
            donor: FileAnalysis | None = None
            for analysis in group:
                field_value = getattr(analysis, attribute)
                if not is_own_fact(field_value):
                    continue
                current: Field | None = getattr(donor, attribute) if donor else None
                if current is None or field_value.confidence > current.confidence:
                    donor = analysis
            if donor is None:
                continue
            source_field: Field = getattr(donor, attribute)
            for analysis in group:
                if analysis is donor:
                    continue
                if is_own_fact(getattr(analysis, attribute)):
                    continue
                setattr(
                    analysis,
                    attribute,
                    Field(
                        value=source_field.value,
                        source=source_field.source,
                        evidence=f"из файла «{donor.source_path.name}»: {source_field.evidence}",
                        confidence=round(source_field.confidence * 0.85, 4),
                    ),
                )

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
            if best_type.context.startswith("имя файла"):
                # Название вида взято из самого имени файла: форму имени оно
                # задаёт, но нового о документе не сообщает.
                analysis.metadata["document_type_from_filename"] = True
        else:
            # Вид документа не подтверждён. Лучше назвать файл нейтрально по
            # его формату, чем присвоить ему чужой юридический ярлык
            # (раздел 92 ТЗ).
            label = FILE_KIND_LABELS.get(analysis.detected_type, DEFAULT_DOCUMENT_LABEL)
            if label == DEFAULT_DOCUMENT_LABEL:
                # Обозначение «Документ» держит форму имени, но само по себе
                # ничего не сообщает: переименовывать файл только ради него
                # не за чем.
                analysis.metadata["document_type_default"] = True
            analysis.document_type = Field(
                value=label,
                source=Source.METADATA,
                evidence=f"формат файла: {analysis.detected_type}",
                # Вид файла определён по сигнатуре — это факт, а не догадка
                # о юридическом смысле документа.
                confidence=0.95 if label != DEFAULT_DOCUMENT_LABEL else 0.8,
            )

        # Имя файла — тоже источник сведений: в нём часто есть номер дела и
        # дата, особенно если файл выгружен из системы делопроизводства.
        date_candidates = extract_dates(text)
        for candidate in extract_dates(filename):
            candidate.source = Source.FILENAME
            candidate.context = f"имя файла: {filename}"
            candidate.confidence = min(candidate.confidence, 0.88)
            if all(existing.value != candidate.value for existing in date_candidates):
                date_candidates.append(candidate)
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
        for kind, values in extract_identifiers(filename).items():
            known = {c.value for c in identifiers.get(kind, [])}
            for candidate in values:
                if candidate.value in known:
                    continue
                candidate.source = Source.FILENAME
                candidate.context = f"имя файла: {filename}"
                identifiers.setdefault(kind, []).append(candidate)
        for kind, values in identifiers.items():
            analysis.candidates[kind] = values[:5]
        main_identifier = select_identifier(identifiers)
        if main_identifier is not None:
            analysis.document_number = Field(
                value=main_identifier.value,
                # Источник сохраняется: номер из имени файла и номер из текста
                # документа — разное знание.
                source=main_identifier.source,
                evidence=main_identifier.context,
                confidence=main_identifier.confidence,
            )
        analysis.case_numbers = [
            Field(
                value=c.value,
                source=c.source,
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

        analysis.metadata["known_type_words"] = [
            entry.canonical_name for entry in self.type_matcher.entries
        ]
        subject = self._subject_for_document(analysis, text)
        if subject is None:
            subject = self._subject_from_filename(analysis)
        if subject is not None:
            analysis.subject = subject
        self._collect_evidence(analysis)

    def _enrich_media(self, analysis: FileAnalysis, text: str) -> None:
        """Фото, видео и аудио: стратегия metadata-first (разделы 27–29 ТЗ)."""
        metadata = analysis.metadata
        stamp = str(metadata.get("datetime") or "")
        if stamp:
            analysis.document_date = Field(
                value=_media_stamp(stamp, with_time=self.config.naming.include_capture_time),
                source=Source.METADATA,
                evidence=f"{metadata.get('datetime_source', 'metadata')}={stamp}",
                confidence=0.97,
            )
        elif self.config.naming.allow_filesystem_date_fallback:
            # Время оставляем: за один день снимков бывает много, и без времени
            # они сливаются в одинаковые имена. Источник времени честно помечен
            # как файловая система (раздел 65 ТЗ).
            fallback = self._filesystem_date(
                analysis, with_time=self.config.naming.include_capture_time
            )
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
        if label and device_known and self.config.naming.order == "date-first":
            # При сортировке по дате подпись категории избыточна: модель камеры
            # и так говорит, что это снимок. При сортировке по названию она,
            # наоборот, собирает все фотографии рядом.
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
            moment.strftime("%Y-%m-%d_%H.%M.%S") if with_time else moment.strftime("%Y-%m-%d")
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
        if not title:
            # У презентации осмысленное название чаще всего на первом слайде.
            slide_titles = metadata.get("slide_titles") or []
            if isinstance(slide_titles, list) and slide_titles:
                title = str(slide_titles[0]).strip()
        if (
            title
            and 3 <= len(title) <= 80
            and title.lower() not in ("документ", "document")
            and not self._document_title_is_type(analysis)
        ):
            return Field(
                value=title,
                source=Source.METADATA,
                evidence=f"название документа: {title}",
                confidence=0.9,
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

    def _subject_from_filename(self, analysis: FileAnalysis) -> Field | None:
        """Использовать слова старого имени как предмет документа.

        Пометка вроде «седой дом газ» несёт смысл, которого нет ни в тексте,
        ни в реквизитах: адрес, о чём справка. Терять её при переименовании
        нельзя, даже если само имя переписывается.
        """
        from docrenamer.naming.builder import clean_original_stem, is_meaningful_stem

        # Слова прежнего имени идут в дело, только если документ действительно
        # прочитан: у нечитаемого файла собственное имя ничего не подтверждает,
        # и переименовывать его не за чем (раздел 92 ТЗ).
        has_facts = (
            analysis.document_type is not None and analysis.document_type.accepted
        ) or bool(analysis.case_numbers) or (
            analysis.document_number is not None and analysis.document_number.accepted
        )
        if not has_facts:
            return None

        stem = analysis.source_path.stem
        if not is_meaningful_stem(stem):
            return None
        cleaned = clean_original_stem(self._strip_known_values(analysis, stem))
        if not cleaned or len(cleaned) < 4:
            return None
        return Field(
            value=cleaned[:60],
            source=Source.FILENAME,
            evidence=f"слова из прежнего имени файла: {stem}",
            confidence=0.8,
        )

    def _strip_known_values(self, analysis: FileAnalysis, stem: str) -> str:
        """Убрать из прежнего имени то, что уже попадёт в новое.

        Если в имени написано «Дело 33-52030_224 определение суда апелляционной
        инстанции», то и номер дела, и вид документа программа уже извлекла.
        Повторять их ещё раз в виде текста незачем.
        """
        text = stem
        values: list[str] = []
        if analysis.document_number is not None and analysis.document_number.accepted:
            values.append(str(analysis.document_number.value))
        values.extend(str(field.value) for field in analysis.case_numbers)
        canonical = str(analysis.metadata.get("document_type_canonical") or "")
        if canonical:
            values.append(canonical)
            values.extend(word for word in canonical.split() if len(word) > 4)
        for value in values:
            if not value:
                continue
            text = re.sub(re.escape(value), " ", text, flags=re.IGNORECASE)
        # Служебные слова, которые сами по себе ничего не сообщают.
        text = re.sub(r"\b(дело|дела|копия|скан|документ)\b", " ", text, flags=re.IGNORECASE)
        return text

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
        stem = analysis.source_path.stem
        type_words = frozenset(
            comparison_key(str(value))
            for value in (analysis.metadata or {}).get("known_type_words", [])
        )
        if self.config.naming.preserve_good_names and is_well_formed_name(stem, type_words):
            # Имя уже хорошее: вариант всё равно предложим, но отмечать его
            # галочкой не будем — решение за человеком.
            analysis.add_status(Status.GOOD_NAME_KEPT)
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


def _media_stamp(iso_value: str, *, with_time: bool = True) -> str:
    """Дата и время съёмки для имени файла.

    Время указывается только для снимков, видео и записей: за один день их
    бывает много, и время их различает. Для остальных файлов такая точность
    не нужна. Записывается через точку, как и дата, чтобы единственным
    разделителем частей имени оставалось подчёркивание.
    """
    value = iso_value.strip().replace("T", " ")
    date_part, _, time_part = value.partition(" ")
    if not time_part or not with_time:
        return date_part
    return f"{date_part}_{time_part[:8].replace(':', '.')}"


def _person_from_address(raw: str) -> str:
    """Извлечь отображаемое имя из адреса электронной почты."""
    value = raw.strip()
    if "<" in value:
        value = value.split("<", 1)[0].strip().strip('"')
    if not value or "@" in value:
        value = raw.split("@", 1)[0].strip().strip("<\"'")
    return value[:60]


def media_confidence(analysis: FileAnalysis) -> float:
    """Уверенность для фото, видео и аудио.

    Имя медиафайла строится не из смысла текста, а из проверяемых фактов: вид
    файла определён по сигнатуре, устройство и время съёмки взяты из
    метаданных. Здесь нечего «угадать неверно», поэтому общая формула, которая
    штрафует за отсутствие текстовых реквизитов, для медиа не подходит.

    Время файловой системы понижает оценку, но не делает имя непригодным: оно
    честно помечено в manifest (разделы 41, 65 ТЗ).
    """
    date = analysis.document_date
    if date is None or not date.accepted:
        return 0.4
    if date.source is Source.FILESYSTEM:
        score = 0.9
    else:
        score = 0.97
    if analysis.metadata.get("device"):
        score = min(0.99, score + 0.02)
    if analysis.has_status(Status.MOJIBAKE_SUSPECTED):
        score *= 0.6
    return round(score, 4)


def compute_confidence(analysis: FileAnalysis) -> float:
    """Итоговая уверенность (раздел 46 ТЗ).

    Складывается из уверенности типа, даты, идентификатора, участников и
    предмета с учётом надёжности источника. Самооценка LLM отдельно не
    используется как единственный критерий.
    """
    if analysis.category in (Category.IMAGE, Category.VIDEO, Category.AUDIO) and not (
        analysis.subject is not None and analysis.subject.accepted
    ):
        return media_confidence(analysis)

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
    # Дата из свойств файла в имя не попадает (см. naming/builder), поэтому и
    # уверенность в имени она снижать не должна.
    date_in_name = not analysis.has_status(Status.DATE_SOURCE_FILE_PROPERTY)
    if analysis.document_date is not None and analysis.document_date.accepted and date_in_name:
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
        # Название, которое автор написал сам, весит больше, чем предмет,
        # выведенный из текста.
        weight = 2.0 if analysis.subject.source is Source.METADATA else 1.0
        add(analysis.subject.confidence, weight, source=analysis.subject.source)

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
