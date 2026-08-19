"""Сведения для окна выбора папки: что в ней лежит и с чего начинать обзор.

Окно выбора — первое, что видит человек, и оно обязано работать на любой
папке: и на пустой, и на закрытой правами, и на той, где тысячи файлов.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docrenamer.browsing import (
    FILE_FORMS,
    Listing,
    has_subdirectories,
    list_directory,
    path_chain,
    plural,
    quick_roots,
    start_folder,
    subdirectories,
    summary,
)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Папка с документами и двумя вложенными папками."""
    directory = tmp_path / "Дело Петрова"
    (directory / "Сканы").mkdir(parents=True)
    (directory / "Том 1").mkdir()
    (directory / "иск.pdf").write_bytes(b"%PDF-1.4\n")
    (directory / "Договор займа №17.docx").write_bytes(b"PK\x03\x04")
    (directory / "ёжик.txt").write_text("текст", encoding="utf-8")
    return directory


def test_folders_first_then_files(folder: Path) -> None:
    """Сначала папки, потом файлы — как в проводнике."""
    listing = list_directory(folder)
    names = [entry.name for entry in listing.entries]
    assert names == ["Сканы", "Том 1", "Договор займа №17.docx", "иск.pdf", "ёжик.txt"]
    assert [entry.is_dir for entry in listing.entries][:2] == [True, True]


def test_counts_and_summary(folder: Path) -> None:
    """Сводка под списком считает папки и файлы по-русски."""
    listing = list_directory(folder)
    assert (listing.folders, listing.files) == (2, 3)
    assert summary(listing) == "В папке: 2 папки, 3 файла"


def test_file_size_and_time_are_read(folder: Path) -> None:
    """У файла видны размер и время — по ним и узнают нужную папку."""
    listing = list_directory(folder)
    document = next(entry for entry in listing.entries if entry.name == "иск.pdf")
    assert document.size == len(b"%PDF-1.4\n")
    assert document.mtime > 0
    folder_entry = next(entry for entry in listing.entries if entry.name == "Сканы")
    assert folder_entry.size == 0


def test_empty_folder(tmp_path: Path) -> None:
    listing = list_directory(tmp_path)
    assert listing.entries == ()
    assert summary(listing) == "Папка пуста."


def test_missing_folder_is_explained_not_raised(tmp_path: Path) -> None:
    """Пропавшая папка — не сбой программы, а строка с пояснением."""
    listing = list_directory(tmp_path / "нет такой")
    assert listing.error == "Папки больше нет."
    assert summary(listing) == "Папки больше нет."


def test_file_instead_of_folder(tmp_path: Path) -> None:
    document = tmp_path / "иск.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    listing = list_directory(document)
    assert listing.error is not None


def test_closed_folder_is_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Папку без прав доступа окно показывает пояснением, а не падением.

    Права подменяются, а не выставляются на диске: под администратором
    chmod ничего не запрещает, и тест был бы обманчивым.
    """

    def deny(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "scandir", deny)
    listing = list_directory(tmp_path)
    assert listing.error == "Папка закрыта правами доступа."


def test_long_listing_is_cut_but_counted(tmp_path: Path) -> None:
    """В папке на тысячи файлов показывается начало, но счёт полный."""
    for index in range(50):
        (tmp_path / f"скан_{index:03}.jpg").write_bytes(b"\xff\xd8\xff")
    listing = list_directory(tmp_path, limit=10)
    assert len(listing.entries) == 10
    assert listing.files == 50
    assert listing.hidden == 40
    assert "показаны первые 10" in summary(listing)


def test_subdirectories_and_arrow(folder: Path) -> None:
    """Дерево раскрывает только то, что есть чем раскрыть."""
    assert [path.name for path in subdirectories(folder)] == ["Сканы", "Том 1"]
    assert has_subdirectories(folder) is True
    assert has_subdirectories(folder / "Сканы") is False
    assert has_subdirectories(folder / "нет такой") is False


def test_plural_forms() -> None:
    """1 файл, 2 файла, 5 файлов, 11 файлов, 21 файл."""
    assert [plural(count, FILE_FORMS) for count in (1, 2, 5, 11, 14, 21, 102)] == [
        "файл",
        "файла",
        "файлов",
        "файлов",
        "файлов",
        "файл",
        "файла",
    ]


def test_quick_roots_include_home() -> None:
    """Обзор начинается с домашней папки: документы чаще всего там."""
    roots = quick_roots()
    assert roots, "начала обзора не найдены"
    assert Path.home() in [path for _label, path in roots]
    assert len({path for _label, path in roots}) == len(roots)


def test_partial_listing_says_so() -> None:
    """Оборванный по пределу обход честно сообщает, что показано не всё."""
    listing = Listing(
        path=Path("."), entries=(), folders=0, files=20_000, hidden=0, partial=True
    )
    assert "показаны не все" in summary(listing)


def test_chain_leads_from_root_to_folder(tmp_path: Path) -> None:
    """Дерево раскрывается по цепочке: от начала обзора до нужной папки."""
    deep = tmp_path / "Дело Петрова" / "Том 1" / "Сканы"
    deep.mkdir(parents=True)

    chain = path_chain(deep, [("Начало", tmp_path)])

    assert chain == [
        tmp_path,
        tmp_path / "Дело Петрова",
        tmp_path / "Дело Петрова" / "Том 1",
        deep,
    ]


def test_chain_of_the_root_itself(tmp_path: Path) -> None:
    assert path_chain(tmp_path, [("Начало", tmp_path)]) == [tmp_path]


def test_chain_is_empty_for_outside_path(tmp_path: Path) -> None:
    """Папка вне известных начал обзора цепочки не имеет — и это не ошибка."""
    assert path_chain(Path("/нет/такого/пути"), [("Начало", tmp_path)]) == []


def test_start_folder_prefers_previous(tmp_path: Path) -> None:
    """Окно открывается там, где работали в прошлый раз."""
    assert start_folder(tmp_path) == tmp_path


def test_start_folder_falls_back_home(tmp_path: Path) -> None:
    """Прошлой папки больше нет — открывается домашняя."""
    assert start_folder(tmp_path / "нет такой") == Path.home()
    assert start_folder(None) == Path.home()
