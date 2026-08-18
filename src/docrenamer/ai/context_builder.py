"""Сборка компактного контекста для локальной модели (раздел 35 ТЗ).

Даже локальной модели не отправляется весь документ: собираются заголовок,
первые содержательные абзацы, резолютивные фрагменты и окрестности найденных
номеров, дат и ФИО.
"""

from __future__ import annotations

import re

from docrenamer.security.limits import Limits
from docrenamer.types import Candidate, FileAnalysis, nfc

#: Сколько символов берём из начала и конца текста.
HEAD_CHARS = 2500
TAIL_CHARS = 1200

#: Ширина окна вокруг найденного кандидата.
SNIPPET_WIDTH = 90

_SPACES_RE = re.compile(r"[ \t]{2,}")
_NEWLINES_RE = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    """Убрать избыточные пробелы, сохранив структуру абзацев."""
    return _NEWLINES_RE.sub("\n\n", _SPACES_RE.sub(" ", nfc(text))).strip()


def _snippets(text: str, candidates: list[Candidate], limit: int = 4) -> list[str]:
    """Фрагменты вокруг кандидатов — по одному на значение."""
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates[:limit]:
        snippet = candidate.context or ""
        if not snippet and candidate.position >= 0:
            start = max(0, candidate.position - SNIPPET_WIDTH)
            snippet = text[start : candidate.position + SNIPPET_WIDTH]
        snippet = _clean(snippet)
        if snippet and snippet not in seen:
            seen.add(snippet)
            result.append(snippet)
    return result


def build_context(analysis: FileAnalysis, text: str, limits: Limits) -> str:
    """Построить блок INPUT для модели."""
    text = _clean(text)
    parts: list[str] = [f"FILE:\n{analysis.source_path.name}", f"TYPE:\n{analysis.detected_type}"]

    title = str(analysis.metadata.get("title") or "").strip()
    if title:
        parts.append(f"DETECTED TITLE:\n{title}")

    head = text[:HEAD_CHARS]
    first_line = next((line.strip() for line in head.splitlines() if line.strip()), "")
    if first_line and first_line != title:
        parts.append(f"FIRST LINE:\n{first_line}")

    date_candidates = analysis.candidates.get("dates", [])
    if date_candidates:
        listed = "\n".join(
            f"{c.value} [{c.role_guess or 'text'}]" for c in date_candidates[:6]
        )
        parts.append(f"DATE CANDIDATES:\n{listed}")

    number_kinds = (
        "enforcement_number",
        "case_number",
        "contract_number",
        "document_number",
        "writ_number",
    )
    numbers: list[str] = []
    for kind in number_kinds:
        for candidate in analysis.candidates.get(kind, [])[:3]:
            numbers.append(f"{candidate.value} [{kind}]")
    if numbers:
        parts.append("NUMBER CANDIDATES:\n" + "\n".join(numbers[:8]))

    persons = analysis.candidates.get("persons", [])
    if persons:
        listed = "\n".join(
            f"{c.value}" + (f" [{c.role_guess}]" if c.role_guess else "") for c in persons[:6]
        )
        parts.append(f"PERSON CANDIDATES:\n{listed}")

    organizations = analysis.candidates.get("organizations", [])
    if organizations:
        parts.append(
            "ORG CANDIDATES:\n" + "\n".join(c.value for c in organizations[:6])
        )

    type_candidates = analysis.candidates.get("document_type", [])
    if type_candidates:
        parts.append(
            "TYPE CANDIDATES:\n" + "\n".join(c.value for c in type_candidates[:5])
        )

    snippets: list[str] = []
    for kind in ("dates", "enforcement_number", "case_number", "persons"):
        snippets.extend(_snippets(text, analysis.candidates.get(kind, []), limit=2))
    if snippets:
        parts.append("SNIPPETS:\n" + "\n---\n".join(snippets[:8]))

    if head:
        parts.append(f"TEXT_HEAD:\n{head}")
    tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
    if tail:
        parts.append(f"TEXT_TAIL:\n{tail}")

    block = "\n\n".join(parts)
    if len(block) > limits.max_text_chars_for_ai:
        block = block[: limits.max_text_chars_for_ai]
    return block
