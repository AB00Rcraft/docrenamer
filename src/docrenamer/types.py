"""Базовые типы данных и единый словарь кодов состояния (разделы 14, 53, 63 ТЗ).

Модуль не должен импортировать ничего из проекта, кроме стандартной библиотеки:
он лежит в основании графа зависимостей.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class Status(StrEnum):
    """Единый словарь кодов (раздел 53 ТЗ).

    Значения намеренно совпадают с именами: коды попадают в логи и manifest
    как машинно-читаемые строки.
    """

    OK = "OK"
    RENAMED = "RENAMED"
    SKIPPED = "SKIPPED"
    SKIPPED_LOW_CONFIDENCE = "SKIPPED_LOW_CONFIDENCE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    READ_ERROR = "READ_ERROR"
    ACCESS_DENIED = "ACCESS_DENIED"
    FILE_LOCKED = "FILE_LOCKED"
    PASSWORD_PROTECTED = "PASSWORD_PROTECTED"  # noqa: S105 — код состояния, не пароль
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    OCR_FAILED = "OCR_FAILED"
    OCR_ENGINE_NOT_FOUND = "OCR_ENGINE_NOT_FOUND"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_FAILED = "MODEL_FAILED"
    INVALID_AI_JSON = "INVALID_AI_JSON"
    AI_EVIDENCE_REJECTED = "AI_EVIDENCE_REJECTED"
    EXTENSION_MISMATCH = "EXTENSION_MISMATCH"
    NAME_COLLISION_RESOLVED = "NAME_COLLISION_RESOLVED"
    SOURCE_CHANGED_AFTER_PREVIEW = "SOURCE_CHANGED_AFTER_PREVIEW"
    HASH_ERROR = "HASH_ERROR"
    CRITICAL_HASH_MISMATCH = "CRITICAL_HASH_MISMATCH"
    UNDO_TARGET_EXISTS = "UNDO_TARGET_EXISTS"
    PATH_TOO_LONG = "PATH_TOO_LONG"
    UNSAFE_PATH = "UNSAFE_PATH"

    # Диагностические коды русского профиля и дополнительные предупреждения
    # (разделы 14A, 15.1, 65, 66, 67 ТЗ). Не являются ошибками сами по себе.
    ENCODING_UNCERTAIN = "ENCODING_UNCERTAIN"
    MOJIBAKE_SUSPECTED = "MOJIBAKE_SUSPECTED"
    MIXED_ALPHABET_SUSPECTED = "MIXED_ALPHABET_SUSPECTED"
    PDF_TEXT_LAYER_LOW_QUALITY = "PDF_TEXT_LAYER_LOW_QUALITY"
    PDF_OCR_FALLBACK_USED = "PDF_OCR_FALLBACK_USED"
    PARTIAL_SUPPORT_LEGACY_OFFICE = "PARTIAL_SUPPORT_LEGACY_OFFICE"
    DUPLICATE_CONTENT = "DUPLICATE_CONTENT"
    SIDECAR_DETECTED = "SIDECAR_DETECTED"
    LIVE_PHOTO_PAIR_DETECTED = "LIVE_PHOTO_PAIR_DETECTED"
    DATE_SOURCE_FILESYSTEM = "DATE_SOURCE_FILESYSTEM"
    DATE_SOURCE_FILE_PROPERTY = "DATE_SOURCE_FILE_PROPERTY"
    NO_NAME_PROPOSED = "NO_NAME_PROPOSED"
    NAME_UNCHANGED = "NAME_UNCHANGED"
    ORIGINAL_NAME_PRESERVED = "ORIGINAL_NAME_PRESERVED"
    GOOD_NAME_KEPT = "GOOD_NAME_KEPT"
    NAME_REVIEW_FAILED = "NAME_REVIEW_FAILED"
    SERIES_PART_DETECTED = "SERIES_PART_DETECTED"
    AI_DISABLED = "AI_DISABLED"
    AI_NOT_NEEDED = "AI_NOT_NEEDED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


#: Человекочитаемые описания кодов на русском (раздел 14A.7 ТЗ).
STATUS_DESCRIPTIONS_RU: dict[str, str] = {
    Status.OK: "Успешно.",
    Status.RENAMED: "Файл переименован.",
    Status.SKIPPED: "Файл пропущен.",
    Status.SKIPPED_LOW_CONFIDENCE: "Пропущен: недостаточная уверенность в имени.",
    Status.UNSUPPORTED_FORMAT: "Формат не поддерживается.",
    Status.PARTIAL_SUPPORT: "Формат поддерживается частично.",
    Status.READ_ERROR: "Не удалось прочитать файл.",
    Status.ACCESS_DENIED: "Нет доступа к файлу.",
    Status.FILE_LOCKED: "Файл занят другим процессом.",
    Status.PASSWORD_PROTECTED: "Файл защищён паролем.",
    Status.EMPTY_DOCUMENT: "Документ не содержит извлекаемого текста.",
    Status.OCR_FAILED: "Не удалось выполнить распознавание текста.",
    Status.OCR_ENGINE_NOT_FOUND: "Локальный OCR не найден. Загрузка из сети не выполняется.",
    Status.MODEL_NOT_FOUND: "Локальная модель не найдена. Загрузка из сети не выполняется.",
    Status.MODEL_FAILED: "Локальная модель завершилась с ошибкой.",
    Status.INVALID_AI_JSON: "Модель вернула некорректный JSON.",
    Status.AI_EVIDENCE_REJECTED: "Значение отклонено: нет подтверждения в исходном тексте.",
    Status.EXTENSION_MISMATCH: "Расширение не соответствует реальному типу файла.",
    Status.NAME_COLLISION_RESOLVED: "Имя было занято, добавлен числовой суффикс.",
    Status.SOURCE_CHANGED_AFTER_PREVIEW: "Файл изменился после предпросмотра, пропущен.",
    Status.HASH_ERROR: "Не удалось вычислить контрольную сумму.",
    Status.CRITICAL_HASH_MISMATCH: "КРИТИЧНО: контрольная сумма изменилась.",
    Status.UNDO_TARGET_EXISTS: "Откат невозможен: исходное имя занято.",
    Status.PATH_TOO_LONG: "Слишком длинный путь.",
    Status.UNSAFE_PATH: "Небезопасный путь.",
    Status.ENCODING_UNCERTAIN: "Не удалось надёжно определить кодировку текста.",
    Status.MOJIBAKE_SUSPECTED: "Похоже на неверно декодированный текст («кракозябры»).",
    Status.MIXED_ALPHABET_SUSPECTED: "Смешаны кириллица и латиница в одном слове.",
    Status.PDF_TEXT_LAYER_LOW_QUALITY: "Текстовый слой PDF низкого качества.",
    Status.PDF_OCR_FALLBACK_USED: "Использовано распознавание вместо текстового слоя PDF.",
    Status.PARTIAL_SUPPORT_LEGACY_OFFICE: (
        "Старый формат Office: доступны только свойства документа."
    ),
    Status.DUPLICATE_CONTENT: "Обнаружен файл с идентичным содержимым.",
    Status.SIDECAR_DETECTED: "Обнаружен связанный служебный файл — нужна ручная проверка.",
    Status.LIVE_PHOTO_PAIR_DETECTED: "Обнаружена пара Live Photo — нужна ручная проверка.",
    Status.DATE_SOURCE_FILESYSTEM: "Дата взята из файловой системы, а не из документа.",
    Status.DATE_SOURCE_FILE_PROPERTY: (
        "Дата взята из свойств файла, а не из текста документа."
    ),
    Status.NO_NAME_PROPOSED: "Не удалось предложить осмысленное имя.",
    Status.NAME_UNCHANGED: "Предложенное имя совпадает с текущим.",
    Status.ORIGINAL_NAME_PRESERVED: (
        "Имя уже осмысленное — оно сохранено, добавлена только дата."
    ),
    Status.NAME_REVIEW_FAILED: (
        "Построенное имя не прошло самопроверку — файл оставлен как есть."
    ),
    Status.GOOD_NAME_KEPT: (
        "Имя уже хорошее. Вариант предложен, но по умолчанию файл не "
        "переименовывается — отметьте его, если вариант нравится больше."
    ),
    Status.SERIES_PART_DETECTED: (
        "Файл распознан как часть многотомного документа; номер части сохранён."
    ),
    Status.AI_DISABLED: "Локальный ИИ отключён в настройках.",
    Status.AI_NOT_NEEDED: "Локальный ИИ не понадобился.",
    Status.LIMIT_EXCEEDED: "Превышен лимит обработки, данные усечены.",
}


def describe(code: str | Status) -> str:
    """Русское описание кода состояния."""
    key = code.value if isinstance(code, Status) else str(code)
    return STATUS_DESCRIPTIONS_RU.get(key, key)


class Category(StrEnum):
    """Крупная категория файла — определяет ветку pipeline."""

    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    EMAIL = "email"
    ARCHIVE = "archive"
    GEODATA = "geodata"
    DATA = "data"
    FOLDER = "folder"
    OTHER = "other"


class Source(StrEnum):
    """Происхождение значения. Раздел 63 ТЗ."""

    TEXT = "text"
    METADATA = "metadata"
    REGEX = "regex"
    LLM = "llm"
    FILENAME = "filename"
    FILESYSTEM = "filesystem"


@dataclass(frozen=True, slots=True)
class Field:
    """Значение с обязательным происхождением и подтверждением.

    Раздел 63 ТЗ: каждое существенное поле несёт source/evidence/confidence.
    Значение без evidence не может попасть в имя файла (раздел 37).
    """

    value: Any
    source: Source
    evidence: str = ""
    confidence: float = 0.0

    @property
    def accepted(self) -> bool:
        """Пригодно ли значение для использования в имени файла."""
        if self.value in (None, "", [], {}):
            return False
        if self.source is Source.LLM and not self.evidence:
            return False
        return self.confidence > 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source.value,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 4),
        }


@dataclass(slots=True)
class EntityRef:
    """Лицо или организация с ролью в документе (разделы 42, 43 ТЗ)."""

    name: str
    role: str = ""
    confidence: float = 0.0
    evidence: str = ""
    source: Source = Source.TEXT
    normalized: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
            "source": self.source.value,
            "normalized": self.normalized,
        }


@dataclass(slots=True)
class Candidate:
    """Кандидат, найденный детерминированным extractor (раздел 40 ТЗ)."""

    value: str
    position: int = -1
    context: str = ""
    source: Source = Source.REGEX
    role_guess: str = ""
    confidence: float = 0.0
    kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "position": self.position,
            "context": self.context,
            "source": self.source.value,
            "role_guess": self.role_guess,
            "confidence": round(self.confidence, 4),
            "kind": self.kind,
        }


@dataclass(slots=True)
class ReadResult:
    """Результат работы reader (раздел 14A.1 ТЗ).

    После стадии декодирования между модулями передаётся только Unicode ``str``.
    """

    text: str = ""
    text_language_hint: str = ""
    source_encoding: str = ""
    encoding_confidence: float = 0.0
    text_quality: float = 0.0
    decoding_warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    statuses: list[str] = field(default_factory=list)
    truncated: bool = False
    page_count: int = 0

    def add_status(self, code: str | Status) -> None:
        value = code.value if isinstance(code, Status) else str(code)
        if value not in self.statuses:
            self.statuses.append(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_length": len(self.text),
            "text_language_hint": self.text_language_hint,
            "source_encoding": self.source_encoding,
            "encoding_confidence": round(self.encoding_confidence, 4),
            "text_quality": round(self.text_quality, 4),
            "decoding_warnings": list(self.decoding_warnings),
            "metadata": self.metadata,
            "statuses": list(self.statuses),
            "truncated": self.truncated,
            "page_count": self.page_count,
        }


@dataclass(slots=True)
class ScannedFile:
    """Файл, найденный сканером (раздел 9 ТЗ)."""

    path: Path
    size: int
    mtime: float
    extension: str

    @property
    def name(self) -> str:
        return self.path.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "size": self.size,
            "mtime": self.mtime,
            "extension": self.extension,
        }


@dataclass(slots=True)
class FileAnalysis:
    """Единая модель анализа файла (раздел 14 ТЗ)."""

    source_path: Path
    detected_type: str = ""
    category: Category = Category.OTHER
    document_type: Field | None = None
    document_date: Field | None = None
    document_number: Field | None = None
    case_numbers: list[Field] = field(default_factory=list)
    main_persons: list[EntityRef] = field(default_factory=list)
    main_organizations: list[EntityRef] = field(default_factory=list)
    subject: Field | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    read_result: ReadResult | None = None
    overall_confidence: float = 0.0
    proposed_filename: str = ""
    statuses: list[str] = field(default_factory=list)
    error: str = ""

    def add_status(self, code: str | Status) -> None:
        value = code.value if isinstance(code, Status) else str(code)
        if value not in self.statuses:
            self.statuses.append(value)

    def has_status(self, code: str | Status) -> bool:
        value = code.value if isinstance(code, Status) else str(code)
        return value in self.statuses

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "detected_type": self.detected_type,
            "category": self.category.value,
            "document_type": self.document_type.to_dict() if self.document_type else None,
            "document_date": self.document_date.to_dict() if self.document_date else None,
            "document_number": self.document_number.to_dict() if self.document_number else None,
            "case_numbers": [f.to_dict() for f in self.case_numbers],
            "main_persons": [p.to_dict() for p in self.main_persons],
            "main_organizations": [o.to_dict() for o in self.main_organizations],
            "subject": self.subject.to_dict() if self.subject else None,
            "metadata": self.metadata,
            "evidence": self.evidence,
            "candidates": {k: [c.to_dict() for c in v] for k, v in self.candidates.items()},
            "read": self.read_result.to_dict() if self.read_result else None,
            "overall_confidence": round(self.overall_confidence, 4),
            "proposed_filename": self.proposed_filename,
            "statuses": list(self.statuses),
            "error": self.error,
        }


@dataclass(slots=True)
class PlanItem:
    """Строка плана переименования (разделы 48, 49 ТЗ).

    Хранит SHA-256, size и mtime для повторной проверки перед APPLY (TOCTOU).
    """

    source_path: Path
    target_path: Path
    proposed_filename: str
    sha256: str
    size: int
    mtime: float
    confidence: float
    analysis: FileAnalysis | None = None
    statuses: list[str] = field(default_factory=list)
    selected: bool = True
    status: str = Status.OK.value
    message: str = ""
    #: «file» или «folder».
    kind: str = "file"

    @property
    def is_folder(self) -> bool:
        """Строка плана описывает папку, а не файл."""
        return self.kind == "folder"

    @property
    def is_rename(self) -> bool:
        """Действительно ли элемент меняет имя файла."""
        return self.source_path.name != self.target_path.name

    def add_status(self, code: str | Status) -> None:
        value = code.value if isinstance(code, Status) else str(code)
        if value not in self.statuses:
            self.statuses.append(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_path": str(self.source_path),
            "target_path": str(self.target_path),
            "original_filename": self.source_path.name,
            "proposed_filename": self.proposed_filename,
            "sha256": self.sha256,
            "size": self.size,
            "mtime": self.mtime,
            "confidence": round(self.confidence, 4),
            "statuses": list(self.statuses),
            "selected": self.selected,
            "status": self.status,
            "message": self.message,
            "analysis": self.analysis.to_dict() if self.analysis else None,
        }


@dataclass(slots=True)
class RenameRecord:
    """Запись о выполненной операции для manifest и undo (раздел 51 ТЗ)."""

    source_path: Path
    target_path: Path
    original_filename: str
    new_filename: str
    sha256_before: str
    sha256_after: str
    size: int
    mtime: float
    detected_type: str
    confidence: float
    status: str
    timestamp: str
    message: str = ""
    #: «file» или «folder». Папка не имеет контрольной суммы, и откат для неё
    #: проверяется иначе.
    kind: str = "file"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_path": str(self.source_path),
            "target_path": str(self.target_path),
            "original_filename": self.original_filename,
            "new_filename": self.new_filename,
            "sha256_before": self.sha256_before,
            "sha256_after": self.sha256_after,
            "size": self.size,
            "mtime": self.mtime,
            "detected_type": self.detected_type,
            "confidence": round(self.confidence, 4),
            "status": self.status,
            "timestamp": self.timestamp,
            "message": self.message,
        }


def nfc(value: str) -> str:
    """Unicode normalization NFC (раздел 14A.4 ТЗ).

    NFKC намеренно не используется: он разрушает «№», типографские кавычки и
    другие значимые для русских документов символы.
    """
    return unicodedata.normalize("NFC", value)


def utcstamp() -> str:
    """Локальная временная метка в ISO-формате для логов и manifest."""
    return datetime.now().astimezone().isoformat(timespec="seconds")
