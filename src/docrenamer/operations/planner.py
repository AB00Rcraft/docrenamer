"""Построение плана переименования (разделы 46, 47, 49, 66, 67, 68, 79 ТЗ).

План — это то, что пользователь видит в предпросмотре и что затем исполняет
APPLY. Он самодостаточен: хранит SHA-256, size и mtime каждого файла, поэтому
перед мутацией можно повторно убедиться, что источник не изменился.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docrenamer.config import Config, write_json_atomic
from docrenamer.naming.collision import fold, resolve_collision
from docrenamer.operations.hashing import HashError, sha256_file
from docrenamer.types import FileAnalysis, PlanItem, Status, utcstamp

PLAN_FORMAT_VERSION = 1

#: Расширения sidecar-файлов, которые нельзя переименовывать независимо
#: от основного файла (раздел 67 ТЗ).
SIDECAR_EXTENSIONS = frozenset({".aae", ".xmp", ".thm", ".lrv", ".pp3", ".dop"})

#: Пары, образующие Live Photo (раздел 68 ТЗ).
LIVE_PHOTO_IMAGE = frozenset({".heic", ".heif", ".jpg", ".jpeg"})
LIVE_PHOTO_VIDEO = frozenset({".mov", ".mp4"})


@dataclass(slots=True)
class RenamePlan:
    """План переименования каталога."""

    root: Path
    items: list[PlanItem] = field(default_factory=list)
    created_at: str = ""
    config_fingerprint: str = ""
    app_version: str = ""
    recursive: bool = True

    @property
    def selected_items(self) -> list[PlanItem]:
        """Строки, реально подлежащие исполнению."""
        return [item for item in self.items if item.selected and item.is_rename]

    def counters(self) -> dict[str, int]:
        low = sum(1 for i in self.items if i.status == Status.SKIPPED_LOW_CONFIDENCE.value)
        errors = sum(
            1
            for i in self.items
            if i.status
            in (
                Status.READ_ERROR.value,
                Status.ACCESS_DENIED.value,
                Status.UNSUPPORTED_FORMAT.value,
                Status.HASH_ERROR.value,
            )
        )
        return {
            "Найдено": len(self.items),
            "Предлагается переименовать": len(self.selected_items),
            "Низкая уверенность": low,
            "Ошибок": errors,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_format_version": PLAN_FORMAT_VERSION,
            "root": str(self.root),
            "created_at": self.created_at or utcstamp(),
            "config_fingerprint": self.config_fingerprint,
            "app_version": self.app_version,
            "recursive": self.recursive,
            "counters": self.counters(),
            "items": [item.to_dict() for item in self.items],
        }

    def save(self, path: Path) -> Path:
        """Сохранить ``rename_plan.json`` (раздел 49 ТЗ)."""
        write_json_atomic(Path(path), self.to_dict())
        return Path(path)


def load_plan(path: Path) -> dict[str, Any]:
    """Прочитать сохранённый план."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _related_groups(analyses: list[FileAnalysis]) -> dict[Path, set[str]]:
    """Сгруппировать файлы по «основе» имени внутри каталога.

    Возвращает отображение ``каталог/основа`` → множество расширений.
    """
    groups: dict[Path, set[str]] = {}
    for analysis in analyses:
        path = analysis.source_path
        key = path.parent / path.stem.lower()
        groups.setdefault(key, set()).add(path.suffix.lower())
    return groups


def _mark_related(analysis: FileAnalysis, groups: dict[Path, set[str]]) -> str:
    """Пометить sidecar и Live Photo (разделы 67, 68 ТЗ).

    Возвращает код состояния или пустую строку.
    """
    path = analysis.source_path
    extensions = groups.get(path.parent / path.stem.lower(), set())
    own = path.suffix.lower()

    if own in SIDECAR_EXTENSIONS:
        return Status.SIDECAR_DETECTED.value
    if extensions & SIDECAR_EXTENSIONS:
        return Status.SIDECAR_DETECTED.value
    has_image = bool(extensions & LIVE_PHOTO_IMAGE)
    has_video = bool(extensions & LIVE_PHOTO_VIDEO)
    if has_image and has_video:
        return Status.LIVE_PHOTO_PAIR_DETECTED.value
    return ""


def build_folder_items(
    folders: Iterable[FileAnalysis],
    *,
    config: Config,
    taken_by_directory: dict[Path, set[str]] | None = None,
) -> list[PlanItem]:
    """Строки плана для папок.

    Папки идут после файлов: если сначала переименовать папку, пути файлов
    внутри неё станут недействительными, а откат — ненадёжным.
    """
    taken = taken_by_directory if taken_by_directory is not None else {}
    items: list[PlanItem] = []
    threshold = config.naming.confidence_threshold

    for analysis in folders:
        folder = analysis.source_path
        proposed = analysis.proposed_filename.strip()
        item = PlanItem(
            source_path=folder,
            target_path=folder,
            proposed_filename=proposed or folder.name,
            sha256="",
            size=0,
            mtime=0.0,
            confidence=analysis.overall_confidence,
            analysis=analysis,
            statuses=list(analysis.statuses),
            selected=False,
            status=Status.SKIPPED.value,
            kind="folder",
        )
        if not proposed:
            item.status = Status.NO_NAME_PROPOSED.value
            item.message = "Содержимое папки не даёт названия."
            items.append(item)
            continue

        directory_taken = taken.setdefault(folder.parent, set())
        target, collided = resolve_collision(
            folder.parent / proposed,
            taken=directory_taken,
            source=folder,
            separator=config.naming.separator,
            max_length=config.naming.max_filename_length,
        )
        item.target_path = target
        item.proposed_filename = target.name
        if collided:
            item.add_status(Status.NAME_COLLISION_RESOLVED.value)
        if target.name == folder.name:
            item.status = Status.NAME_UNCHANGED.value
            item.message = "Имя папки уже соответствует предложенному."
        elif analysis.overall_confidence < threshold:
            item.status = Status.SKIPPED_LOW_CONFIDENCE.value
            item.message = (
                f"Уверенность {analysis.overall_confidence:.2f} ниже порога "
                f"{threshold:.2f} — папка автоматически не переименовывается."
            )
        else:
            item.status = Status.OK.value
            item.selected = True
        directory_taken.add(fold(target.name))
        items.append(item)
    return items


def build_plan(
    analyses: Iterable[FileAnalysis],
    *,
    config: Config,
    root: Path,
    app_version: str = "",
    progress: Callable[[int, int], None] | None = None,
) -> RenamePlan:
    """Построить план по результатам анализа.

    Правила:

    * файл без предложенного имени в план на исполнение не попадает;
    * уверенность ниже порога — строка показывается, но не выбрана
      (раздел 46 ТЗ);
    * занятое имя получает числовой суффикс (раздел 47 ТЗ);
    * sidecar и Live Photo помечаются для ручной проверки (разделы 67, 68 ТЗ);
    * одинаковое содержимое помечается как ``DUPLICATE_CONTENT`` без каких-либо
      действий с дубликатами (раздел 66 ТЗ).
    """
    items_input = list(analyses)
    plan = RenamePlan(
        root=Path(root),
        created_at=utcstamp(),
        config_fingerprint=config.fingerprint(),
        app_version=app_version,
        recursive=config.recursive,
    )
    groups = _related_groups(items_input)
    taken_by_directory: dict[Path, set[str]] = {}
    seen_hashes: dict[str, Path] = {}
    threshold = config.naming.confidence_threshold
    total = len(items_input)

    for index, analysis in enumerate(items_input, start=1):
        if progress:
            progress(index, total)
        source = analysis.source_path
        try:
            stat = source.stat()
        except OSError as exc:
            plan.items.append(
                PlanItem(
                    source_path=source,
                    target_path=source,
                    proposed_filename=source.name,
                    sha256="",
                    size=0,
                    mtime=0.0,
                    confidence=0.0,
                    analysis=analysis,
                    selected=False,
                    status=Status.READ_ERROR.value,
                    message=f"Нет доступа к файлу: {exc}",
                )
            )
            continue

        try:
            digest = sha256_file(source)
        except HashError as exc:
            plan.items.append(
                PlanItem(
                    source_path=source,
                    target_path=source,
                    proposed_filename=source.name,
                    sha256="",
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    confidence=0.0,
                    analysis=analysis,
                    selected=False,
                    status=Status.HASH_ERROR.value,
                    message=str(exc),
                )
            )
            continue

        statuses = list(analysis.statuses)
        proposed = analysis.proposed_filename.strip()
        confidence = analysis.overall_confidence
        directory = source.parent
        taken = taken_by_directory.setdefault(directory, set())

        item = PlanItem(
            source_path=source,
            target_path=source,
            proposed_filename=proposed or source.name,
            sha256=digest,
            size=stat.st_size,
            mtime=stat.st_mtime,
            confidence=confidence,
            analysis=analysis,
            statuses=statuses,
            selected=False,
            status=Status.SKIPPED.value,
        )

        duplicate_of = seen_hashes.get(digest)
        if duplicate_of is not None:
            item.add_status(Status.DUPLICATE_CONTENT.value)
            item.message = f"Идентичное содержимое: {duplicate_of.name}"
        else:
            seen_hashes[digest] = source

        related = _mark_related(analysis, groups)
        if related:
            item.add_status(related)

        if not proposed:
            if analysis.has_status(Status.NAME_UNCHANGED):
                item.status = Status.NAME_UNCHANGED.value
                item.message = item.message or (
                    "Имя уже хорошее — предложить лучше нечего."
                    if analysis.has_status(Status.GOOD_NAME_KEPT)
                    else "Имя уже соответствует предложенному."
                )
            else:
                item.status = Status.NO_NAME_PROPOSED.value
                item.message = item.message or "Не удалось предложить осмысленное имя."
            plan.items.append(item)
            taken.add(fold(source.name))
            continue

        target, collided = resolve_collision(
            directory / proposed,
            taken=taken,
            source=source,
            separator=config.naming.separator,
            max_length=config.naming.max_filename_length,
        )
        item.target_path = target
        item.proposed_filename = target.name
        if collided:
            item.add_status(Status.NAME_COLLISION_RESOLVED.value)

        if target.name == source.name:
            item.status = Status.NAME_UNCHANGED.value
            item.message = "Имя уже соответствует предложенному."
        elif related:
            item.status = related
            item.message = "Связанные файлы переименовываются только вручную."
        elif analysis.has_status(Status.GOOD_NAME_KEPT):
            item.status = Status.GOOD_NAME_KEPT.value
            item.message = (
                "Имя уже хорошее. Вариант предложен — отметьте, если он нравится больше."
            )
        elif confidence < threshold:
            item.status = Status.SKIPPED_LOW_CONFIDENCE.value
            item.message = (
                f"Уверенность {confidence:.2f} ниже порога {threshold:.2f} — "
                "автоматически не переименовывается."
            )
        else:
            item.status = Status.OK.value
            item.selected = True

        taken.add(fold(target.name))
        plan.items.append(item)

    return plan


def verify_plan_item(item: PlanItem) -> tuple[bool, str, str]:
    """Повторная проверка строки плана перед APPLY (раздел 49 ТЗ)."""
    source = item.source_path
    if item.is_folder:
        # У папки нет содержимого для сверки, а время изменения меняется от
        # переименования файлов внутри. Проверяем, что она на месте.
        if not source.is_dir():
            return False, Status.SOURCE_CHANGED_AFTER_PREVIEW.value, "Папка не найдена."
        return True, Status.OK.value, ""
    try:
        stat = source.stat()
    except OSError as exc:
        return False, Status.SOURCE_CHANGED_AFTER_PREVIEW.value, f"Файл недоступен: {exc}"
    if stat.st_size != item.size:
        return (
            False,
            Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
            "Размер файла изменился после предпросмотра.",
        )
    if abs(stat.st_mtime - item.mtime) > 1.0:
        return (
            False,
            Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
            "Время изменения файла отличается от зафиксированного в плане.",
        )
    return True, Status.OK.value, ""
