"""Общие вспомогательные средства извлечения (раздел 40 ТЗ)."""

from __future__ import annotations

import re

#: Ширина окна контекста вокруг найденного значения.
CONTEXT_WIDTH = 70

_SPACES_RE = re.compile(r"\s+")


def context_window(text: str, start: int, end: int, width: int = CONTEXT_WIDTH) -> str:
    """Фрагмент текста вокруг найденного значения — доказательство (evidence)."""
    left = max(0, start - width)
    right = min(len(text), end + width)
    return _SPACES_RE.sub(" ", text[left:right]).strip()


def head_position_bonus(position: int, length: int, *, window: int = 1500) -> float:
    """Надбавка за расположение ближе к началу документа.

    Реквизиты (заголовок, номер, дата) почти всегда находятся в верхней части
    первой страницы (раздел 41 ТЗ).
    """
    if length <= 0:
        return 0.0
    if position <= window:
        return 0.08 * (1.0 - position / window)
    return 0.0


def dedupe_keep_order(values: list[str]) -> list[str]:
    """Убрать повторы, сохранив порядок появления."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
