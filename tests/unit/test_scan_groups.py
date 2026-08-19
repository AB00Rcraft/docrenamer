"""Пачка сканов — один документ, а не восемь разных (разделы 42, 67 ТЗ).

Страницы сканируют подряд, и номер страницы стоит либо в начале имени, либо в
конце. Такая пачка обязана получить одно имя на всех, различающееся только
номером страницы, иначе документ рассыпается на восемь несвязанных файлов.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.extractors.series import detect_scan_pages
from docrenamer.paths import AppPaths
from tests.fixtures import builders

ISK_PAGE1 = (
    "В Пресненский районный суд города Москвы\n\nИСКОВОЕ ЗАЯВЛЕНИЕ\n"
    "о взыскании задолженности\n\nИстец: Шахманова Мария Петровна\n"
    "Ответчик: ООО «Альфа»\n\nДело № 2-1183/2026\n"
    "12 мая 2026 года между сторонами заключён договор займа.\n"
)
ISK_NEXT = (
    "продолжение искового заявления. Ответчик уклоняется от исполнения\n"
    "обязательств, что подтверждается перепиской и актом сверки расчётов\n"
    "от 3 июня 2026 года. Просим суд взыскать сумму долга полностью.\n"
)


def preview_names(config: Config, app_paths: AppPaths, workdir: Path) -> dict[str, str]:
    app = Application(config, paths=app_paths)
    plan = app.preview(workdir, recursive=True)
    return {
        str(item.source_path.relative_to(workdir)): item.proposed_filename
        for item in plan.items
        if item.is_rename
    }


def test_leading_number_is_a_page_number() -> None:
    """«1 Иск», «2 Иск» — это страницы, а не разные документы."""
    paths = [Path("/дело") / f"{number} Иск Шахманова.pdf" for number in (1, 2, 3)]

    pages = detect_scan_pages(paths)

    assert {p.name: pages[p].page for p in paths} == {
        "1 Иск Шахманова.pdf": 1,
        "2 Иск Шахманова.pdf": 2,
        "3 Иск Шахманова.pdf": 3,
    }
    assert all(page.total == 3 for page in pages.values())


def test_bare_numbers_are_pages() -> None:
    """Сканеры часто дают просто «1.pdf», «2.pdf» — это тоже порядок."""
    paths = [Path("/дело") / f"{number}.pdf" for number in range(1, 9)]

    pages = detect_scan_pages(paths)

    assert len(pages) == 8
    assert pages[paths[-1]].page == 8


@pytest.mark.parametrize("naming", ["{n}.pdf", "{n} Иск.pdf", "скан_{n}.pdf"])
def test_pages_share_one_name(
    config: Config, app_paths: AppPaths, workdir: Path, naming: str
) -> None:
    """Все страницы получают одно имя и различаются только номером."""
    for number in range(1, 9):
        text = ISK_PAGE1 if number == 1 else ISK_NEXT
        builders.make_pdf_with_text(workdir / naming.format(n=number), text)

    names = preview_names(config, app_paths, workdir)

    assert len(names) == 8, names
    bases = {name.split("_стр_")[0] for name in names.values()}
    assert len(bases) == 1, names
    assert bases.pop().startswith("Иск"), names
    assert sorted(names.values()) == [names[naming.format(n=i)] for i in range(1, 9)]


def test_folder_of_scans_gets_a_name(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Папка со сканами одного документа тоже получает осмысленное имя."""
    inner = workdir / "Новая папка (2)"
    inner.mkdir()
    for number in range(1, 9):
        builders.make_pdf_with_text(
            inner / f"{number}.pdf", ISK_PAGE1 if number == 1 else ISK_NEXT
        )

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir, recursive=True)
    folders = [item for item in plan.items if item.is_folder and item.is_rename]

    assert folders, "папка со сканами осталась без предложения"
    assert folders[0].proposed_filename.startswith("Иск"), folders[0].proposed_filename


def test_ordinary_photos_are_not_pages(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Подряд снятые кадры без текста страницами не объявляются."""
    for number in range(1, 4):
        builders.make_jpeg_with_exif(workdir / f"{number}.jpg")

    names = preview_names(config, app_paths, workdir)

    assert all("стр" not in name for name in names.values()), names
