"""Безопасный запуск локальных инструментов (раздел 55 ТЗ).

Единственный разрешённый способ вызвать ``llama-cli``, ``tesseract``,
``exiftool``, ``ffprobe`` или ``7z``. Команда всегда передаётся списком
аргументов, оболочка не используется, таймаут обязателен.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def hidden_process_options() -> dict[str, Any]:
    """Параметры запуска без появления консольного окна.

    В Windows каждый запуск консольной программы открывает чёрное окно. При
    обработке сотни файлов оно мигнёт сто раз. Программы запускаются скрыто:
    их вывод программа читает сама.
    """
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startup,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Результат запуска внешнего инструмента."""

    ok: bool
    returncode: int
    stdout: str
    stderr: str
    error: str = ""
    timed_out: bool = False


def run_tool(
    executable: Path | str,
    arguments: list[str],
    *,
    timeout: int = 60,
    input_bytes: bytes | None = None,
    cwd: Path | None = None,
) -> ToolResult:
    """Запустить локальный инструмент и вернуть его вывод.

    Ошибки не поднимаются: любой сбой внешнего процесса — это диагностическое
    состояние одного файла, а не крушение пакетной обработки.
    """
    command = [str(executable), *[str(a) for a in arguments]]
    try:
        completed = subprocess.run(  # noqa: S603 — список аргументов, без оболочки
            command,
            shell=False,
            capture_output=True,
            timeout=timeout,
            check=False,
            input=input_bytes,
            cwd=str(cwd) if cwd else None,
            **hidden_process_options(),
        )
    except FileNotFoundError:
        return ToolResult(False, -1, "", "", error=f"Программа не найдена: {executable}")
    except PermissionError as exc:
        return ToolResult(False, -1, "", "", error=f"Нет прав на запуск: {exc}")
    except subprocess.TimeoutExpired:
        return ToolResult(
            False,
            -1,
            "",
            "",
            error=f"Превышено время выполнения ({timeout} с): {executable}",
            timed_out=True,
        )
    except OSError as exc:
        return ToolResult(False, -1, "", "", error=f"Запуск не удался: {exc}")

    stdout = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""
    stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
    return ToolResult(
        ok=completed.returncode == 0,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )
