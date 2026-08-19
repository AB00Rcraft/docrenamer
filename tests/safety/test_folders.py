"""Переименование папок (требование приёмки).

Папка — такой же объект файловой системы, и правила для неё те же: не
перемещать, не перезаписывать, не менять содержимое, всё откатывается.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.operations.rename import CriticalSafetyError, rename_directory
from docrenamer.paths import AppPaths
from docrenamer.types import Status

pytestmark = pytest.mark.safety

POSTANOVLENIE = (
    "ПОСТАНОВЛЕНИЕ\n"
    "о возбуждении исполнительного производства\n"
    "№ 859189755/7728 от 27 июля 2026 года\n"
    "Должник: Иванов Иван Иванович\n"
    "Исполнительное производство № 652102/26/77028-ИП\n"
)


@pytest.fixture
def case_folder(workdir: Path) -> Path:
    """Папка с однородными документами по одному делу."""
    folder = workdir / "новая папка (2)"
    folder.mkdir()
    for index in range(4):
        (folder / f"скан{index}.txt").write_bytes(POSTANOVLENIE.encode())
    return folder


# --- транзакция -------------------------------------------------------------


def test_folder_rename_keeps_contents(workdir: Path) -> None:
    folder = workdir / "старая"
    folder.mkdir()
    (folder / "файл.txt").write_bytes("данные".encode())

    outcome = rename_directory(folder, workdir / "Дело_Иванов_2026")

    assert outcome.ok
    assert not folder.exists()
    target = workdir / "Дело_Иванов_2026"
    assert (target / "файл.txt").read_bytes() == "данные".encode()
    assert outcome.record is not None
    assert outcome.record.kind == "folder"


def test_folder_is_never_overwritten(workdir: Path) -> None:
    source = workdir / "первая"
    source.mkdir()
    (source / "а.txt").write_text("A", encoding="utf-8")
    occupied = workdir / "вторая"
    occupied.mkdir()
    (occupied / "б.txt").write_text("Б", encoding="utf-8")

    outcome = rename_directory(source, occupied)

    assert not outcome.ok
    assert (occupied / "б.txt").read_text(encoding="utf-8") == "Б"
    assert (source / "а.txt").exists()


def test_folder_is_not_moved(workdir: Path, tmp_path: Path) -> None:
    folder = workdir / "папка"
    folder.mkdir()
    other = tmp_path / "снаружи"
    other.mkdir()

    outcome = rename_directory(folder, other / "папка")

    assert not outcome.ok
    assert outcome.status == Status.UNSAFE_PATH.value
    assert folder.is_dir()


def test_file_is_not_treated_as_folder(workdir: Path) -> None:
    path = workdir / "файл.txt"
    path.write_text("x", encoding="utf-8")

    outcome = rename_directory(path, workdir / "другое")

    assert not outcome.ok
    assert outcome.status == Status.UNSAFE_PATH.value


def test_content_change_during_rename_is_critical(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Расхождение состава папки до и после — критическая ошибка."""
    import docrenamer.operations.rename as rename_module

    folder = workdir / "папка"
    folder.mkdir()
    (folder / "а.txt").write_text("A", encoding="utf-8")

    def sneaky(source: Path, target: Path) -> str:
        source.rename(target)
        (target / "лишний.txt").write_text("!", encoding="utf-8")
        return "test"

    monkeypatch.setattr(rename_module, "_rename_no_clobber", sneaky)

    with pytest.raises(CriticalSafetyError):
        rename_directory(folder, workdir / "Дело")


# --- сквозной цикл ----------------------------------------------------------


def test_folder_named_after_its_contents(
    config: Config, app_paths: AppPaths, workdir: Path, case_folder: Path
) -> None:
    """Папка получает имя от того, что в ней лежит."""
    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    folder_items = [item for item in plan.items if item.is_folder]

    assert len(folder_items) == 1
    proposed = folder_items[0].proposed_filename
    assert proposed.startswith("Постановление_СПИ_")
    assert "Иванов" in proposed
    assert "4_файлов" in proposed or "652102" in proposed


def test_files_are_renamed_before_folders(
    config: Config, app_paths: AppPaths, workdir: Path, case_folder: Path
) -> None:
    """Сначала файлы, потом папка: иначе пути внутри перестают совпадать."""
    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    for item in plan.items:
        item.selected = item.is_rename

    report = app.apply(plan)

    assert report.failed == 0
    assert not report.critical
    assert not case_folder.exists(), "папка должна быть переименована"
    renamed_folder = next(path for path in workdir.iterdir() if path.is_dir())
    assert len(list(renamed_folder.iterdir())) == 4
    assert all(
        path.name.startswith("Постановление_СПИ_") for path in renamed_folder.iterdir()
    )


def test_undo_restores_folders_and_files(
    config: Config, app_paths: AppPaths, workdir: Path, case_folder: Path
) -> None:
    """Откат возвращает и файлы, и папку — в обратном порядке."""
    before = sorted(path.name for path in case_folder.iterdir())

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    for item in plan.items:
        item.selected = item.is_rename
    report = app.apply(plan)
    assert report.manifest_path is not None

    undo_report = app.undo(report.manifest_path)

    assert undo_report.failed == 0
    assert case_folder.is_dir(), "папка должна вернуть прежнее имя"
    assert sorted(path.name for path in case_folder.iterdir()) == before


def test_manifest_marks_folder_records(
    config: Config, app_paths: AppPaths, workdir: Path, case_folder: Path
) -> None:
    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    for item in plan.items:
        item.selected = item.is_rename
    report = app.apply(plan)
    assert report.manifest_path is not None

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    kinds = {record.get("kind") for record in manifest["records"]}

    assert kinds == {"file", "folder"}


def test_mixed_folder_gets_no_name(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Разнородной папке общий смысл не выдумывается."""
    folder = workdir / "разное"
    folder.mkdir()
    (folder / "скан1.txt").write_bytes(POSTANOVLENIE.encode())
    (folder / "заметка.txt").write_bytes("Просто текст без реквизитов".encode())
    (folder / "данные.json").write_bytes(b'{"a": 1}')

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)
    folder_item = next(item for item in plan.items if item.is_folder)

    assert not folder_item.selected


def test_folder_renaming_can_be_disabled(
    config: Config, app_paths: AppPaths, workdir: Path, case_folder: Path
) -> None:
    config.naming.rename_folders = False

    app = Application(config, paths=app_paths)
    plan = app.preview(workdir)

    assert not any(item.is_folder for item in plan.items)
