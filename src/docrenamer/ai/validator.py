"""Проверка ответа локальной модели (разделы 36, 37 ТЗ).

**LLM не является источником фактов.** Каждое значение обязано подтверждаться
дословным фрагментом INPUT. Значения без подтверждения отбрасываются.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from docrenamer.textquality import comparison_key
from docrenamer.types import Status, nfc

#: Поля-объекты вида {"value": ..., "confidence": ..., "evidence": ...}.
SCALAR_FIELDS = ("document_type", "document_date", "document_number", "subject")

#: Классифицирующие поля: их значение — это ярлык, выведенный из текста, а не
#: дословная цитата. Для них требуется, чтобы подтверждение присутствовало в
#: INPUT дословно, а основы слов значения находились в тексте.
CLASSIFICATION_FIELDS = ("document_type", "subject")

#: Минимальная доля основ слов значения, которые обязаны найтись в INPUT.
MIN_STEM_COVERAGE = 0.6

#: Длина основы слова для сравнения (падежные окончания русского языка).
STEM_LENGTH = 6
#: Поля-списки.
LIST_FIELDS = ("case_numbers", "main_persons", "main_organizations")

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(slots=True)
class ValidatedAnswer:
    """Проверенный ответ модели."""

    values: dict[str, Any] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    raw: str = ""

    def add_status(self, code: str | Status) -> None:
        value = code.value if isinstance(code, Status) else str(code)
        if value not in self.statuses:
            self.statuses.append(value)


def extract_json(raw: str) -> dict[str, Any] | None:
    """Найти и разобрать JSON-объект в выводе модели."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = text.rsplit("```", 1)[0]
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize(text: str) -> str:
    """Ключ для сравнения значения с исходным текстом."""
    return _NON_WORD_RE.sub("", comparison_key(nfc(text)))


def evidence_supported(value: str, evidence: str, source_text: str) -> bool:
    """Подтверждается ли значение дословным фрагментом INPUT.

    Проверяются оба условия: сам фрагмент должен присутствовать в INPUT и
    содержать значение (либо значение должно встречаться в INPUT напрямую).
    """
    if not value:
        return False
    haystack = _normalize(source_text)
    needle = _normalize(str(value))
    if not needle:
        return False
    if needle in haystack:
        return True
    snippet = _normalize(evidence or "")
    return bool(snippet) and snippet in haystack and needle in snippet


def classification_supported(value: str, evidence: str, source_text: str) -> bool:
    """Подтверждён ли классифицирующий ярлык (тип документа, предмет).

    Значение не обязано присутствовать дословно: «Постановление судебного
    пристава» выводится из заголовка и упоминания пристава-исполнителя. Но
    подтверждение обязано быть дословной цитатой из INPUT, а основы слов
    значения — присутствовать в тексте. Выдуманный ярлык такую проверку не
    проходит.
    """
    if not value:
        return False
    haystack = _normalize(source_text)
    if not haystack:
        return False
    snippet = _normalize(evidence or "")
    if not snippet or snippet not in haystack:
        return False

    tokens = [t for t in _NON_WORD_RE.split(comparison_key(nfc(value))) if len(t) >= 4]
    if not tokens:
        return _normalize(value) in haystack
    hits = sum(1 for token in tokens if token[:STEM_LENGTH] in haystack)
    return hits / len(tokens) >= MIN_STEM_COVERAGE


def _date_supported(value: str, source_text: str) -> bool:
    """Проверка даты: в тексте должны присутствовать её составляющие."""
    if not _DATE_RE.match(value):
        return False
    year, month, day = value.split("-")
    haystack = source_text
    if value in haystack:
        return True
    numeric = f"{int(day):02d}.{int(month):02d}.{year}"
    if numeric in haystack or f"{int(day)}.{int(month)}.{year}" in haystack:
        return True
    from docrenamer.extractors.dates import extract_dates

    return any(c.value == value for c in extract_dates(haystack))


def validate(raw_output: str, source_text: str) -> ValidatedAnswer:
    """Проверить ответ модели по схеме и по наличию подтверждений."""
    answer = ValidatedAnswer(raw=raw_output)
    payload = extract_json(raw_output)
    if payload is None:
        answer.add_status(Status.INVALID_AI_JSON)
        return answer

    for name in SCALAR_FIELDS:
        entry = payload.get(name)
        parsed = _parse_scalar(entry)
        if parsed is None:
            continue
        value, confidence, evidence = parsed
        if name == "document_date":
            supported = _date_supported(value, source_text)
        elif name in CLASSIFICATION_FIELDS:
            supported = classification_supported(value, evidence, source_text)
        else:
            supported = evidence_supported(value, evidence, source_text)
        if not supported:
            answer.rejected.append(f"{name}={value}")
            answer.add_status(Status.AI_EVIDENCE_REJECTED)
            continue
        answer.values[name] = {
            "value": value,
            "confidence": confidence,
            "evidence": evidence or value,
        }

    for name in LIST_FIELDS:
        items = payload.get(name)
        if not isinstance(items, list):
            continue
        accepted: list[dict[str, Any]] = []
        for item in items[:10]:
            parsed_item = _parse_list_item(item)
            if parsed_item is None:
                continue
            value, confidence, evidence, role = parsed_item
            if not evidence_supported(value, evidence, source_text):
                answer.rejected.append(f"{name}={value}")
                answer.add_status(Status.AI_EVIDENCE_REJECTED)
                continue
            accepted.append(
                {
                    "value": value,
                    "confidence": confidence,
                    "evidence": evidence or value,
                    "role": role,
                }
            )
        if accepted:
            answer.values[name] = accepted

    return answer


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, number))


def _parse_scalar(entry: Any) -> tuple[str, float, str] | None:
    """Привести поле к ``(значение, уверенность, подтверждение)``."""
    if entry is None:
        return None
    if isinstance(entry, str):
        value, confidence, evidence = entry, 0.5, ""
    elif isinstance(entry, dict):
        raw_value = entry.get("value")
        if raw_value is None:
            return None
        value = str(raw_value)
        confidence = _clamp_confidence(entry.get("confidence", 0.5))
        evidence = str(entry.get("evidence") or "")
    else:
        return None
    value = nfc(value).strip()
    if not value or value.lower() in ("null", "none", "n/a", "-"):
        return None
    return value[:200], confidence, evidence[:400]


def _parse_list_item(item: Any) -> tuple[str, float, str, str] | None:
    """Привести элемент списка к ``(значение, уверенность, подтверждение, роль)``."""
    if isinstance(item, str):
        value = nfc(item).strip()
        return (value[:200], 0.5, "", "") if value else None
    if not isinstance(item, dict):
        return None
    raw_value = item.get("value") or item.get("name") or item.get("number")
    if raw_value is None:
        return None
    value = nfc(str(raw_value)).strip()
    if not value:
        return None
    return (
        value[:200],
        _clamp_confidence(item.get("confidence", 0.5)),
        str(item.get("evidence") or "")[:400],
        str(item.get("role") or "")[:40],
    )
