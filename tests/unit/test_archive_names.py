"""Архивы: хорошее имя сохраняется (раздел 32 ТЗ).

Архив почти всегда называет человек, и это имя точнее любого списка файлов
внутри. Программа лишь дописывает, что внутри архив и что в нём сканы.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.paths import AppPaths


def make_archive(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"\xff\xd8\xff\xe0" + b"0" * 200)
    return path


def preview_names(config: Config, app_paths: AppPaths, workdir: Path) -> dict[str, str]:
    app = Application(config, paths=app_paths)
    return {a.source_path.name: a.proposed_filename for a in app.analyze(app.scan(workdir))}


def test_good_archive_name_is_kept(config: Config, app_paths: AppPaths, workdir: Path) -> None:
    """«иск Шахманова.zip» остаётся собой, с пометкой про сканы."""
    make_archive(workdir / "иск Шахманова.zip", [f"{i}.jpg" for i in range(1, 9)])

    name = preview_names(config, app_paths, workdir)["иск Шахманова.zip"]

    assert "Шахманова" in name, name
    assert "иск" in name.lower(), name
    assert "архив" in name.lower(), name
    assert "скан" in name.lower(), name


def test_technical_archive_name_is_rebuilt(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Техническое имя пересобирается по содержимому, как и раньше."""
    make_archive(workdir / "archive (3).zip", [f"{i}.jpg" for i in range(1, 5)])

    name = preview_names(config, app_paths, workdir)["archive (3).zip"]

    assert name.startswith("Архив"), name
    assert "файлов" in name, name
