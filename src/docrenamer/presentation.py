"""Форматирование данных для интерфейса (разделы 78–80, 95 ТЗ).

Модуль намеренно не зависит от Tkinter: отображение русских имён входит в
release gate раздела 95 и должно проверяться в любой среде, в том числе там,
где графическая подсистема недоступна.
"""

from __future__ import annotations

from docrenamer.types import PlanItem, Status

#: Значки состояний для интерфейса (раздел 78 ТЗ).
STATUS_ICONS: dict[str, str] = {
    Status.OK.value: "✓",
    Status.RENAMED.value: "✓",
    Status.SKIPPED_LOW_CONFIDENCE.value: "!",
    Status.NAME_UNCHANGED.value: "○",
    Status.UNSUPPORTED_FORMAT.value: "○",
    Status.READ_ERROR.value: "×",
    Status.ACCESS_DENIED.value: "×",
    Status.HASH_ERROR.value: "×",
    Status.PASSWORD_PROTECTED.value: "×",
    Status.SIDECAR_DETECTED.value: "!",
    Status.LIVE_PHOTO_PAIR_DETECTED.value: "!",
}

#: Состояния, которые считаются ошибкой чтения файла.
ERROR_STATUSES = frozenset(
    {
        Status.READ_ERROR.value,
        Status.ACCESS_DENIED.value,
        Status.HASH_ERROR.value,
        Status.FILE_LOCKED.value,
    }
)


def format_plan_row(item: PlanItem) -> tuple[str, str, str, str, str]:
    """Значения строки предпросмотра.

    Галочка вынесена в отдельную колонку: по ней удобно попасть щелчком, и
    отклик получается сразу, без выделения строки и двойных нажатий.
    """
    return (
        "☑" if item.selected else "☐",
        item.source_path.name,
        item.proposed_filename if item.is_rename else "—",
        f"{item.confidence * 100:.0f}%",
        item.status,
    )


def plan_row_values(item: PlanItem) -> tuple[str, str, str, str, str]:
    """Значения строки дерева: имя стоит в колонке дерева, отдельно от них."""
    from docrenamer.preview import metadata_cell

    mark, _current, proposed, confidence, status = format_plan_row(item)
    return (mark, proposed, confidence, status, metadata_cell(item))


def plan_row_label(item: PlanItem) -> str:
    """Подпись строки в дереве.

    У папки к имени добавляется значок: в общем списке сразу видно, где
    заканчивается корень и начинается вложенная папка.
    """
    name = item.source_path.name
    return f"📁 {name}" if item.is_folder else name


def row_tag(item: PlanItem) -> str:
    """Цветовая метка строки предпросмотра."""
    if item.status in ERROR_STATUSES:
        return "error"
    return "ok" if item.selected else "warn"


def status_icon(status: str) -> str:
    """Значок состояния для журнала интерфейса."""
    return STATUS_ICONS.get(status, "·")


def progress_label(done: int, total: int, stage: str) -> str:
    """Строка прогресса вида ``ANALYZE  38 / 184`` (раздел 80 ТЗ)."""
    return f"{stage}  {done} / {total}" if stage else f"{done} / {total}"
