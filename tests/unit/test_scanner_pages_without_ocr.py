"""Сканы без распознавания — тоже один документ.

Распознавание устанавливается отдельно, и на многих машинах его нет: восемь
сканов лежат без единой буквы текста. Понять, что это один документ, всё равно
можно — по нумерации и по тому, что сканер, в отличие от камеры, не пишет в
снимок модель аппарата.
"""

from __future__ import annotations

from pathlib import Path

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.paths import AppPaths
from tests.fixtures import builders


def preview_names(config: Config, app_paths: AppPaths, workdir: Path) -> dict[str, str]:
    app = Application(config, paths=app_paths)
    return {a.source_path.name: a.proposed_filename for a in app.analyze(app.scan(workdir))}


def test_scans_share_name_from_folder(
    config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    """Имя берётся с папки: «Иск Шахмановой» → «Иск_Шахмановой_стр_1»."""
    workdir = tmp_path / "Иск Шахмановой"
    workdir.mkdir()
    for number in range(1, 9):
        builders.make_jpeg(workdir / f"скан {number}.jpg")

    names = preview_names(config, app_paths, workdir)

    assert len(names) == 8
    assert names["скан 1.jpg"] == "Иск_Шахмановой_стр_1.jpg"
    assert names["скан 8.jpg"] == "Иск_Шахмановой_стр_8.jpg"


def test_technical_folder_gives_neutral_name(
    config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    """Если и папка названа технически, страницы честно называются сканами."""
    workdir = tmp_path / "Новая папка (2)"
    workdir.mkdir()
    for number in range(1, 5):
        builders.make_jpeg(workdir / f"{number}.jpg")

    names = preview_names(config, app_paths, workdir)

    assert all(name.startswith("Скан_стр_") for name in names.values()), names


def test_camera_photos_are_left_alone(
    config: Config, app_paths: AppPaths, tmp_path: Path
) -> None:
    """Снимки с камеры страницами не объявляются: модель аппарата в них есть."""
    workdir = tmp_path / "Отпуск"
    workdir.mkdir()
    for number in range(1, 5):
        builders.make_jpeg_with_exif(workdir / f"{number}.jpg")

    names = preview_names(config, app_paths, workdir)

    assert all("стр_" not in name for name in names.values()), names
