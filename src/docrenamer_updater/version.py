"""Сравнение версий."""

from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse(value: str) -> tuple[int, int, int]:
    """Разобрать строку версии. Непонятное значение считается нулевым."""
    match = _VERSION_RE.match(str(value).strip())
    if not match:
        return (0, 0, 0)
    parts = [int(part) if part else 0 for part in match.groups()]
    return (parts[0], parts[1], parts[2])


def is_newer(candidate: str, current: str) -> bool:
    """Строго новее ли ``candidate`` по сравнению с ``current``."""
    return parse(candidate) > parse(current)
