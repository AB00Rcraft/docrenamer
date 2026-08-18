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
