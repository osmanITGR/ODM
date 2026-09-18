"""Build the Android launcher icon sources from the Windows app icon.

The arrow is redrawn as geometry rather than upscaled from the 256px original:
scaling that source to 1024px magnifies its stair-stepped edges, which is very
visible on a modern high-density screen. The proportions below are measured
from the original so the two apps still look like the same icon.

Two files are produced because Android uses them for different jobs:

- odm_icon.png: the full square artwork, used for legacy icons on Android 7
  and below, where the launcher does not reshape anything.
- odm_foreground.png: just the arrow on transparency, drawn near full-bleed.
  flutter_launcher_icons applies its own 16% inset when it builds the adaptive
  icon, which is what keeps the glyph inside the launcher's safe zone.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SOURCE = Path(r"D:\1. My Apps\ODM\odm\icons\app.png")
OUT = Path(r"D:\1. My Apps\ODM\android\assets\icon")

CANVAS = 1024
# flutter_launcher_icons wraps the foreground in a 16% inset of its own, which
# already lands the glyph inside the safe zone. Insetting here as well would
# compound the two and leave the arrow visibly undersized, so the foreground is
# drawn close to full-bleed and the generator does the insetting.
FOREGROUND_FILL = 0.92
# Supersample, then downscale: the cheapest way to get clean diagonals.
SCALE = 4


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    blue = sample_plate_colour(Image.open(SOURCE).convert("RGBA"))

    # 1. Full square artwork with the rounded plate, for legacy launchers.
    full = draw_plate(blue)
    full.save(OUT / "odm_icon.png")

    # 2. Adaptive foreground: the arrow alone, centred, on transparency.
    foreground = draw_foreground()
    foreground.save(OUT / "odm_foreground.png")

    print(f"plate colour: {blue}")
    print(f"wrote {OUT / 'odm_icon.png'} and {OUT / 'odm_foreground.png'}")


def sample_plate_colour(source: Image.Image) -> tuple[int, int, int, int]:
    """Read the brand blue from the original, rather than hardcoding it."""
    # A point inside the plate but clear of the white glyph.
    return source.getpixel((source.width // 8, source.height // 2))


def arrow_path(size: float) -> list[tuple[float, float]]:
    """The download glyph, as fractions of a square of the given size.

    Ratios are taken from the Windows icon: a stem two-sevenths wide over a
    head that spans most of the width, with a baseline bar beneath it.
    """
    c = size / 2
    stem_half = size * 0.105
    head_half = size * 0.285
    top = size * 0.045
    shoulder = size * 0.52
    tip = size * 0.78

    return [
        (c - stem_half, top),
        (c + stem_half, top),
        (c + stem_half, shoulder),
        (c + head_half, shoulder),
        (c, tip),
        (c - head_half, shoulder),
        (c - stem_half, shoulder),
    ]


def draw_arrow(canvas: Image.Image, size: float, origin: float) -> None:
    """Draw the arrow and its baseline bar onto an already-supersampled image."""
    draw = ImageDraw.Draw(canvas)
    white = (255, 255, 255, 255)

    points = [(x + origin, y + origin) for x, y in arrow_path(size)]
    draw.polygon(points, fill=white)

    # The bar under the arrow, with rounded ends to match the plate's corners.
    bar_half = size * 0.30
    bar_top = size * 0.855
    bar_height = size * 0.085
    c = size / 2 + origin
    draw.rounded_rectangle(
        [
            (c - bar_half, bar_top + origin),
            (c + bar_half, bar_top + bar_height + origin),
        ],
        radius=bar_height / 2,
        fill=white,
    )


def draw_plate(blue: tuple[int, int, int, int]) -> Image.Image:
    """The full square icon: white glyph on a blue rounded square."""
    big = CANVAS * SCALE
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Matches the corner radius of the original artwork.
    draw.rounded_rectangle(
        [(0, 0), (big - 1, big - 1)], radius=big * 0.195, fill=blue
    )

    # The glyph sits at 62% of the plate, centred.
    glyph = big * 0.62
    draw_arrow(canvas, glyph, (big - glyph) / 2)

    return canvas.resize((CANVAS, CANVAS), Image.LANCZOS)


def draw_foreground() -> Image.Image:
    """The adaptive foreground: the glyph alone, for the generator to inset."""
    big = CANVAS * SCALE
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    glyph = big * FOREGROUND_FILL
    draw_arrow(canvas, glyph, (big - glyph) / 2)

    return canvas.resize((CANVAS, CANVAS), Image.LANCZOS)


if __name__ == "__main__":
    main()
