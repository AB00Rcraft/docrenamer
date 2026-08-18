"""Разрешение коллизий имён (раздел 47 ТЗ).

Перезапись существующего пользовательского файла невозможна ни при каких
условиях. Занятое имя получает числовой суффикс: ``имя__02.pdf``, ``имя__03.pdf``.
"""

from __future__ import annotations

from pathlib import Path

from docrenamer.naming.sanitizer import (
    MAX_FILENAME_BYTES,
    normalize_extension,
    sanitize_filename,
    utf8_length,
)

#: Максимальное число попыток подобрать свободное имя.
MAX_ATTEMPTS = 999


def fold(name: str) -> str:
    """Ключ сравнения имён без учёта регистра.

    Windows и macOS по умолчанию нечувствительны к регистру, поэтому
    ``ИМЯ.pdf`` и ``имя.pdf`` считаются одним и тем же именем.
    """
    return name.casefold()


def _exists(path: Path) -> bool:
    """Существует ли путь. Ошибка обращения к ФС трактуется как «занято».

    Консервативная трактовка: непроверяемое имя не должно стать целью rename.
    """
    try:
        return path.exists()
    except OSError:
        return True


def directory_names(directory: Path) -> set[str]:
    """Множество занятых имён каталога (в свёрнутом регистре)."""
    try:
        return {fold(entry.name) for entry in directory.iterdir()}
    except OSError:
        return set()


def _with_counter(
    stem: str,
    extension: str,
    counter: int,
    *,
    separator: str,
    max_length: int,
    max_bytes: int,
) -> str:
    """Собрать вариант имени с числовым суффиксом, уложившись в лимиты."""
    suffix = f"{separator}{counter:02d}"
    ext = normalize_extension(extension)
    budget_chars = max_length - len(ext) - len(suffix)
    budget_bytes = max_bytes - utf8_length(ext) - utf8_length(suffix)
    trimmed = stem
    while trimmed and (len(trimmed) > budget_chars or utf8_length(trimmed) > budget_bytes):
        trimmed = trimmed[:-1]
    trimmed = trimmed.rstrip(" .-_") or "файл"
    return sanitize_filename(
        f"{trimmed}{suffix}",
        extension,
        max_length=max_length,
        max_bytes=max_bytes,
    )


def resolve_collision(
    target: Path,
    *,
    taken: set[str] | None = None,
    source: Path | None = None,
    separator: str = "__",
    max_length: int = 160,
    max_bytes: int = MAX_FILENAME_BYTES,
) -> tuple[Path, bool]:
    """Подобрать свободное имя для ``target``.

    Args:
        target: желаемый путь.
        taken: дополнительно занятые имена (например, цели других строк плана),
            в свёрнутом регистре.
        source: путь исходного файла. Если цель отличается от источника только
            регистром, это не считается коллизией.

    Returns:
        ``(путь, была_ли_коллизия)``.
    """
    directory = target.parent
    # Повторная санитизация делает функцию устойчивой к слишком длинным именам:
    # обращение к ФС с именем длиннее NAME_MAX завершилось бы OSError.
    safe_name = sanitize_filename(
        target.stem, target.suffix, max_length=max_length, max_bytes=max_bytes
    )
    target = directory / safe_name

    occupied = set(taken or set())
    occupied |= directory_names(directory)

    is_self = (
        source is not None
        and source.parent == directory
        and fold(source.name) == fold(target.name)
    )
    if is_self:
        # Имя не меняется (или меняется только регистр) — это не коллизия.
        return target, False
    if source is not None and source.parent == directory:
        occupied.discard(fold(source.name))

    if fold(target.name) not in occupied and not _exists(target):
        return target, False

    stem = target.stem
    extension = target.suffix
    for counter in range(2, MAX_ATTEMPTS + 1):
        candidate_name = _with_counter(
            stem,
            extension,
            counter,
            separator=separator,
            max_length=max_length,
            max_bytes=max_bytes,
        )
        candidate = directory / candidate_name
        if fold(candidate_name) not in occupied and not _exists(candidate):
            return candidate, True

    raise FileExistsError(
        f"Не удалось подобрать свободное имя для «{target.name}»: "
        f"занято более {MAX_ATTEMPTS} вариантов."
    )
