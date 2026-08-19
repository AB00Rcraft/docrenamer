"""Показать файл в проводнике системы.

Из окна программы часто нужно перейти к самому файлу: посмотреть соседние,
скопировать, отправить. Пересказывать путь и искать его руками в проводнике —
лишняя работа, поэтому программа открывает нужную папку сама и по возможности
выделяет в ней файл.

Ничего не открывается самой программой и ничего не выполняется из файла: в
систему передаётся только путь, а показывает его штатный проводник.

Команда собирается отдельной функцией без запуска — так её можно проверить на
любой системе, а не только на той, для которой она предназначена.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

#: Дольше ждать нечего: проводник либо запускается сразу, либо не запустится.
TIMEOUT_SECONDS = 10


def reveal_command(path: Path, *, system: str = os.name) -> list[str] | None:
    """Команда, показывающая файл в проводнике, или ``None``, если её нет.

    Windows умеет выделить сам файл: ``explorer /select,<путь>``. Запятая и
    отсутствие пробела здесь обязательны — с пробелом explorer откроет
    «Документы» вместо нужной папки.

    В остальных системах единого способа выделить файл нет, поэтому
    открывается папка, в которой файл лежит.
    """
    target = Path(path)
    if system == "nt":
        explorer = shutil.which("explorer") or "explorer"
        return [explorer, f"/select,{target}"]
    opener = shutil.which("open")  # macOS умеет выделять файл
    if opener:
        return [opener, "-R", str(target)]
    opener = shutil.which("xdg-open")
    if opener:
        directory = target if target.is_dir() else target.parent
        return [opener, str(directory)]
    return None


def reveal(path: Path, *, system: str = os.name) -> str:
    """Показать файл в проводнике. Пустая строка — получилось.

    Возвращается человеческая причина неудачи: окно должно объяснить, что
    произошло, а не промолчать.
    """
    target = Path(path)
    if not target.exists():
        return "Файла больше нет на прежнем месте."
    command = reveal_command(target, system=system)
    if command is None:
        return "В системе не нашлось программы для открытия папок."
    try:
        subprocess.run(  # noqa: S603 — список аргументов, shell=False, без ввода извне
            command,
            shell=False,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Не удалось открыть проводник: {exc}"
    # Код возврата не проверяется намеренно: explorer возвращает 1 и при
    # удачном открытии окна.
    return ""
