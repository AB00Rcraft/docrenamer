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


#: Номер в конце имени: «IMG_5608», «scan001», «doc-12».
SCAN_TAIL_RE = re.compile(r"^(?P<rest>.*?)(?P<num>\d{1,6})$")

#: Номер в начале имени: «1 Иск Шахманова», «01_скан», просто «1». Сканеры и
#: люди нумеруют страницы именно так, и это тоже порядок, а не случайность.
SCAN_HEAD_RE = re.compile(r"^(?P<num>\d{1,6})(?P<rest>.*)$")

#: Насколько далеко могут отстоять номера соседних страниц. Один-два пропуска
#: — это обычное дело: неудачный кадр удалили, а порядок остался прежним.
MAX_SCAN_GAP = 3


@dataclass(frozen=True, slots=True)
class ScanPage:
    """Место файла в подряд отснятой пачке страниц."""

    group: str
    number: int
    page: int
    total: int
    #: Номер стоял в начале имени («1 Иск») или в конце («IMG_5608»).
    position: str = "tail"

    @property
    def segment(self) -> str:
        """Обозначение страницы в имени.

        Номер дополняется нулями до ширины последнего: тогда сортировка по
        имени совпадает с порядком страниц и «стр_10» не встаёт перед «стр_2».
        """
        width = len(str(self.total))
        return f"стр_{self.page:0{width}d}"

    @property
    def numbered_from_one(self) -> bool:
        """Нумерация начата с первой страницы, а не с номера кадра камеры."""
        return self.number - self.page in (0, 1)

    def to_dict(self) -> dict[str, object]:
        return {
            "group": self.group,
            "number": self.number,
            "page": self.page,
            "total": self.total,
            "position": self.position,
            "segment": self.segment,
        }


def _split_number(stem: str) -> list[tuple[str, str, str]]:
    """Разложить имя на номер и остаток обоими способами.

    Возвращает пары ``(положение, остаток, цифры)``. Одно и то же имя может
    читаться двояко — «20260818_142203» и как номер в начале, и как номер в
    конце. Какое прочтение верное, решает группировка: настоящая пачка
    страниц даст более длинный ряд.
    """
    variants: list[tuple[str, str, str]] = []
    head = SCAN_HEAD_RE.match(stem)
    if head is not None:
        variants.append(("head", head.group("rest"), head.group("num")))
    tail = SCAN_TAIL_RE.match(stem)
    if tail is not None:
        variants.append(("tail", tail.group("rest"), tail.group("num")))
    return variants


def detect_scan_pages(paths: Iterable[Path]) -> dict[Path, ScanPage]:
    """Найти пачки сканов: подряд пронумерованные файлы одного каталога.

    Страницы снимают и сканируют одну за другой, поэтому их порядок записан в
    именах: ``1 Иск``, ``2 Иск`` или ``IMG_5608``, ``IMG_5609``. Сам номер
    ничего не значит — важен порядок, поэтому страницы нумеруются заново, с
    первой.

    Одного имени мало, чтобы объявить файлы страницами документа: подряд
    снятые кадры отпуска выглядят точно так же. Решение принимается выше, по
    содержимому файлов.
    """
    groups: dict[tuple[str, str, str, str, int], list[tuple[int, Path]]] = {}
    for path in paths:
        stem = path.stem.strip()
        for position, rest, digits in _split_number(stem):
            # Ширина номера — часть образца: «01» и «1» нумеровали по-разному.
            key = (
                str(path.parent),
                path.suffix.lower(),
                position,
                comparison_key(rest),
                len(digits),
            )
            groups.setdefault(key, []).append((int(digits), path))

    #: Каждый файл попадает в ту пачку, где ряд длиннее: это и есть верное
    #: прочтение его имени.
    best: dict[Path, ScanPage] = {}
    for key, members in groups.items():
        members.sort()
        runs: list[list[tuple[int, Path]]] = [[members[0]]]
        for number, path in members[1:]:
            if number == runs[-1][-1][0]:
                continue
            if number - runs[-1][-1][0] <= MAX_SCAN_GAP:
                runs[-1].append((number, path))
            else:
                runs.append([(number, path)])
        for index, run in enumerate(runs):
            if len(run) < 2:
                continue
            group_key = f"{key[0]}|{key[1]}|{key[2]}|{key[3]}|{key[4]}|{index}"
            for page, (number, path) in enumerate(run, start=1):
                candidate = ScanPage(
                    group=group_key,
                    number=number,
                    page=page,
                    total=len(run),
                    position=key[2],
                )
                current = best.get(path)
                if current is None or candidate.total > current.total:
                    best[path] = candidate
    return best
