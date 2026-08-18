"""Определение типа документа по словарю маркеров (раздел 39 ТЗ).

Словарь расширяемый и лежит в ``config/document_types.json``. Более
специфичные типы имеют больший приоритет: «Постановление судебного пристава»
должно побеждать общее «Постановление».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docrenamer.extractors.common import context_window
from docrenamer.textquality import comparison_key
from docrenamer.types import Candidate, Source

#: Заголовок документа обычно находится в первых строках.
TITLE_WINDOW = 1200


@dataclass(slots=True)
class DocumentTypeEntry:
    """Одна запись словаря типов."""

    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    priority: int = 0
    filename_abbreviation: str = ""

    @property
    def abbreviation(self) -> str:
        return self.filename_abbreviation or self.canonical_name


class DocumentTypeMatcher:
    """Сопоставление текста со словарём типов документов."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.entries = [
            DocumentTypeEntry(
                canonical_name=entry["canonical_name"],
                aliases=list(entry.get("aliases", [])),
                markers=list(entry.get("markers", [])),
                priority=int(entry.get("priority", 0)),
                filename_abbreviation=entry.get("filename_abbreviation", ""),
            )
            for entry in entries
        ]

    def match(self, text: str, *, filename: str = "") -> list[Candidate]:
        """Найти подходящие типы документа, отсортированные по убыванию веса."""
        if not text and not filename:
            return []
        haystack = comparison_key(text or "")
        head = haystack[:TITLE_WINDOW]
        name_key = comparison_key(filename or "")

        results: list[Candidate] = []
        for entry in self.entries:
            score = 0.0
            evidence = ""
            position = -1
            hits = 0
            for marker in (*entry.markers, *entry.aliases, entry.canonical_name):
                key = comparison_key(marker)
                if not key:
                    continue
                index = haystack.find(key)
                if index < 0:
                    if name_key and key in name_key:
                        score = max(score, 0.55)
                        evidence = evidence or f"имя файла: {filename}"
                    continue
                hits += 1
                weight = 0.75
                if index < len(head):
                    weight = 0.9
                if _is_line_start(text, index):
                    weight += 0.05
                score = max(score, weight)
                if position < 0 or index < position:
                    position = index
                    evidence = context_window(text, index, index + len(marker))
            if score <= 0:
                continue
            # Дополнительные совпадения маркеров укрепляют уверенность.
            score = min(0.99, score + min(0.06, 0.02 * (hits - 1)))
            results.append(
                Candidate(
                    value=entry.canonical_name,
                    position=position,
                    context=evidence,
                    source=Source.TEXT,
                    role_guess=entry.abbreviation,
                    confidence=score,
                    kind="document_type",
                )
            )

        priorities = {e.canonical_name: e.priority for e in self.entries}
        results.sort(
            key=lambda c: (
                -(c.confidence + priorities.get(c.value, 0) / 500.0),
                c.position if c.position >= 0 else 10**9,
            )
        )
        return results

    def abbreviation_for(self, canonical_name: str) -> str:
        """Сокращение типа для имени файла."""
        for entry in self.entries:
            if entry.canonical_name == canonical_name:
                return entry.abbreviation
        return canonical_name


_LINE_START_RE = re.compile(r"(?:^|\n)\s*$")


def _is_line_start(text: str, index: int) -> bool:
    """Начинается ли совпадение с новой строки — признак заголовка."""
    left = text[max(0, index - 40) : index]
    return bool(_LINE_START_RE.search(left))


def select_document_type(candidates: list[Candidate]) -> Candidate | None:
    """Выбрать наиболее вероятный тип документа."""
    return candidates[0] if candidates else None
