"""Генератор фирменного знака DocRenamer.

Знак строится кодом, а не рисуется вручную: так он воспроизводим, а размеры и
цвета берутся из той же палитры, что и интерфейс программы.

Идея знака: лист документа, на котором прежнее нечитаемое имя (пунктирная
серая строка) сменяется понятным (сплошная строка акцентного цвета).

Запуск:  python assets/make_logo.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent

#: Палитра совпадает с интерфейсом (src/docrenamer/gui.py).
BACKGROUND = (27, 32, 39, 255)
PAPER = (238, 242, 247, 255)
PAPER_FOLD = (198, 208, 221, 255)
ACCENT = (79, 163, 255, 255)
MUTED = (150, 160, 175, 255)
FAINT = (196, 205, 217, 255)

#: Рисуем с четырёхкратным запасом и уменьшаем: края получаются гладкими.
SUPERSAMPLE = 4
CANVAS = 256

#: Размеры, которые Windows использует в разных местах интерфейса.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_logo(size: int, *, tile: bool = True) -> Image.Image:
    """Нарисовать знак заданного размера."""
    scale = size * SUPERSAMPLE / CANVAS
    image = Image.new("RGBA", (size * SUPERSAMPLE, size * SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float]:
        return (x1 * scale, y1 * scale, x2 * scale, y2 * scale)

    if tile:
        draw.rounded_rectangle(box(0, 0, 256, 256), radius=56 * scale, fill=BACKGROUND)

    # Лист документа с загнутым уголком.
    page = box(64, 40, 192, 216)
    draw.rounded_rectangle(page, radius=12 * scale, fill=PAPER)
    fold = [
        (156 * scale, 40 * scale),
        (192 * scale, 76 * scale),
        (156 * scale, 76 * scale),
    ]
    draw.polygon(fold, fill=PAPER_FOLD)

    def line(y: float, x1: float, x2: float, color: tuple[int, int, int, int],
             thickness: float = 9) -> None:
        draw.rounded_rectangle(
            box(x1, y, x2, y + thickness), radius=thickness * scale / 2, fill=color
        )

    # Прежнее имя: обрывочная серая строка — по ней ничего не понять.
    for start, end in ((86, 106), (112, 126), (132, 152)):
        line(84, start, end, MUTED, thickness=8)

    # Новое имя: ярлык акцентного цвета, выходящий за край листа. Именно он
    # делает знак узнаваемым: речь не про документ вообще, а про его имя.
    tag_top, tag_bottom = 112.0, 140.0
    tag_left, tag_right = 44.0, 176.0
    point = 22.0
    draw.polygon(
        [
            (tag_left * scale, ((tag_top + tag_bottom) / 2) * scale),
            ((tag_left + point) * scale, tag_top * scale),
            (tag_right * scale, tag_top * scale),
            (tag_right * scale, tag_bottom * scale),
            ((tag_left + point) * scale, tag_bottom * scale),
        ],
        fill=ACCENT,
    )
    # Отверстие ярлыка.
    hole = 5.5
    centre_x, centre_y = (tag_left + point + 12), (tag_top + tag_bottom) / 2
    draw.ellipse(
        box(centre_x - hole, centre_y - hole, centre_x + hole, centre_y + hole),
        fill=BACKGROUND,
    )

    # Остальной текст документа.
    line(158, 86, 168, FAINT, thickness=8)
    line(176, 86, 152, FAINT, thickness=8)
    line(194, 86, 138, FAINT, thickness=8)

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    icon_images = [draw_logo(size) for size in ICON_SIZES]
    icon_path = ROOT / "icon.ico"
    icon_images[-1].save(icon_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])

    draw_logo(256).save(ROOT / "logo.png")
    for size in (32, 40, 48, 64):
        draw_logo(size).save(ROOT / f"logo{size}.png")
    draw_logo(512).save(ROOT / "logo@512.png")
    draw_logo(128, tile=False).save(ROOT / "logo-mark.png")

    print(f"icon.ico: {icon_path.stat().st_size} байт, размеры {ICON_SIZES}")
    print("logo.png, logo@512.png, logo-mark.png готовы")


if __name__ == "__main__":
    main()
