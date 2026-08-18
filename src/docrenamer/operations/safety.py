"""Проверки безопасности файловых операций (разделы 48, 49, 69, 77 ТЗ).

Модуль не выполняет мутаций. Он отвечает на вопрос «допустима ли операция»
и возвращает код из единого словаря вместе с русским пояснением.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from docrenamer.naming.sanitizer import is_safe_filename
from docrenamer.operations.hashing import HashError, sha256_file
from docrenamer.types import Status

#: Классический предел пути Windows. Длинные пути включаются отдельно, поэтому
#: приложение остаётся в консервативных рамках.
WINDOWS_MAX_PATH = 260


@dataclass(frozen=True, slots=True)
class Check:
    """Результат проверки."""

    ok: bool
    status: str = Status.OK.value
    message: str = ""

    def __bool__(self) -> bool:
        return self.ok


OK = Check(True)


def check_path_length(path: Path) -> Check:
    """Длина пути допустима для целевой платформы."""
    text = str(path)
    if os.name == "nt" and len(text) >= WINDOWS_MAX_PATH:
        return Check(
            False,
            Status.PATH_TOO_LONG.value,
            f"Путь длиннее {WINDOWS_MAX_PATH} символов: {text}",
        )
    if len(path.name.encode("utf-8")) > 255:
        return Check(
            False,
            Status.PATH_TOO_LONG.value,
            f"Имя файла длиннее 255 байт: {path.name}",
        )
    return OK


def check_same_directory(source: Path, target: Path) -> Check:
    """Переименование не должно превращаться в перемещение (раздел 2 ТЗ)."""
    if source.parent != target.parent:
        return Check(
            False,
            Status.UNSAFE_PATH.value,
            "Запрещено перемещать файл в другой каталог: разрешено только "
            "переименование внутри текущей директории.",
        )
    return OK


def check_source_ready(source: Path) -> Check:
    """Источник существует, является обычным файлом и доступен на чтение."""
    try:
        if not source.exists():
            return Check(False, Status.SKIPPED.value, f"Файл исчез: {source}")
        if source.is_dir():
            return Check(False, Status.UNSAFE_PATH.value, f"Это каталог, а не файл: {source}")
        if source.is_symlink():
            return Check(
                False,
                Status.UNSAFE_PATH.value,
                f"Символические ссылки не переименовываются: {source}",
            )
        if not os.access(source, os.R_OK):
            return Check(False, Status.ACCESS_DENIED.value, f"Нет прав на чтение: {source}")
    except OSError as exc:
        return Check(False, Status.READ_ERROR.value, f"Ошибка доступа к файлу: {exc}")
    return OK


def check_target_free(target: Path) -> Check:
    """Цель обязана отсутствовать: перезапись запрещена (раздел 77 ТЗ)."""
    try:
        if target.exists() or target.is_symlink():
            return Check(
                False,
                Status.NAME_COLLISION_RESOLVED.value,
                f"Целевое имя уже занято: {target.name}",
            )
    except OSError as exc:
        return Check(False, Status.UNSAFE_PATH.value, f"Не удалось проверить цель: {exc}")
    return OK


def check_target_name(target: Path, max_length: int = 240) -> Check:
    """Имя цели прошло санитизацию и допустимо в файловой системе."""
    if not is_safe_filename(target.name, max_length=max_length):
        return Check(
            False,
            Status.UNSAFE_PATH.value,
            f"Недопустимое имя файла: {target.name!r}",
        )
    return OK


def check_directory_writable(directory: Path) -> Check:
    """Каталог доступен на запись (раздел 69 ТЗ)."""
    if not directory.is_dir():
        return Check(False, Status.UNSAFE_PATH.value, f"Каталог не найден: {directory}")
    if not os.access(directory, os.W_OK | os.X_OK):
        return Check(
            False,
            Status.ACCESS_DENIED.value,
            f"Нет прав на запись в каталог: {directory}",
        )
    return OK


def check_not_modified(source: Path, expected_size: int, expected_mtime: float) -> Check:
    """Дешёвая проверка TOCTOU по ``size`` и ``mtime`` (раздел 49 ТЗ)."""
    try:
        stat = source.stat()
    except OSError as exc:
        return Check(False, Status.SOURCE_CHANGED_AFTER_PREVIEW.value, f"Файл недоступен: {exc}")
    if stat.st_size != expected_size:
        return Check(
            False,
            Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
            f"Размер файла изменился после предпросмотра: {expected_size} → {stat.st_size}",
        )
    # mtime сравнивается с допуском: некоторые ФС округляют его до секунды.
    if abs(stat.st_mtime - expected_mtime) > 1.0:
        return Check(
            False,
            Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
            "Время изменения файла отличается от зафиксированного в плане.",
        )
    return OK


def check_hash_unchanged(source: Path, expected_sha256: str) -> Check:
    """Строгая проверка TOCTOU по содержимому (раздел 49 ТЗ)."""
    if not expected_sha256:
        return Check(False, Status.HASH_ERROR.value, "В плане отсутствует контрольная сумма.")
    try:
        actual = sha256_file(source)
    except HashError as exc:
        return Check(False, Status.HASH_ERROR.value, str(exc))
    if actual != expected_sha256:
        return Check(
            False,
            Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
            "Содержимое файла изменилось после предпросмотра.",
        )
    return OK


def preflight(
    source: Path,
    target: Path,
    *,
    expected_size: int | None = None,
    expected_mtime: float | None = None,
    expected_sha256: str = "",
    max_name_length: int = 240,
) -> Check:
    """Полный набор проверок непосредственно перед мутацией.

    Порядок от дешёвых к дорогим: последней выполняется сверка SHA-256.
    """
    checks = [
        check_source_ready(source),
        check_same_directory(source, target),
        check_target_name(target, max_name_length),
        check_path_length(target),
        check_directory_writable(target.parent),
        check_target_free(target),
    ]
    for check in checks:
        if not check.ok:
            return check
    if expected_size is not None and expected_mtime is not None:
        check = check_not_modified(source, expected_size, expected_mtime)
        if not check.ok:
            return check
    if expected_sha256:
        check = check_hash_unchanged(source, expected_sha256)
        if not check.ok:
            return check
    return OK
