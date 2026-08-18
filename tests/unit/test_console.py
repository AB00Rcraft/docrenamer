"""Консольный вывод на русском не должен ронять программу (раздел 14A.7 ТЗ)."""

from __future__ import annotations

import io
import sys

import pytest

from docrenamer.console import configure_console


def test_cyrillic_survives_single_byte_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Кириллица печатается даже в консоли с однобайтовой кодировкой.

    Именно так падала сборка на Windows: стандартный вывод там открыт в cp1252.
    """
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    configure_console()
    print("Аудит офлайн-режима пройден: сетевых зависимостей нет.")
    sys.stdout.flush()

    assert "Аудит" in buffer.getvalue().decode("utf-8")


def test_configure_console_is_idempotent_and_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный вызов и поток без reconfigure не приводят к ошибке."""
    configure_console()
    configure_console()

    class Dummy:
        def write(self, text: str) -> int:
            return len(text)

    monkeypatch.setattr(sys, "stdout", Dummy())
    configure_console()


def test_external_programs_start_without_console_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В Windows внешние программы запускаются скрыто.

    Иначе при обработке сотни файлов чёрное окно мигнёт сто раз.
    """
    import subprocess

    from docrenamer.security.subprocess_safe import hidden_process_options

    assert hidden_process_options() == {} or "creationflags" in hidden_process_options()

    class FakeStartupInfo:
        dwFlags = 0
        wShowWindow = 0

    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    options = hidden_process_options()

    assert options["creationflags"] == 0x08000000
    assert options["startupinfo"].dwFlags == 1


def test_hidden_options_are_used_by_run_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Параметры скрытого запуска действительно передаются в subprocess."""
    import subprocess

    from docrenamer.security import subprocess_safe

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)

        class Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return Result()

    monkeypatch.setattr(subprocess_safe, "hidden_process_options", lambda: {"creationflags": 42})
    monkeypatch.setattr(subprocess, "run", fake_run)

    subprocess_safe.run_tool("/bin/true", [], timeout=5)

    assert captured["creationflags"] == 42
    assert captured["shell"] is False
