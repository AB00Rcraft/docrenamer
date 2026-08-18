"""Многотомные документы: «Дело 1», «Дело 2» (разделы 42, 67 ТЗ по смыслу).

Одинаковые имена, отличающиеся только номером, почти всегда означают части
одного документа: тома дела, части приложения, страницы одного скана. Такие
файлы нельзя ни сливать в одно имя, ни нумеровать заново — иначе порядок томов
теряется, а числовой суффикс разрешения коллизий (``__02``) выдаст их за
случайно совпавшие файлы.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from docrenamer.textquality import comparison_key

#: Шаблоны номера части. Порядок важен: явные слова проверяются первыми.
PART_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?P<base>.+?)[\s_\-–—]*том[\s_\-.№]*(?P<num>\d{1,3})$", re.IGNORECASE), "том"),
    (
        re.compile(r"^(?P<base>.+?)[\s_\-–—]*част[ья][\s_\-.№]*(?P<num>\d{1,3})$", re.IGNORECASE),
        "часть",
    ),
    (
        re.compile(r"^(?P<base>.+?)[\s_\-–—]*(?:part|vol|volume)[\s_\-.]*(?P<num>\d{1,3})$",
                   re.IGNORECASE),
        "часть",
    ),
    (re.compile(r"^(?P<base>.+?)\s*\((?P<num>\d{1,3})\)$"), ""),
    (re.compile(r"^(?P<base>.+?)[\s_\-]+(?P<num>\d{1,3})$"), ""),
)

#: Максимальный разумный номер части.
MAX_PART_NUMBER = 200


@dataclass(frozen=True, slots=True)
class SeriesInfo:
    """Сведения о принадлежности файла к серии."""

    base: str
    part: int
    total: int
    label: str

    @property
    def segment(self) -> str:
        """Как часть обозначается в имени файла.

        Если в исходном имени было слово «том» или «часть», оно сохраняется.
        Иначе используется нейтральное «N-из-M»: программа не выдумывает, что
        именно нумеровал пользователь.
        """
        if self.label:
            return f"{self.label}_{self.part}"
        return f"{self.part}_из_{self.total}"

    def to_dict(self) -> dict[str, object]:
        return {
            "base": self.base,
            "part": self.part,
            "total": self.total,
            "label": self.label,
            "segment": self.segment,
        }


def split_part(stem: str) -> tuple[str, int, str] | None:
    """Разделить имя на основу и номер части.

    Returns:
        ``(основа, номер, метка)`` либо ``None``, если номера нет.
    """
    text = stem.strip()
    for pattern, label in PART_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        base = match.group("base").strip(" _-–—.")
        number = int(match.group("num"))
        if not base or number <= 0 or number > MAX_PART_NUMBER:
            continue
        # Основа обязана содержать буквы: «1.pdf» и «2.pdf» ничего не сообщают
        # о том, что это части одного документа.
        if not any(ch.isalpha() for ch in base):
            continue
        return base, number, label
    return None


def detect_series(paths: Iterable[Path]) -> dict[Path, SeriesInfo]:
    """Найти группы файлов, отличающихся только номером.

    Группируются файлы одного каталога с одинаковым расширением и одинаковой
    основой имени. Группа признаётся серией, если в ней не меньше двух разных
    номеров.
    """
    groups: dict[tuple[Path, str, str], list[tuple[Path, int, str]]] = {}
    for path in paths:
        parsed = split_part(path.stem)
        if parsed is None:
            continue
        base, number, label = parsed
        key = (path.parent, path.suffix.lower(), comparison_key(base))
        groups.setdefault(key, []).append((path, number, label))

    result: dict[Path, SeriesInfo] = {}
    for (_parent, _suffix, _base_key), members in groups.items():
        numbers = {number for _, number, _ in members}
        if len(numbers) < 2:
            continue
        # Метка берётся из тех имён, где она указана явно.
        labels = [label for _, _, label in members if label]
        label = labels[0] if labels else ""
        total = max(numbers)
        for path, number, _ in members:
            parsed = split_part(path.stem)
            result[path] = SeriesInfo(
                base=parsed[0] if parsed else path.stem,
                part=number,
                total=max(total, len(numbers)),
                label=label,
            )
    return result
