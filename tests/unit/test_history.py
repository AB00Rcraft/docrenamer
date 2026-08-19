"""Повторный запуск не гоняет папку по кругу.

Программа помнит свою работу по manifest'ам: файл, которому она уже давала
имя, узнаётся по контрольной сумме и по имени.
"""

from __future__ import annotations

import json
from pathlib import Path

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.history import RenameHistory
from docrenamer.paths import AppPaths
from docrenamer.types import Status
from tests.fixtures import builders


def write_manifest(app_paths: AppPaths, name: str, digest: str) -> Path:
    path = app_paths.manifests_dir / "rename_manifest_2026-08-19_101010.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "kind": "file",
                        "status": "RENAMED",
                        "new_filename": name,
                        "sha256_after": digest,
                        "timestamp": "2026-08-19T10:10:10Z",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_history_recognizes_by_hash_and_name(app_paths: AppPaths) -> None:
    write_manifest(app_paths, "Договор_18.08.2026.docx", "a" * 64)

    history = RenameHistory.load(app_paths.manifests_dir)

    assert history.renamed_on("любое имя.docx", "a" * 64)
    assert history.renamed_on("Договор_18.08.2026.docx")
    assert not history.renamed_on("другой файл.docx", "b" * 64)


def test_already_renamed_file_is_marked(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Файл, переименованный раньше, показывается, но не отмечается."""
    source = builders.make_docx(workdir / "договор.docx")
    app = Application(config, paths=app_paths)
    digest = app.preview(workdir).items[0].sha256
    write_manifest(app_paths, source.name, digest)

    plan = Application(config, paths=app_paths).preview(workdir)
    item = plan.items[0]

    assert item.status == Status.ALREADY_RENAMED.value
    assert not item.selected
    assert "Уже переименован" in item.message


def test_only_new_mode_hides_them(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """В режиме «только новые» разобранные прежде файлы в план не попадают."""
    source = builders.make_docx(workdir / "договор.docx")
    builders.make_text(workdir / "иск.txt", "ИСКОВОЕ ЗАЯВЛЕНИЕ\nИстец: Иванов Иван Иванович\n")
    app = Application(config, paths=app_paths)
    digest = next(i for i in app.preview(workdir).items if i.source_path == source).sha256
    write_manifest(app_paths, source.name, digest)
    config.naming.skip_already_renamed = True

    plan = Application(config, paths=app_paths).preview(workdir)

    assert [item.source_path.name for item in plan.items] == ["иск.txt"]
