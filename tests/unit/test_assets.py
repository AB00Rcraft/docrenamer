"""Фирменный знак (требование приёмки).

Значок должен быть собран, содержать все нужные размеры и быть подключён
к сборке — иначе в системе останется значок по умолчанию.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"

#: Размеры, которые Windows использует в проводнике, на панели задач и в меню.
REQUIRED_SIZES = {16, 24, 32, 48, 64, 128, 256}


def test_icon_contains_all_required_sizes() -> None:
    from PIL import Image

    with Image.open(ASSETS / "icon.ico") as icon:
        sizes = {size[0] for size in icon.info.get("sizes", set())}
    assert REQUIRED_SIZES.issubset(sizes), f"в значке не хватает размеров: {sizes}"


def test_logo_files_exist() -> None:
    for name in ("logo.svg", "logo.png", "logo@512.png", "icon.ico", "make_logo.py"):
        assert (ASSETS / name).is_file(), f"нет файла {name}"


def test_icon_is_visible_on_dark_and_light() -> None:
    """Знак не сливается с фоном: у него собственная тёмная подложка."""
    from PIL import Image

    with Image.open(ASSETS / "logo.png") as logo:
        image = logo.convert("RGBA")
        corner = image.getpixel((4, 4))
        centre = image.getpixel((image.width // 2, image.height // 2))

    assert corner[3] == 0 or sum(corner[:3]) < 200, "углы должны быть прозрачными или тёмными"
    assert sum(centre[:3]) > 200, "в середине знака должен быть светлый лист"


def test_build_uses_the_icon() -> None:
    spec = (ROOT / "DocRenamer.spec").read_text(encoding="utf-8")
    assert 'assets" / "icon.ico"' in spec
    assert '"icon": str(ICON_PATH)' in spec

    installer = (ROOT / "installer" / "DocRenamer.iss").read_text(encoding="utf-8")
    assert "SetupIconFile" in installer


def test_generator_is_reproducible(tmp_path: Path) -> None:
    """Знак собирается кодом: результат воспроизводим."""
    import sys

    sys.path.insert(0, str(ASSETS))
    try:
        from make_logo import draw_logo
    finally:
        sys.path.remove(str(ASSETS))

    first = draw_logo(64).tobytes()
    second = draw_logo(64).tobytes()
    assert first == second


@pytest.mark.parametrize("size", sorted(REQUIRED_SIZES))
def test_logo_renders_at_every_size(size: int) -> None:
    import sys

    sys.path.insert(0, str(ASSETS))
    try:
        from make_logo import draw_logo
    finally:
        sys.path.remove(str(ASSETS))

    image = draw_logo(size)
    assert image.size == (size, size)
    assert image.getbbox() is not None, "знак не должен быть пустым"
