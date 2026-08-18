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

#: Сколько первых непустых строк проверяется как возможный заголовок.
TITLE_LINES = 8

#: Длиннее этого заголовок документа не бывает — дальше это уже текст.
MAX_HEADING_CHARS = 90

#: Сколько символов от начала текста ещё считается «верхом» документа.
HEAD_CHARS = 400

#: Вес совпадения в зависимости от того, где и какой маркер найден.
WEIGHT_HEADING = 0.95         # маркер и есть заголовок документа
WEIGHT_HEAD_PHRASE = 0.88     # словосочетание в верхней части документа
WEIGHT_PHRASE = 0.8           # словосочетание где угодно в тексте
WEIGHT_WORD = 0.45            # одиночное общее слово внутри текста
WEIGHT_FILENAME = 0.55        # совпадение только по имени файла

#: Ниже этого порога тип документа не принимается: одного случайного слова
#: в тексте недостаточно, чтобы назвать презентацию определением суда.
MIN_TYPE_CONFIDENCE = 0.6

#: Исключение: документ начинается с названия своего вида. Текстовый слой PDF
#: часто приходит одним сплошным абзацем без переводов строк — заголовок тогда
#: не распознать по форме. Но если документ буквально открывается словом
#: «ДОГОВОР», это и есть его вид. Допуск в пару символов — на кавычки и
#: типографский мусор в начале.
OPENING_WORD_CHARS = 2
OPENING_WORD_CONFIDENCE = 0.7


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
        """Найти подходящие типы документа, отсортированные по убыванию веса.

        Вес совпадения зависит от того, *что* и *где* найдено. Одиночное общее
        слово в глубине текста («определение», «акт», «решение») почти ничего
        не значит: такие слова встречаются в любом документе. Настоящий тип
        документа стоит в заголовке или подтверждается словосочетанием.
        """
        if not text and not filename:
            return []
        haystack = comparison_key(text or "")
        head = haystack[:HEAD_CHARS]
        headings = heading_lines(text or "")
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
                is_phrase = len(marker.split()) > 1
                index = haystack.find(key)
                if index < 0:
                    if name_key and key in name_key and is_phrase:
                        if WEIGHT_FILENAME > score:
                            score = WEIGHT_FILENAME
                            evidence = f"имя файла: {filename}"
                    continue

                hits += 1
                if _matches_heading(key, headings):
                    weight = WEIGHT_HEADING
                elif is_phrase:
                    weight = WEIGHT_HEAD_PHRASE if index < len(head) else WEIGHT_PHRASE
                else:
                    # Одиночное общее слово («акт», «определение», «решение»)
                    # встречается в любом тексте и само по себе типом не является.
                    weight = WEIGHT_WORD

                if weight > score:
                    score = weight
                    position = index
                    evidence = context_window(text, index, index + len(marker))
                elif position < 0:
                    position = index

            if score <= 0:
                continue
            # Несколько разных маркеров одного типа усиливают уверенность.
            score = min(0.99, score + min(0.08, 0.03 * (hits - 1)))
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


def heading_lines(text: str) -> list[str]:
    """Строки в начале документа, похожие на заголовок.

    Заголовок документа — это короткая строка, которая либо целиком является
    названием («ПОСТАНОВЛЕНИЕ»), либо написана прописными буквами
    («ДОГОВОР ЗАЙМА № 17»). Строка «Определение эффективности в исследовании»
    заголовком документа не является, хотя и начинается со слова из словаря.
    """
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip(" \t.;:—–-")
        if not line:
            continue
        if len(line) <= MAX_HEADING_CHARS:
            result.append(line)
        if len(result) >= TITLE_LINES:
            break
    return result


#: Чем может продолжаться заголовок после названия документа:
#: «СЧЁТ-ФАКТУРА № 245», «ПОСТАНОВЛЕНИЕ о возбуждении», «ЖАЛОБА на решение».
HEADING_TAIL_RE = re.compile(
    r"^(?:[№#:()«\"'\-–—,.]|\d|"
    r"(?:от|о|об|обо|по|на|к|ко|за|при|для|в|во|с|со|из)\b)",
    re.IGNORECASE,
)


def _matches_heading(marker_key: str, headings: list[str]) -> bool:
    """Является ли маркер названием документа в одной из первых строк.

    Названием считается строка, которая либо целиком совпадает с маркером,
    либо начинается с него и продолжается служебным «хвостом» — номером,
    предлогом, скобкой. Строка «Определение эффективности в исследовании»
    начинается со словарного слова, но продолжается обычным существительным,
    поэтому названием документа не является.
    """
    for line in headings:
        key = comparison_key(line)
        if key == marker_key:
            return True
        if not key.startswith(marker_key):
            continue
        if line.isupper():
            return True
        tail = line[len(marker_key) :].strip(" \t.,:;—–-")
        if not tail or HEADING_TAIL_RE.match(tail):
            return True
    return False


def select_document_type(candidates: list[Candidate]) -> Candidate | None:
    """Выбрать тип документа, если он подтверждён достаточно уверенно.

    Слабое совпадение лучше отбросить: файл получит имя по другим признакам,
    чем неверный юридический ярлык (раздел 92 ТЗ).
    """
    if not candidates:
        return None
    best = candidates[0]
    if best.confidence >= MIN_TYPE_CONFIDENCE:
        return best
    if 0 <= best.position < OPENING_WORD_CHARS:
        return Candidate(
            value=best.value,
            position=best.position,
            context=best.context,
            source=best.source,
            role_guess=best.role_guess,
            confidence=OPENING_WORD_CONFIDENCE,
            kind=best.kind,
        )
    return None
