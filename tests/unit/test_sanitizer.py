"""Тесты санитизации имён (раздел 45 ТЗ)."""

from __future__ import annotations

import unicodedata

import pytest

from docrenamer.naming.sanitizer import (
    RESERVED_NAMES,
    Segment,
    assemble_filename,
    is_safe_filename,
    normalize_extension,
    sanitize_component,
    sanitize_filename,
    utf8_length,
)


@pytest.mark.parametrize("char", list('<>:"/\\|?*'))
def test_forbidden_windows_chars_removed(char: str) -> None:
    result = sanitize_filename(f"имя{char}файла", ".pdf")
    assert char not in result
    assert is_safe_filename(result)


def test_control_and_format_chars_removed() -> None:
    # U+202E маскирует расширение файла и обязан исчезнуть.
    result = sanitize_filename("файл‮gpj.exe\x07\x00", ".jpg")
    assert all(unicodedata.category(ch) not in ("Cc", "Cf") for ch in result)
    assert result.endswith(".jpg")


@pytest.mark.parametrize("name", sorted(RESERVED_NAMES))
def test_reserved_names_escaped(name: str) -> None:
    result = sanitize_filename(name, ".txt")
    assert result != f"{name}.txt"
    assert is_safe_filename(result)


@pytest.mark.parametrize("stem", [".", "..", "", "   ", "..."])
def test_degenerate_names_replaced(stem: str) -> None:
    result = sanitize_filename(stem, ".pdf")
    assert result not in (".pdf", "..pdf", ".", "..")
    assert is_safe_filename(result)


def test_extension_preserved_and_lowercased() -> None:
    assert sanitize_filename("Фото", ".HEIC") == "Фото.heic"
    assert normalize_extension("JPG") == ".jpg"


def test_no_trailing_space_or_dot() -> None:
    result = sanitize_filename("имя файла. ", ".pdf")
    assert not result.replace(".pdf", "").endswith((".", " "))


def test_cyrillic_and_typography_preserved() -> None:
    result = sanitize_filename("Договор №17 «Альфа» — копия ёж", ".docx")
    for char in "№«»—ё":
        assert char in result


def test_length_limits_chars_and_bytes() -> None:
    result = sanitize_filename("я" * 400, ".pdf", max_length=160)
    assert len(result) <= 160
    assert utf8_length(result) <= 255


def test_unicode_normalized_to_nfc() -> None:
    decomposed = "й" + "жик"  # й в разложенной форме
    result = sanitize_filename(decomposed, ".txt")
    assert result == unicodedata.normalize("NFC", result)


def test_segments_dropped_by_priority_keeping_identifier() -> None:
    segments = [
        Segment("2026-07-27", 95, droppable=False, kind="date"),
        Segment("Постановление_СПИ", 80, droppable=False, kind="type"),
        Segment("очень длинный предмет " * 6, 25, kind="subject"),
        Segment("Иванов", 60, kind="entities"),
        Segment("652102_26_77028_ИП", 90, droppable=False, kind="identifier"),
    ]
    name, dropped = assemble_filename(segments, ".pdf", max_length=80)
    assert "652102_26_77028_ИП" in name
    assert "2026-07-27" in name
    assert "subject" in dropped
    assert len(name) <= 80


def test_sanitize_component_collapses_whitespace() -> None:
    assert sanitize_component("  Иван   Иванович  ") == "Иван_Иванович"
