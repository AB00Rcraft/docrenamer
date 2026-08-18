"""Сохранение осмысленных имён и многотомные документы.

Два правила, сформулированные при приёмке:

* если человек уже назвал файл по-русски и по делу — это имя не ломается,
  максимум дополняется датой по единому образцу;
* файлы, отличающиеся только номером, — это части одного документа, и номер
  части обязан сохраниться.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.extractors.series import detect_series, split_part
from docrenamer.naming.builder import is_meaningful_stem
from docrenamer.paths import AppPaths
from docrenamer.types import Status

DOCUMENT = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "№ 859189755/7728 от 27 июля 2026 года\n"
    "Должник: Иванов Иван Иванович\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
)

UNDATED = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "Должник: Иванов Иван Иванович\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
)


def analyses_by_name(app: Application, directory: Path) -> dict[str, object]:
    return {a.source_path.name: a for a in app.analyze(app.scan(directory))}


# --- какие имена считаются осмысленными ------------------------------------


@pytest.mark.parametrize(
    "stem",
    [
        "Договор займа №17 от 18 августа 2026 года",
        "Постановление Иванова И.И.",
        "Акт сверки с ООО Альфа",
        "отчет за 2026 год",
        "Дело Петрова 1",
        "Постановление",
    ],
)
def test_human_names_are_recognized(stem: str) -> None:
    assert is_meaningful_stem(stem)


@pytest.mark.parametrize(
    "stem",
    [
        "IMG_0032",
        "scan0007",
        "DSC_1234",
        "VID_3871",
        "20260818_142203",
        "8f3a91c2e4b7",
        "Новый документ",
        "Новый документ 2",
        "Untitled document",
        "Документ1",
        "1",
        "",
    ],
)
def test_machine_names_are_not_protected(stem: str) -> None:
    assert not is_meaningful_stem(stem)


# --- сохранение хорошего имени ---------------------------------------------


def test_good_name_with_date_is_left_alone(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Имя осмысленное и дата в нём уже есть — файл не трогаем вовсе."""
    name = "Постановление от 27 июля 2026 года.txt"
    (workdir / name).write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    assert plan.items[0].proposed_filename == name
    assert not plan.items[0].selected
    assert plan.items[0].status == Status.NAME_UNCHANGED.value


def test_good_name_is_only_prefixed_with_date(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Единственное дополнение — дата в начале. Текст имени не переписывается."""
    (workdir / "Постановление по делу Иванова.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename == "2026-07-27__Постановление по делу Иванова.txt"
    assert item.selected


def test_preserved_name_keeps_spaces_and_typography(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Пробелы, «№», кавычки и регистр остаются такими же, как их задал человек."""
    (workdir / "Договор займа №17 «Альфа».txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert "Договор займа №17 «Альфа»" in item.proposed_filename
    assert item.proposed_filename.startswith("2026-07-27__")


def test_technical_name_is_fully_rebuilt(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Техническое имя заменяется полноценным, как и раньше."""
    (workdir / "scan0007.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.startswith("2026-07-27__Постановление-СПИ__")
    assert "652102-26-77028-ИП" in item.proposed_filename


def test_preservation_can_be_disabled(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    config.naming.preserve_good_names = False
    (workdir / "Постановление по делу Иванова.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert "Постановление-СПИ" in item.proposed_filename


def test_filesystem_date_does_not_touch_good_name(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Дата из файловой системы — не повод дополнять хорошее имя."""
    (workdir / "Заметки по встрече с подрядчиком.txt").write_bytes(
        "Обсудили сроки и смету, дата не указана".encode()
    )

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename in ("", "Заметки по встрече с подрядчиком.txt")
    assert not item.selected


# --- многотомные документы --------------------------------------------------


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("Дело Петрова 1", ("Дело Петрова", 1, "")),
        ("Договор том 2", ("Договор", 2, "том")),
        ("Отчёт часть 3", ("Отчёт", 3, "часть")),
        ("Приложение (2)", ("Приложение", 2, "")),
        ("Акт part 2", ("Акт", 2, "часть")),
        ("Постановление", None),
        ("2", None),
    ],
)
def test_part_number_parsing(stem: str, expected: tuple[str, int, str] | None) -> None:
    assert split_part(stem) == expected


def test_series_requires_at_least_two_parts(tmp_path: Path) -> None:
    single = [tmp_path / "Дело Петрова 1.pdf"]
    assert detect_series(single) == {}


def test_volumes_keep_their_numbers(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Тома не сливаются в одно имя и не перенумеровываются заново."""
    for index in (1, 2, 3):
        (workdir / f"scan_{index}.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    names = {item.source_path.name: item.proposed_filename for item in plan.items}

    assert names["scan_1.txt"].endswith("__1-из-3.txt")
    assert names["scan_2.txt"].endswith("__2-из-3.txt")
    assert names["scan_3.txt"].endswith("__3-из-3.txt")
    # Числовой суффикс разрешения коллизий не появляется: имена и так разные.
    assert not any("__02" in name for name in names.values())


def test_explicit_volume_label_is_kept(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Слово «том» из исходного имени сохраняется, а не заменяется догадкой."""
    (workdir / "scan том 1.txt").write_bytes(DOCUMENT.encode())
    (workdir / "scan том 2.txt").write_bytes(DOCUMENT.encode())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    assert any(item.proposed_filename.endswith("__том-1.txt") for item in plan.items)
    assert any(item.proposed_filename.endswith("__том-2.txt") for item in plan.items)


def test_second_volume_inherits_missing_date_with_visible_source(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Том без шапки берёт дату у соседнего тома — с указанием источника."""
    (workdir / "scan_1.txt").write_bytes(DOCUMENT.encode())
    (workdir / "scan_2.txt").write_bytes(UNDATED.encode())

    app = Application(config, paths=app_paths)
    found = analyses_by_name(app, workdir)
    second = found["scan_2.txt"]

    assert second.document_date is not None
    assert second.document_date.value == "2026-07-27"
    assert "из файла «scan_1.txt»" in second.document_date.evidence
    assert second.document_date.confidence < found["scan_1.txt"].document_date.confidence
    assert second.has_status(Status.SERIES_PART_DETECTED)


def test_volumes_survive_apply_and_undo(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Полный цикл: тома переименованы по порядку и корректно откатываются."""
    for index in (1, 2):
        (workdir / f"scan_{index}.txt").write_bytes(f"{DOCUMENT}\nтом {index}".encode())

    app = Application(config, paths=app_paths)
    report = app.apply(app.preview(workdir))
    renamed = sorted(p.name for p in workdir.iterdir())

    assert report.renamed == 2
    assert renamed[0].endswith("__1-из-2.txt")
    assert renamed[1].endswith("__2-из-2.txt")

    assert report.manifest_path is not None
    app.undo(report.manifest_path)
    assert sorted(p.name for p in workdir.iterdir()) == ["scan_1.txt", "scan_2.txt"]
