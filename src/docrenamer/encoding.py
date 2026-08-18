"""Определение кодировки текста (раздел 14A.2 ТЗ).

Порядок определения строго следует ТЗ:

1. BOM;
2. явная декларация кодировки внутри формата;
3. строгая попытка UTF-8;
4. ``charset-normalizer``;
5. сравнение вероятных русских legacy-кодировок;
6. проверка качества получившегося русского текста;
7. при недостаточной уверенности — ``ENCODING_UNCERTAIN``.

Молчаливое ``errors="ignore"`` запрещено: потеря символов обязана быть видимой.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docrenamer.textquality import assess, try_fix_mojibake
from docrenamer.types import Status, nfc

#: BOM-сигнатуры в порядке убывания длины.
BOM_TABLE: tuple[tuple[bytes, str], ...] = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)

#: Русские legacy-кодировки, обязательные к поддержке.
RUSSIAN_LEGACY_ENCODINGS: tuple[str, ...] = (
    "windows-1251",
    "koi8-r",
    "cp866",
    "iso-8859-5",
)

#: Порог, ниже которого качество текста считается сомнительным.
QUALITY_THRESHOLD = 0.6


@dataclass(slots=True)
class DecodeResult:
    """Результат декодирования байтов в Unicode."""

    text: str = ""
    encoding: str = ""
    confidence: float = 0.0
    quality: float = 0.0
    warnings: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    bom: bool = False

    def add_status(self, code: str | Status) -> None:
        value = code.value if isinstance(code, Status) else str(code)
        if value not in self.statuses:
            self.statuses.append(value)


def detect_bom(data: bytes) -> tuple[str, int]:
    """Определить кодировку по BOM. Возвращает ``(кодировка, длина_BOM)``."""
    for signature, encoding in BOM_TABLE:
        if data.startswith(signature):
            return encoding, len(signature)
    return "", 0


def _try_decode(data: bytes, encoding: str) -> str | None:
    """Строгое декодирование: при любой потере данных возвращается ``None``."""
    try:
        return data.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError):
        return None


def _charset_normalizer_guess(data: bytes) -> tuple[str, float]:
    """Подсказка от ``charset-normalizer``."""
    try:
        from charset_normalizer import from_bytes
    except ImportError:  # pragma: no cover — зависимость обязательна в сборке
        return "", 0.0
    try:
        matches = from_bytes(data)
    except Exception:
        return "", 0.0
    best = matches.best()
    if best is None or not best.encoding:
        return "", 0.0
    # chaos: 0.0 — идеально, 1.0 — мусор.
    confidence = max(0.0, 1.0 - float(getattr(best, "chaos", 0.0)))
    return str(best.encoding), confidence


def decode_bytes(data: bytes, *, declared: str = "") -> DecodeResult:
    """Декодировать байты пользовательского файла в Unicode.

    Args:
        data: содержимое файла.
        declared: кодировка, объявленная самим форматом (meta charset, XML
            declaration и т. п.).
    """
    result = DecodeResult()
    if not data:
        result.encoding = "utf-8"
        result.confidence = 1.0
        return result

    # 1. BOM.
    bom_encoding, bom_length = detect_bom(data)
    if bom_encoding:
        text = _try_decode(data[bom_length:] if bom_encoding != "utf-8-sig" else data, bom_encoding)
        if text is not None:
            return _finish(result, text, bom_encoding, 1.0, bom=True)

    candidates: list[tuple[str, float]] = []

    # 2. Явная декларация формата.
    if declared:
        normalized = declared.strip().lower().replace("_", "-")
        candidates.append((normalized, 0.95))

    # 3. Строгий UTF-8.
    candidates.append(("utf-8", 0.9))

    # 4. Подсказка charset-normalizer.
    guess, guess_confidence = _charset_normalizer_guess(data)
    if guess:
        candidates.append((guess, min(0.88, 0.5 + guess_confidence * 0.4)))

    # 5. Русские legacy-кодировки.
    candidates.extend((enc, 0.55) for enc in RUSSIAN_LEGACY_ENCODINGS)

    best: tuple[str, str, float, float] | None = None  # text, encoding, confidence, quality
    seen: set[str] = set()
    for encoding, confidence in candidates:
        if encoding in seen:
            continue
        seen.add(encoding)
        text = _try_decode(data, encoding)
        if text is None:
            continue
        # 6. Проверка качества получившегося русского текста.
        quality = assess(text).score
        combined = quality * 0.7 + confidence * 0.3
        if best is None or combined > best[2] * 0.3 + best[3] * 0.7:
            best = (text, encoding, confidence, quality)
        if quality >= 0.85 and confidence >= 0.85:
            break

    if best is None:
        # 7. Ничего не декодировалось строго: сохраняем диагностику явно.
        text = data.decode("utf-8", errors="replace")
        result.add_status(Status.ENCODING_UNCERTAIN)
        result.warnings.append(
            "Ни одна из проверенных кодировок не подошла; текст содержит символы замены."
        )
        return _finish(result, text, "utf-8/replace", 0.1)

    text, encoding, confidence, quality = best
    if quality < QUALITY_THRESHOLD:
        fixed, label = try_fix_mojibake(text)
        if label:
            text = fixed
            quality = assess(text).score
            result.warnings.append(f"Исправлена ошибочная декодировка ({label}).")
            encoding = f"{encoding}→utf-8"
    return _finish(result, text, encoding, confidence, quality=quality)


def _finish(
    result: DecodeResult,
    text: str,
    encoding: str,
    confidence: float,
    *,
    quality: float | None = None,
    bom: bool = False,
) -> DecodeResult:
    """Заполнить результат и перенести диагностические коды."""
    normalized = nfc(text)
    report = assess(normalized)
    result.text = normalized
    result.encoding = encoding
    result.confidence = confidence
    result.quality = report.score if quality is None else quality
    result.bom = bom
    result.warnings.extend(report.warnings)
    for code in report.statuses:
        result.add_status(code)
    if result.quality < QUALITY_THRESHOLD:
        result.add_status(Status.ENCODING_UNCERTAIN)
    return result


def read_text_file(path, *, limit: int = 0, declared: str = "") -> DecodeResult:
    """Прочитать текстовый файл целиком или частично и декодировать его."""
    with open(path, "rb") as handle:
        data = handle.read(limit) if limit > 0 else handle.read()
    return decode_bytes(data, declared=declared)
