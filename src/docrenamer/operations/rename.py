"""Транзакция переименования (раздел 48 ТЗ).

Единственный модуль приложения, который меняет имя пользовательского файла.
Содержимое файла при этом не открывается на запись ни на одном шаге.

Порядок шагов раздела 48 ТЗ:

1. source exists;
2. target отсутствует;
3. получить size;
4. SHA-256 before;
5. проверить, что source не изменился после preview;
6. rename внутри той же директории;
7. target exists;
8. SHA-256 after;
9. hashes equal;
10. записать manifest (выполняет вызывающий код).
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

from docrenamer.operations import safety
from docrenamer.operations.hashing import HashError, sha256_file
from docrenamer.types import RenameRecord, Status, utcstamp

#: Константы renameat2(2). RENAME_NOREPLACE делает переименование
#: неперезаписывающим на уровне ядра — это закрывает гонку между проверкой
#: «цель свободна» и самой операцией.
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class CriticalSafetyError(RuntimeError):
    """Нарушение инварианта целостности.

    Поднимается только при расхождении SHA-256 до и после переименования.
    Пакетная обработка обязана остановиться (раздел 48 ТЗ).
    """


@dataclass(slots=True)
class RenameOutcome:
    """Результат одной транзакции."""

    ok: bool
    status: str
    message: str = ""
    record: RenameRecord | None = None
    target_path: Path | None = None
    method: str = ""


def _renameat2_noreplace(source: Path, target: Path) -> bool:
    """Атомарное переименование без перезаписи через ``renameat2``.

    Возвращает False, если системный вызов недоступен. Ошибка «цель существует»
    поднимается как :class:`FileExistsError` — перезаписи не происходит.
    """
    if os.name == "nt":
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        func = libc.renameat2
    except (OSError, AttributeError):
        return False
    func.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    func.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = func(
        _AT_FDCWD,
        os.fsencode(str(source)),
        _AT_FDCWD,
        os.fsencode(str(target)),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return True
    errno = ctypes.get_errno()
    if errno == 17:  # EEXIST
        raise FileExistsError(f"Целевое имя занято: {target}")
    if errno in (38, 22, 95):  # ENOSYS / EINVAL / EOPNOTSUPP — вызов не поддержан
        return False
    raise OSError(errno, os.strerror(errno), str(source), None, str(target))


def _rename_no_clobber(source: Path, target: Path) -> str:
    """Переименовать файл, не имея возможности перезаписать существующий.

    Возвращает использованный метод — он попадает в manifest.

    * Windows: ``os.rename`` завершается ошибкой, если цель существует, поэтому
      перезапись невозможна по определению.
    * Linux: ``renameat2(RENAME_NOREPLACE)``.
    * Прочие POSIX: ``os.link`` (не перезаписывает) + удаление старого имени.
      Удаляется только жёсткая ссылка на уже сохранённое содержимое: сам файл и
      его inode остаются на месте. Это не является удалением пользовательского
      файла в смысле раздела 2 ТЗ.
    """
    if os.name == "nt":
        os.rename(source, target)
        return "os.rename"

    if _renameat2_noreplace(source, target):
        return "renameat2(RENAME_NOREPLACE)"

    try:
        os.link(source, target)
    except OSError as exc:
        raise OSError(
            f"Файловая система не поддерживает безопасное переименование: {exc}"
        ) from exc
    try:
        os.unlink(source)  # снимается только старая ссылка на тот же inode
    except OSError as exc:
        # Содержимое доступно под новым именем; старое имя осталось.
        raise OSError(
            f"Файл доступен под новым именем, но старое имя не снято: {exc}"
        ) from exc
    return "link+unlink"


def rename_directory(
    source: Path,
    target: Path,
    *,
    max_name_length: int = 240,
) -> RenameOutcome:
    """Переименовать папку.

    У папки нет содержимого, которое можно сверить контрольной суммой, поэтому
    целостность проверяется иначе: до и после операции сравнивается состав —
    имена элементов первого уровня. Сама папка не перемещается и не удаляется,
    её содержимое не трогается.
    """
    source = Path(source)
    target = Path(target)

    if source == target:
        return RenameOutcome(
            ok=False,
            status=Status.NAME_UNCHANGED.value,
            message="Имя не изменилось.",
            target_path=target,
        )
    if not source.is_dir() or source.is_symlink():
        return RenameOutcome(
            ok=False,
            status=Status.UNSAFE_PATH.value,
            message=f"Это не папка: {source}",
            target_path=target,
        )

    check = safety.check_same_directory(source, target)
    if not check.ok:
        return RenameOutcome(
            ok=False, status=check.status, message=check.message, target_path=target
        )
    for control in (
        safety.check_target_name(target, max_name_length),
        safety.check_path_length(target),
        safety.check_directory_writable(target.parent),
        safety.check_target_free(target),
    ):
        if not control.ok:
            return RenameOutcome(
                ok=False, status=control.status, message=control.message, target_path=target
            )

    try:
        before = sorted(entry.name for entry in source.iterdir())
    except OSError as exc:
        return RenameOutcome(
            ok=False,
            status=Status.READ_ERROR.value,
            message=f"Папка недоступна: {exc}",
            target_path=target,
        )

    try:
        method = _rename_no_clobber(source, target)
    except FileExistsError:
        return RenameOutcome(
            ok=False,
            status=Status.NAME_COLLISION_RESOLVED.value,
            message=f"Целевое имя оказалось занято: {target.name}",
            target_path=target,
        )
    except PermissionError as exc:
        return RenameOutcome(
            ok=False,
            status=Status.ACCESS_DENIED.value,
            message=f"Нет прав на переименование папки: {exc}",
            target_path=target,
        )
    except OSError as exc:
        return RenameOutcome(
            ok=False,
            status=Status.READ_ERROR.value,
            message=f"Папка не переименована: {exc}",
            target_path=target,
        )

    if not target.is_dir():
        raise CriticalSafetyError(f"После переименования папка отсутствует: {target}")
    after = sorted(entry.name for entry in target.iterdir())
    if after != before:
        raise CriticalSafetyError(
            f"Состав папки изменился при переименовании: {source.name} → {target.name}"
        )

    record = RenameRecord(
        source_path=source,
        target_path=target,
        original_filename=source.name,
        new_filename=target.name,
        sha256_before="",
        sha256_after="",
        size=len(before),
        mtime=0.0,
        detected_type="folder",
        confidence=0.0,
        status=Status.RENAMED.value,
        timestamp=utcstamp(),
        message=f"method={method}, элементов: {len(before)}",
        kind="folder",
    )
    return RenameOutcome(
        ok=True,
        status=Status.RENAMED.value,
        record=record,
        target_path=target,
        method=method,
    )


def rename_file(
    source: Path,
    target: Path,
    *,
    expected_size: int | None = None,
    expected_mtime: float | None = None,
    expected_sha256: str = "",
    detected_type: str = "",
    confidence: float = 0.0,
    max_name_length: int = 240,
) -> RenameOutcome:
    """Выполнить одну транзакцию переименования.

    Raises:
        CriticalSafetyError: SHA-256 до и после операции не совпали.
    """
    source = Path(source)
    target = Path(target)

    if source == target:
        return RenameOutcome(
            ok=False,
            status=Status.NAME_UNCHANGED.value,
            message="Имя не изменилось.",
            target_path=target,
        )

    # Шаги 1–3, 5: проверки перед мутацией.
    check = safety.preflight(
        source,
        target,
        expected_size=expected_size,
        expected_mtime=expected_mtime,
        max_name_length=max_name_length,
    )
    if not check.ok:
        return RenameOutcome(
            ok=False, status=check.status, message=check.message, target_path=target
        )

    try:
        stat = source.stat()
    except OSError as exc:
        return RenameOutcome(
            ok=False,
            status=Status.READ_ERROR.value,
            message=f"Не удалось получить сведения о файле: {exc}",
            target_path=target,
        )

    # Шаг 4: контрольная сумма до операции.
    try:
        sha_before = sha256_file(source)
    except HashError as exc:
        return RenameOutcome(
            ok=False, status=Status.HASH_ERROR.value, message=str(exc), target_path=target
        )

    # Шаг 5 (строгая часть): содержимое не изменилось с момента предпросмотра.
    if expected_sha256 and sha_before != expected_sha256:
        return RenameOutcome(
            ok=False,
            status=Status.SOURCE_CHANGED_AFTER_PREVIEW.value,
            message="Содержимое файла изменилось после предпросмотра.",
            target_path=target,
        )

    # Шаг 6: собственно переименование.
    try:
        method = _rename_no_clobber(source, target)
    except FileExistsError:
        return RenameOutcome(
            ok=False,
            status=Status.NAME_COLLISION_RESOLVED.value,
            message=f"Целевое имя оказалось занято: {target.name}",
            target_path=target,
        )
    except PermissionError as exc:
        return RenameOutcome(
            ok=False,
            status=Status.ACCESS_DENIED.value,
            message=f"Нет прав на переименование: {exc}",
            target_path=target,
        )
    except OSError as exc:
        locked = getattr(exc, "winerror", 0) == 32
        status = Status.FILE_LOCKED.value if locked else Status.READ_ERROR.value
        return RenameOutcome(
            ok=False,
            status=status,
            message=f"Переименование не выполнено: {exc}",
            target_path=target,
        )

    # Шаг 7: цель существует.
    if not target.exists():
        raise CriticalSafetyError(
            f"После переименования целевой файл отсутствует: {target}"
        )

    # Шаги 8–9: контрольная сумма после операции.
    try:
        sha_after = sha256_file(target)
    except HashError as exc:
        raise CriticalSafetyError(
            f"Не удалось проверить целостность после переименования: {exc}"
        ) from exc

    if sha_after != sha_before:
        raise CriticalSafetyError(
            "CRITICAL_HASH_MISMATCH: контрольная сумма изменилась при переименовании "
            f"{source.name} → {target.name}"
        )

    # Шаг 10: метаданные файла не тронуты. Переименование меняет запись в
    # каталоге, а не сам файл: размер и время изменения обязаны остаться
    # прежними, и это проверяется, а не предполагается.
    try:
        stat_after = target.stat()
        size_after, mtime_after = stat_after.st_size, stat_after.st_mtime
    except OSError:
        size_after, mtime_after = -1, -1.0
    if size_after >= 0 and size_after != stat.st_size:
        raise CriticalSafetyError(
            "CRITICAL_SIZE_MISMATCH: размер файла изменился при переименовании "
            f"{source.name} → {target.name}"
        )

    record = RenameRecord(
        source_path=source,
        target_path=target,
        original_filename=source.name,
        new_filename=target.name,
        sha256_before=sha_before,
        sha256_after=sha_after,
        size=stat.st_size,
        mtime=stat.st_mtime,
        detected_type=detected_type,
        confidence=confidence,
        status=Status.RENAMED.value,
        timestamp=utcstamp(),
        message=f"method={method}",
        size_after=size_after,
        mtime_after=mtime_after,
    )
    return RenameOutcome(
        ok=True,
        status=Status.RENAMED.value,
        message="",
        record=record,
        target_path=target,
        method=method,
    )
