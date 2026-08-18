"""Запасные источники метаданных без внешних программ (разделы 26, 28 ТЗ).

Без ExifTool и ffprobe у фото и видео не было бы даты съёмки. Эти backend'ы
дают приложению осмысленные имена медиафайлов, даже если рядом не разложены
внешние бинарники.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docrenamer.app import Application
from docrenamer.config import Config
from docrenamer.metadata.exiftool import device_label, exif_datetime, gps_pair
from docrenamer.metadata.ffprobe import duration_label, media_datetime
from docrenamer.metadata.mp4_atoms import Mp4Backend, probe_mp4
from docrenamer.metadata.pillow_exif import PillowExifBackend, read_exif
from docrenamer.paths import AppPaths
from tests.fixtures import builders

# --- EXIF средствами Pillow ------------------------------------------------


def test_pillow_reads_exif_datetime_device_and_gps(tmp_path: Path) -> None:
    path = builders.make_jpeg_with_exif(tmp_path / "IMG_7834.jpg")

    values = read_exif(path)

    assert exif_datetime(values) == ("2026-08-03T18:42:17", "DateTimeOriginal")
    assert device_label(values) == "iPhone 16 Pro"
    coordinates = gps_pair(values)
    assert coordinates is not None
    assert coordinates[0] == pytest.approx(55.7558, abs=1e-4)
    assert coordinates[1] == pytest.approx(37.6173, abs=1e-4)
    assert values["ImageWidth"] == 4032


@pytest.mark.parametrize(
    ("make", "model", "expected"),
    [
        ("Apple", "iPhone 16 Pro", "iPhone 16 Pro"),
        ("Canon", "Canon EOS 5D Mark IV", "Canon EOS 5D Mark IV"),
        ("samsung", "SM-G991B", "SM-G991B"),
        ("NIKON", "D850", "NIKON D850"),
        ("", "iPhone 15", "iPhone 15"),
        ("Apple", "", "Apple"),
    ],
)
def test_device_label_variants(make: str, model: str, expected: str) -> None:
    """Название устройства компактно, но не теряет узнаваемости."""
    assert device_label({"Make": make, "Model": model}) == expected


def test_pillow_backend_on_image_without_exif(tmp_path: Path) -> None:
    values = read_exif(builders.make_jpeg(tmp_path / "пустой.jpg"))

    assert exif_datetime(values) == ("", "")
    assert values["ImageWidth"] > 0


def test_pillow_backend_survives_corrupted_file(tmp_path: Path) -> None:
    path = builders.make_corrupted(tmp_path / "битый.jpg", "jpg")
    assert PillowExifBackend().read(path).values == {}


# --- MP4 своими силами -----------------------------------------------------


def test_mp4_atoms_parse_creation_time_duration_and_gps(tmp_path: Path) -> None:
    path = builders.make_mp4(tmp_path / "VID_3871.mp4")

    values = probe_mp4(path)

    assert media_datetime(values) == "2026-08-12T17:48:22"
    assert duration_label(values["duration_seconds"]) == "01m42s"
    assert values["gps"] == [55.7558, 37.6173]
    assert values["has_video"] is True


def test_mp4_backend_ignores_other_formats(tmp_path: Path) -> None:
    path = builders.make_wav(tmp_path / "запись.wav")
    assert Mp4Backend().read(path).values == {}


def test_mp4_parser_survives_garbage(tmp_path: Path) -> None:
    path = tmp_path / "битый.mp4"
    path.write_bytes(b"\x00\x00\x00\x08ftyp" + bytes(range(256)) * 4)
    assert probe_mp4(path).get("creation_time") is None


def test_mp4_parser_rejects_impossible_box_size(tmp_path: Path) -> None:
    """Заявленный размер бокса больше файла не приводит к чтению за границу."""
    path = tmp_path / "лживый.mp4"
    path.write_bytes(b"\xff\xff\xff\xffmoov" + b"\x00" * 16)
    assert probe_mp4(path) == {"has_video": False, "has_audio": False}


# --- сквозной результат ----------------------------------------------------


def test_photo_named_from_exif_without_exiftool(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Фото получает дату съёмки и устройство без внешнего ExifTool."""
    config.allow_system_binaries = False
    builders.make_jpeg_with_exif(workdir / "IMG_7834.jpg")

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    # Формат совпадает с примером раздела 27 ТЗ.
    assert item.proposed_filename == "Фото__iPhone-16-Pro__03.08.2026_18-42-17.jpg"
    assert item.selected
    assert item.confidence >= config.naming.confidence_threshold


def test_video_named_from_container_without_ffprobe(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Видео получает дату и длительность без внешнего ffprobe."""
    config.allow_system_binaries = False
    builders.make_mp4(workdir / "VID_3871.mp4")

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert item.proposed_filename.startswith("Видео__")
    assert item.proposed_filename.endswith("__12.08.2026_17-48-22.mp4")
    assert "01m42s" in item.proposed_filename
    assert item.selected


def test_gps_included_only_when_configured(
    config: Config, app_paths: AppPaths, workdir: Path
) -> None:
    """Координаты попадают в имя только по явной настройке (раздел 27 ТЗ)."""
    config.allow_system_binaries = False
    config.media.include_gps_coordinates = True
    builders.make_jpeg_with_exif(workdir / "IMG_7834.jpg")

    app = Application(config, paths=app_paths)
    item = app.preview(workdir).items[0]

    assert "GPS-55.7558_37.6173" in item.proposed_filename
