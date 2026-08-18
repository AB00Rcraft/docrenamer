"""Русский профиль обработки текста (разделы 14A.2, 14A.3, 95 ТЗ)."""

from __future__ import annotations

import pytest

from docrenamer.encoding import decode_bytes, read_text_file
from docrenamer.textquality import (
    assess,
    comparison_key,
    mixed_alphabet_words,
    russian_frequency_score,
    try_fix_mojibake,
)
from docrenamer.types import Status

SAMPLE = (
    "Договор займа номер 17. Иванов Иван Иванович, город Москва, "
    "сумма сто тысяч рублей, срок возврата восемнадцатое августа две тысячи "
    "двадцать шестого года, общество Альфа"
)


@pytest.mark.parametrize(
    "encoding",
    [
        "utf-8",
        "utf-8-sig",
        "windows-1251",
        "koi8-r",
        "cp866",
        "iso-8859-5",
        "utf-16-le",
        "utf-16-be",
    ],
)
def test_all_required_encodings_decoded(encoding: str) -> None:
    """Все обязательные кодировки раздела 14A.2 читаются без искажений."""
    data = SAMPLE.encode(encoding)
    result = decode_bytes(data)
    assert result.text.strip() == SAMPLE
    assert result.quality > 0.7
    assert Status.MOJIBAKE_SUSPECTED.value not in result.statuses


def test_bom_takes_priority() -> None:
    result = decode_bytes(SAMPLE.encode("utf-8-sig"))
    assert result.bom is True
    assert result.encoding == "utf-8-sig"


def test_cp1251_not_confused_with_koi8r() -> None:
    """CP1251 и KOI8-R различимы: обе дают кириллицу, но частоты разные."""
    result = decode_bytes(SAMPLE.encode("windows-1251"))
    assert "1251" in result.encoding
    assert result.text.strip() == SAMPLE


def test_cyrillic_not_decoded_as_other_script() -> None:
    """Кириллица не должна превращаться в иврит/греческий (профиль RUSSIAN-FIRST)."""
    result = decode_bytes("Договор займа №17 «Альфа» Иванов Иван Иванович".encode("cp1251"))
    assert "Договор" in result.text


def test_mojibake_detected_and_repaired_reversibly() -> None:
    broken = SAMPLE.encode("utf-8").decode("latin-1")
    report = assess(broken)
    assert report.is_mojibake
    fixed, label = try_fix_mojibake(broken)
    assert fixed == SAMPLE
    assert label


def test_clean_text_is_never_auto_repaired() -> None:
    fixed, label = try_fix_mojibake(SAMPLE)
    assert fixed == SAMPLE
    assert label == ""


def test_uppercase_legal_header_is_good_quality() -> None:
    header = "ПОСТАНОВЛЕНИЕ СУДЕБНОГО ПРИСТАВА-ИСПОЛНИТЕЛЯ О ВОЗБУЖДЕНИИ ПРОИЗВОДСТВА"
    assert assess(header).score > 0.8


def test_garbage_scores_low() -> None:
    garbage = "дНЦНБНП ГЮИЛЮ ╧17 ╚юКЭТЮ╩ хБЮМНБ хБЮМ хБЮМНБХВ ЦНПНД лНЯЙБЮ"
    report = assess(garbage)
    assert report.score < 0.3
    assert Status.MOJIBAKE_SUSPECTED.value in report.statuses


def test_frequency_score_ignores_short_text() -> None:
    score, count = russian_frequency_score("Иванов")
    assert score == 1.0
    assert count < 20


def test_mixed_alphabet_detected_but_value_preserved() -> None:
    words = mixed_alphabet_words("Компания Aльфа и Bета")
    assert words == ["Aльфа", "Bета"]


def test_comparison_key_treats_yo_as_ye() -> None:
    assert comparison_key("Ёлкин") == comparison_key("Елкин")
    assert comparison_key("Ёлкин") != "Ёлкин"


def test_empty_and_binary_input() -> None:
    assert decode_bytes(b"").text == ""
    binary = decode_bytes(bytes(range(256)))
    assert binary.quality < 0.5
    assert Status.ENCODING_UNCERTAIN.value in binary.statuses


def test_no_silent_data_loss(tmp_path) -> None:
    """Символы не выбрасываются молча: потеря видна как предупреждение."""
    path = tmp_path / "смешанный.txt"
    path.write_bytes("Договор".encode("cp1251") + b"\xff\xfe\x00" + "Иванов".encode("cp1251"))
    result = read_text_file(path)
    assert result.text
    assert result.encoding
