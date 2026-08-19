"""Разбор пачками и отбор по сроку.

На папке в тысячи файлов человек не должен ждать общего итога: имена первых
файлов можно проверять, пока программа разбирает остальные. Но пачка не имеет
права разорвать серию страниц или предложить имя, уже занятое прошлой пачкой.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from docrenamer.app import Application, batch_key, split_batches
from docrenamer.scanner import PERIODS, filter_by_period, period_days
from docrenamer.types import ScannedFile


def scanned(path: Path, *, mtime: float = 0.0) -> ScannedFile:
    return ScannedFile(path=path, size=10, mtime=mtime, extension=path.suffix)


# --- пачки -----------------------------------------------------------------


def test_batches_are_cut_by_size(tmp_path: Path) -> None:
    """Пачка набирается до заданного размера и режется по смене имени."""
    names = ("иск", "отзыв", "акт", "справка", "письмо", "договор", "жалоба")
    files = [scanned(tmp_path / f"{name}.pdf") for name in names]

    batches = list(split_batches(files, 3))

    assert [len(batch) for batch in batches] == [3, 3, 1]


def test_series_is_not_torn_apart(tmp_path: Path) -> None:
    """Страницы одного скана остаются в одной пачке.

    Иначе программа перестанет узнавать их как один документ: разрыв по
    номеру превратил бы «стр. 1–8» в две разные пачки страниц.
    """
    files = [scanned(tmp_path / "договор.pdf")]
    files += [scanned(tmp_path / f"скан_{index}.jpg") for index in range(1, 9)]

    batches = list(split_batches(files, 3))
    where = {file.path.name: index for index, batch in enumerate(batches) for file in batch}

    assert len({where[f"скан_{index}.jpg"] for index in range(1, 9)}) == 1


def test_folders_are_not_torn_apart(tmp_path: Path) -> None:
    """Резать пачку можно на границе папки, а не посреди неё."""
    files = [scanned(tmp_path / "Дело А" / f"{name}.pdf") for name in ("иск", "отзыв")]
    files += [scanned(tmp_path / "Дело Б" / f"{name}.pdf") for name in ("акт", "справка")]

    batches = list(split_batches(files, 3))

    assert [file.path.parent.name for file in batches[0]] == ["Дело А", "Дело А", "Дело Б"]


def test_huge_series_is_cut_by_the_safety_limit(tmp_path: Path) -> None:
    """Папка из одинаково названных файлов не превращается в одну пачку.

    Серию рвать не хочется, но и ждать первых имён до конца тысячной папки
    человек не должен: предохранитель режет пачку вчетверо больше обычной.
    """
    files = [scanned(tmp_path / f"скан_{index}.jpg") for index in range(1, 60)]

    batches = list(split_batches(files, 5))

    assert len(batches) > 1
    assert all(len(batch) <= 20 for batch in batches)


def test_batch_key_ignores_the_number(tmp_path: Path) -> None:
    assert batch_key(tmp_path / "скан_1.jpg") == batch_key(tmp_path / "скан_7.jpg")
    assert batch_key(tmp_path / "скан_1.jpg") != batch_key(tmp_path / "иск_1.pdf")


# --- срок ------------------------------------------------------------------


def test_period_keeps_recent_files(tmp_path: Path) -> None:
    now = time.time()
    files = [
        scanned(tmp_path / "свежий.txt", mtime=now - 3 * 86400),
        scanned(tmp_path / "старый.txt", mtime=now - 200 * 86400),
    ]

    kept = filter_by_period(files, 30, now=now)

    assert [file.path.name for file in kept] == ["свежий.txt"]


def test_period_zero_keeps_everything(tmp_path: Path) -> None:
    files = [scanned(tmp_path / "старый.txt", mtime=1.0)]

    assert filter_by_period(files, 0) == files


def test_file_without_time_is_kept(tmp_path: Path) -> None:
    """Спрятать файл из-за того, что о нём чего-то не известно, нельзя."""
    files = [scanned(tmp_path / "без времени.txt", mtime=0.0)]

    assert filter_by_period(files, 7) == files


def test_period_names() -> None:
    assert period_days("За неделю") == 7
    assert period_days("За месяц") == 30
    assert period_days("За всё время") == 0
    assert period_days("чего-то такого") == 0
    assert PERIODS[0][1] == 0


# --- сквозной разбор пачками ----------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path, config, app_paths):  # type: ignore[no-untyped-def]
    directory = tmp_path / "Дело"
    directory.mkdir()
    documents = (
        ("иск", "ИСКОВОЕ ЗАЯВЛЕНИЕ"),
        ("отзыв", "ОТЗЫВ на исковое заявление"),
        ("акт", "АКТ приёма-передачи"),
        ("справка", "СПРАВКА"),
        ("письмо", "ПИСЬМО"),
        ("жалоба", "ЖАЛОБА"),
        ("ходатайство", "ХОДАТАЙСТВО"),
    )
    for index, (name, heading) in enumerate(documents, start=1):
        (directory / f"{name}.txt").write_text(
            f"{heading}\n\nот 1{index}.08.2026 в отношении Иванова Ивана Ивановича.",
            encoding="utf-8",
        )
    config.ai.enabled = False
    config.ocr.enabled = False
    return directory, Application(config, paths=app_paths)


def test_preview_comes_in_batches(workspace) -> None:  # type: ignore[no-untyped-def]
    """План приходит частями, а вместе они дают тот же набор файлов."""
    directory, app = workspace

    batches = list(app.preview_batches(directory, batch_size=3))
    files = [item.source_path.name for batch in batches for item in batch.items]

    assert len(batches) > 1
    assert sorted(files) == sorted(path.name for path in directory.glob("*.txt"))


def test_names_do_not_collide_across_batches(tmp_path: Path, config, app_paths) -> None:  # type: ignore[no-untyped-def]
    """Вторая пачка не предложит имя, занятое первой."""
    directory = tmp_path / "Дело"
    directory.mkdir()
    # Одинаковые по содержанию документы дадут одно и то же имя.
    for index in range(4):
        (directory / f"скан{index}.txt").write_text(
            "АКТ\n\nот 01.02.2026 приёма-передачи.", encoding="utf-8"
        )
    config.ai.enabled = False
    config.ocr.enabled = False
    app = Application(config, paths=app_paths)

    batches = list(app.preview_batches(directory, batch_size=1))
    names = [item.proposed_filename for batch in batches for item in batch.items]

    assert len(names) == len(set(names)), names


def test_batched_plan_matches_the_whole_one(workspace) -> None:  # type: ignore[no-untyped-def]
    """Разбор пачками даёт те же имена, что и разбор целиком."""
    directory, app = workspace

    whole = app.preview(directory)
    by_batches = list(app.preview_batches(directory, batch_size=2))

    expected = {item.source_path: item.proposed_filename for item in whole.items}
    got = {
        item.source_path: item.proposed_filename
        for batch in by_batches
        for item in batch.items
    }
    assert got == expected
