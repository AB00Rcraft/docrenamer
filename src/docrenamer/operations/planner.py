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
from docrenamer.history import RenameHistory
from docrenamer.naming.collision import fold, resolve_collision
from docrenamer.naming.sanitizer import (
    normalize_extension,
    sanitize_component,
    sanitize_filename,
)
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
    threshold = config.naming.folder_confidence_threshold

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


@dataclass
class PlanState:
    """Память между пачками плана.

    План строится частями, чтобы человек видел имена, не дожидаясь конца
    работы на всей папке. Но занятость имён и одинаковое содержимое —
    свойства папки целиком, а не отдельной пачки: без общей памяти вторая
    пачка предложила бы имя, уже занятое первой, а дубликат остался бы
    незамеченным.
    """

    #: Занятые имена по каталогам (в свёрнутом регистре).
    taken_by_directory: dict[Path, set[str]] = field(default_factory=dict)
    #: Контрольная сумма → первый файл с таким содержимым.
    seen_hashes: dict[str, Path] = field(default_factory=dict)


def build_plan(
    analyses: Iterable[FileAnalysis],
    *,
    config: Config,
    root: Path,
    app_version: str = "",
    progress: Callable[[int, int], None] | None = None,
    history: RenameHistory | None = None,
    state: PlanState | None = None,
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
    state = state if state is not None else PlanState()
    taken_by_directory = state.taken_by_directory
    seen_hashes = state.seen_hashes
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

        renamed_on = ""
        if history is not None:
            renamed_on = history.renamed_on(source.name, digest)
        if renamed_on and config.naming.skip_already_renamed:
            # Человек попросил показывать только новое: разобранный прежде
            # файл в план не попадает вовсе.
            continue
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

        if renamed_on:
            item.add_status(Status.ALREADY_RENAMED.value)
            item.message = f"Уже переименован программой ({renamed_on})."

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
            if analysis.has_status(Status.TECHNICAL_FILE):
                # Имя служебного файла — часть работы системы или программы.
                # Строку показываем, но ни отметки, ни предложения у неё нет.
                item.status = Status.TECHNICAL_FILE.value
                reason = str((analysis.metadata or {}).get("technical_reason") or "")
                item.message = (
                    f"Служебный файл ({reason}) — программа его не трогает."
                    if reason
                    else "Служебный файл — программа его не трогает."
                )
            elif analysis.has_status(Status.NAME_UNCHANGED):
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
        elif renamed_on:
            # Имя этому файлу уже давала эта же программа: показываем, но не
            # отмечаем — иначе повторный запуск гоняет папку по кругу.
            item.status = Status.ALREADY_RENAMED.value
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


def set_manual_name(plan: RenamePlan, item: PlanItem, name: str) -> tuple[bool, str]:
    """Заменить предложенное имя тем, что ввёл человек (раздел 79 ТЗ).

    Программа предлагает, решает человек. Введённое имя проходит те же
    проверки, что и собранное автоматически: запрещённые символы убираются,
    расширение сохраняется, совпадение с другим файлом не допускается.

    Returns:
        ``(принято, сообщение)``.
    """
    text = (name or "").strip()
    if not text:
        return False, "Имя не может быть пустым."

    suffix = item.source_path.suffix
    stem = text
    if not item.is_folder:
        entered = Path(text)
        if entered.suffix.lower() == suffix.lower():
            stem = entered.stem
        elif entered.suffix and entered.suffix.lower() != suffix.lower():
            return False, f"Расширение менять нельзя: у файла оно «{suffix}»."

    if item.is_folder:
        cleaned = sanitize_component(stem, keep_spaces=True)
        if not cleaned:
            return False, "В имени не осталось допустимых символов."
    else:
        cleaned_name = sanitize_filename(stem, suffix, keep_spaces=True)
        cleaned = Path(cleaned_name).stem

    target_name = cleaned if item.is_folder else f"{cleaned}{normalize_extension(suffix)}"
    if target_name == item.source_path.name:
        item.proposed_filename = target_name
        item.target_path = item.source_path
        item.status = Status.NAME_UNCHANGED.value
        item.message = "Имя оставлено прежним."
        item.selected = False
        return True, "Имя оставлено прежним."

    taken = {
        fold(other.target_path.name)
        for other in plan.items
        if other is not item and other.target_path.parent == item.source_path.parent
    }
    if fold(target_name) in taken:
        return False, "Такое имя уже занято другим файлом в этой папке."
    existing = item.source_path.parent / target_name
    if existing.exists() and existing != item.source_path:
        return False, "Файл с таким именем в папке уже есть."

    item.proposed_filename = target_name
    item.target_path = item.source_path.parent / target_name
    item.status = Status.OK.value
    item.message = "Имя задано вручную."
    item.selected = True
    item.add_status(Status.MANUAL_NAME.value)
    if item.analysis is not None:
        item.analysis.metadata["manual_name"] = target_name
    return True, f"Имя задано вручную: {target_name}"


def merge_as_document(
    plan: RenamePlan, items: list[PlanItem], name: str
) -> tuple[bool, str]:
    """Считать выбранные файлы страницами одного документа (раздел 79 ТЗ).

    Бывает, что программа не догадалась: сканы лежат без распознавания, имена
    ничего не говорят, и восемь листов выглядят восемью документами. Тогда
    решение принимает человек — отмечает файлы и объединяет их сам.

    Порядок страниц берётся из имён: он и так задан нумерацией, а если номеров
    нет — обычным порядком имён.

    Returns:
        ``(принято, сообщение)``.
    """
    pages = [item for item in items if not item.is_folder]
    if len(pages) < 2:
        return False, "Выберите хотя бы два файла — страницы одного документа."
    directories = {item.source_path.parent for item in pages}
    if len(directories) > 1:
        return False, "Страницы одного документа должны лежать в одной папке."

    base = sanitize_component(name, keep_spaces=True)
    if not base:
        return False, "Имя документа не может быть пустым."

    ordered = sorted(pages, key=lambda item: _page_order(item.source_path))
    width = len(str(len(ordered)))
    taken = {
        fold(other.target_path.name)
        for other in plan.items
        if other not in pages and other.target_path.parent in directories
    }
    prepared: list[tuple[PlanItem, str]] = []
    for number, item in enumerate(ordered, start=1):
        target = f"{base}_стр_{number:0{width}d}{normalize_extension(item.source_path.suffix)}"
        if fold(target) in taken:
            return False, f"Имя «{target}» уже занято другим файлом."
        taken.add(fold(target))
        prepared.append((item, target))

    for item, target in prepared:
        item.proposed_filename = target
        item.target_path = item.source_path.parent / target
        item.status = Status.OK.value
        item.message = "Страница документа, объединено вручную."
        item.selected = True
        item.add_status(Status.MANUAL_NAME.value)
        item.add_status(Status.SERIES_PART_DETECTED.value)
        if item.analysis is not None:
            item.analysis.metadata["manual_document"] = base
    return True, f"Объединено страниц: {len(prepared)} — «{base}»."


def _page_order(path: Path) -> tuple[int, str]:
    """Порядок страницы: сначала по номеру в имени, затем по самому имени."""
    from docrenamer.extractors.series import SCAN_HEAD_RE, SCAN_TAIL_RE

    stem = path.stem.strip()
    for pattern in (SCAN_HEAD_RE, SCAN_TAIL_RE):
        match = pattern.match(stem)
        if match is not None:
            return int(match.group("num")), stem.casefold()
    return 10**6, stem.casefold()



def make_plan_item(path: Path, *, config: Config) -> PlanItem | None:
    """Строка плана для файла, которого в плане ещё нет.

    Нужна, когда человек добавляет страницу вручную: файл мог не попасть в
    разбор (например, программа сочла его служебным) или появиться в папке
    после сканирования. Содержимое читается только ради контрольной суммы —
    она понадобится при переименовании.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    try:
        digest = sha256_file(path)
    except HashError:
        return None
    return PlanItem(
        source_path=path,
        target_path=path,
        proposed_filename=path.name,
        sha256=digest,
        size=stat.st_size,
        mtime=stat.st_mtime,
        confidence=0.0,
        selected=False,
        status=Status.NAME_UNCHANGED.value,
        message="Файл добавлен вручную.",
    )
