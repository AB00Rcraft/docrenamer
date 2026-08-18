"""Оценка качества текста и выявление mojibake (раздел 14A.3 ТЗ).

Непустой результат извлечения ещё не означает, что русский текст получен
корректно. Этот модуль даёт численную оценку и обнаруживает признаки неверной
декодировки, чтобы «кракозябры» не попали в имя файла.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from docrenamer.types import Status

#: Символ-замена, который появляется при потере данных при декодировании.
REPLACEMENT_CHAR = "�"

#: Символы, характерные для UTF-8, ошибочно прочитанного как CP1251/Latin-1.
MOJIBAKE_MARKERS = "ÐÑÂÃÐ°ÑÐµÑÐ¾Ð¸â€ŒŽšœžŸ¤¦§¨©ª«¬­®¯"

#: Русские гласные: почти любое настоящее русское слово содержит хотя бы одну.
RUSSIAN_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")

_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_CYRILLIC_WORD_RE = re.compile(r"[А-Яа-яЁё]{3,}")

#: Частотность букв русского языка (доли, «ё» объединена с «е»).
#: Используется для различения кириллических кодировок между собой: CP1251,
#: KOI8-R, CP866 и ISO-8859-5 все дают кириллицу, но только одна из них даёт
#: правдоподобное распределение букв.
RUSSIAN_LETTER_FREQUENCY: dict[str, float] = {
    "о": 0.1097, "е": 0.0967, "а": 0.0801, "и": 0.0735, "н": 0.0670,
    "т": 0.0626, "с": 0.0547, "р": 0.0473, "в": 0.0454, "л": 0.0440,
    "к": 0.0349, "м": 0.0321, "д": 0.0298, "п": 0.0281, "у": 0.0262,
    "я": 0.0201, "ы": 0.0190, "ь": 0.0174, "г": 0.0170, "з": 0.0165,
    "б": 0.0159, "ч": 0.0144, "й": 0.0121, "х": 0.0097, "ж": 0.0094,
    "ш": 0.0073, "ю": 0.0064, "ц": 0.0048, "щ": 0.0036, "э": 0.0032,
    "ф": 0.0026, "ъ": 0.0004,
}
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")

#: Пары визуально одинаковых кириллических и латинских букв (раздел 14A.11 ТЗ).
LOOKALIKE_PAIRS: tuple[tuple[str, str], ...] = (
    ("A", "А"),
    ("B", "В"),
    ("C", "С"),
    ("E", "Е"),
    ("H", "Н"),
    ("K", "К"),
    ("M", "М"),
    ("O", "О"),
    ("P", "Р"),
    ("T", "Т"),
    ("X", "Х"),
    ("a", "а"),
    ("c", "с"),
    ("e", "е"),
    ("o", "о"),
    ("p", "р"),
    ("x", "х"),
    ("y", "у"),
)


@dataclass(slots=True)
class QualityReport:
    """Результат оценки текста."""

    score: float = 0.0
    length: int = 0
    cyrillic_ratio: float = 0.0
    latin_ratio: float = 0.0
    replacement_ratio: float = 0.0
    control_ratio: float = 0.0
    mojibake_ratio: float = 0.0
    other_script_ratio: float = 0.0
    frequency_score: float = 1.0
    mixed_case_ratio: float = 0.0
    russian_word_ratio: float = 0.0
    warnings: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)

    @property
    def is_mojibake(self) -> bool:
        return Status.MOJIBAKE_SUSPECTED.value in self.statuses

    def to_dict(self) -> dict[str, float | list[str]]:
        return {
            "score": round(self.score, 4),
            "length": self.length,
            "cyrillic_ratio": round(self.cyrillic_ratio, 4),
            "latin_ratio": round(self.latin_ratio, 4),
            "replacement_ratio": round(self.replacement_ratio, 4),
            "control_ratio": round(self.control_ratio, 4),
            "mojibake_ratio": round(self.mojibake_ratio, 4),
            "other_script_ratio": round(self.other_script_ratio, 4),
            "frequency_score": round(self.frequency_score, 4),
            "mixed_case_ratio": round(self.mixed_case_ratio, 4),
            "russian_word_ratio": round(self.russian_word_ratio, 4),
            "warnings": list(self.warnings),
            "statuses": list(self.statuses),
        }


def russian_frequency_score(text: str) -> tuple[float, int]:
    """Насколько распределение кириллических букв похоже на русский язык.

    Возвращает ``(косинусная_близость, число_букв)``. Значение около 1.0 —
    правдоподобный русский текст; заметно ниже — кириллица получена неверной
    кодировкой (характерный случай CP1251, прочитанной как KOI8-R).
    """
    counts: dict[str, int] = {}
    total = 0
    for ch in text.lower():
        if not _CYRILLIC_RE.match(ch):
            continue
        letter = "е" if ch == "ё" else ch
        if letter not in RUSSIAN_LETTER_FREQUENCY:
            continue
        counts[letter] = counts.get(letter, 0) + 1
        total += 1
    if total < 20:
        return 1.0, total

    dot = 0.0
    observed_norm = 0.0
    reference_norm = 0.0
    for letter, expected in RUSSIAN_LETTER_FREQUENCY.items():
        observed = counts.get(letter, 0) / total
        dot += observed * expected
        observed_norm += observed * observed
        reference_norm += expected * expected
    if observed_norm <= 0 or reference_norm <= 0:
        return 0.0, total
    return dot / ((observed_norm**0.5) * (reference_norm**0.5)), total


def mixed_case_word_ratio(text: str) -> tuple[float, int]:
    """Доля слов с «рваным» регистром — признак перепутанной кодировки.

    Нормальное русское слово написано строчными, ПРОПИСНЫМИ либо С Заглавной.
    Слова вида «дНЦНБНП» появляются, когда CP1251 читают как KOI8-R.
    """
    words = _CYRILLIC_WORD_RE.findall(text)
    if not words:
        return 0.0, 0
    weird = 0
    for word in words:
        if word.islower() or word.isupper() or (word[0].isupper() and word[1:].islower()):
            continue
        weird += 1
    return weird / len(words), len(words)


def assess(text: str, *, sample: int = 20_000) -> QualityReport:
    """Оценить качество извлечённого текста.

    Оценка 1.0 — уверенно читаемый текст, 0.0 — мусор либо пустая строка.
    """
    report = QualityReport(length=len(text))
    if not text:
        report.warnings.append("Текст пуст.")
        return report

    chunk = text[:sample]
    total = len(chunk)

    replacements = chunk.count(REPLACEMENT_CHAR)
    controls = sum(
        1 for ch in chunk if unicodedata.category(ch) == "Cc" and ch not in "\r\n\t"
    )
    cyrillic = len(_CYRILLIC_RE.findall(chunk))
    latin = len(_LATIN_RE.findall(chunk))
    mojibake = sum(1 for ch in chunk if ch in MOJIBAKE_MARKERS)
    letters = sum(1 for ch in chunk if unicodedata.category(ch).startswith("L"))
    other_letters = max(0, letters - cyrillic - latin)

    report.replacement_ratio = replacements / total
    report.control_ratio = controls / total
    report.cyrillic_ratio = cyrillic / total
    report.latin_ratio = latin / total
    report.mojibake_ratio = mojibake / total
    report.other_script_ratio = other_letters / letters if letters else 0.0

    frequency, cyrillic_letters = russian_frequency_score(chunk)
    report.frequency_score = frequency
    case_ratio, cyrillic_words = mixed_case_word_ratio(chunk)
    report.mixed_case_ratio = case_ratio

    words = _WORD_RE.findall(chunk)
    russian_words = [w for w in words if _CYRILLIC_RE.search(w)]
    plausible = [w for w in russian_words if RUSSIAN_VOWELS & set(w)]
    report.russian_word_ratio = len(plausible) / len(russian_words) if russian_words else 0.0

    score = 1.0
    score -= min(1.0, report.replacement_ratio * 12.0)
    score -= min(1.0, report.control_ratio * 20.0)
    score -= min(0.8, report.mojibake_ratio * 8.0)
    if russian_words and report.russian_word_ratio < 0.5:
        score -= 0.35
    # Профиль RUSSIAN-FIRST: текст ожидается кириллическим или латинским.
    # Массовое появление третьей письменности почти всегда означает, что
    # кодировка выбрана неверно (например, кириллица прочитана как иврит).
    if other_letters > 3 and report.other_script_ratio > 0.15:
        score -= min(0.9, report.other_script_ratio * 1.2)
        report.warnings.append(
            "Текст содержит символы посторонней письменности — вероятно, неверная кодировка."
        )
    # Кириллица, полученная неверной кодировкой, выдаёт себя распределением
    # букв и рваным регистром слов (раздел 14A.3 ТЗ).
    if cyrillic_letters >= 20 and frequency < 0.85:
        score -= min(0.85, (0.85 - frequency) * 2.5)
        report.warnings.append(
            "Распределение букв не похоже на русский язык — вероятно, неверная кодировка."
        )
    if cyrillic_words >= 4 and case_ratio > 0.25:
        score -= min(0.8, case_ratio)
        report.warnings.append("Нехарактерное чередование регистра в словах.")

    if total >= 40 and (cyrillic + latin) / total < 0.25:
        score -= 0.25
        report.warnings.append("Мало буквенных символов — вероятно, не текст.")
    report.score = max(0.0, min(1.0, score))

    if report.replacement_ratio > 0.005:
        report.warnings.append(
            f"Символы замены U+FFFD: {report.replacement_ratio:.1%} — часть данных потеряна."
        )
        report.statuses.append(Status.ENCODING_UNCERTAIN.value)
    if report.mojibake_ratio > 0.02 or (
        russian_words and report.russian_word_ratio < 0.35 and cyrillic > 0
    ):
        report.warnings.append("Признаки неверной декодировки текста.")
        report.statuses.append(Status.MOJIBAKE_SUSPECTED.value)
    if other_letters > 3 and report.other_script_ratio > 0.4:
        report.statuses.append(Status.ENCODING_UNCERTAIN.value)
    if (cyrillic_letters >= 20 and frequency < 0.75) or (cyrillic_words >= 4 and case_ratio > 0.4):
        if Status.MOJIBAKE_SUSPECTED.value not in report.statuses:
            report.statuses.append(Status.MOJIBAKE_SUSPECTED.value)
    if report.control_ratio > 0.02:
        report.warnings.append("Высокая доля управляющих символов.")
        report.statuses.append(Status.ENCODING_UNCERTAIN.value)

    return report


def try_fix_mojibake(text: str) -> tuple[str, str]:
    """Попытаться однозначно восстановить неверно декодированный текст.

    Исправление применяется, только если преобразование обратимо и заметно
    повышает оценку качества (раздел 14A.3 ТЗ).

    Returns:
        ``(текст, описание)``. Пустое описание — исправление не применялось.
    """
    if not text:
        return text, ""
    base = assess(text)
    if base.score >= 0.75 and not base.is_mojibake:
        return text, ""

    best_text, best_score, best_label = text, base.score, ""
    for source_encoding in ("cp1251", "latin-1", "cp1252"):
        try:
            candidate = text.encode(source_encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        # Проверка обратимости: преобразование не должно терять данные.
        try:
            if candidate.encode("utf-8").decode(source_encoding) != text:
                continue
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        score = assess(candidate).score
        if score > best_score + 0.2:
            best_text, best_score, best_label = candidate, score, f"utf-8 как {source_encoding}"

    if best_label:
        return best_text, best_label
    return text, ""


def mixed_alphabet_words(text: str, *, limit: int = 20) -> list[str]:
    """Найти слова, в которых смешаны кириллица и латиница (раздел 14A.11 ТЗ).

    Значения не изменяются: результат используется только для предупреждения.
    """
    found: list[str] = []
    for word in _WORD_RE.findall(text):
        if _CYRILLIC_RE.search(word) and _LATIN_RE.search(word):
            found.append(word)
            if len(found) >= limit:
                break
    return found


def comparison_key(value: str) -> str:
    """Ключ сравнения, в котором «е» и «ё» эквивалентны (раздел 14A.4 ТЗ).

    Отображаемое значение при этом не меняется.
    """
    normalized = unicodedata.normalize("NFC", value).casefold()
    return normalized.replace("ё", "е").replace("й", "й")
