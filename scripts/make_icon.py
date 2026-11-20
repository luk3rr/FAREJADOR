# Filename: make_icon.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Generate the Farejador icon from the whole photo of the dog.

Requires Pillow (``python3 -m pip install pillow`` or ``uv run --with pillow python ...``).

    python3 scripts/make_icon.py            # writes docs/img/icon.png and docs/img/icon-128.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "img" / "farejador.jpeg"
OUT = ROOT / "docs" / "img"
SIZE = 1024

AMBER = (240, 165, 40)
NIGHT = (13, 17, 23)
RING = 10
PHOTO_RATIO = 0.86  # share of the icon taken by the photo
PHOTO_RADIUS = 0.14  # corner radius of the photo, as a share of its side


def photo() -> Image.Image:
    """The whole picture, brightened (it is very dark) and padded to a square, never cropped."""
    image = Image.open(SOURCE).convert("RGB")
    image = ImageOps.autocontrast(image, cutoff=0.3)
    image = ImageEnhance.Brightness(image).enhance(1.3)
    image = ImageEnhance.Contrast(image).enhance(1.05)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=3))

    side = max(image.size)
    # The padding is a blurred, stretched copy of the picture, so no edge shows.
    squared = image.resize((side, side)).filter(ImageFilter.GaussianBlur(40))
    squared.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return squared


def rounded_mask(size: int, radius: int) -> Image.Image:
    """Anti-aliased rounded-square mask (drawn at 2x and scaled down)."""
    mask = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * 2 - 1, size * 2 - 1), radius=radius * 2, fill=255
    )
    return mask.resize((size, size), Image.LANCZOS)


def icon() -> Image.Image:
    """Dark rounded square holding the whole photo inside a thin amber border."""
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    background = Image.new("RGBA", (SIZE, SIZE), (*NIGHT, 255))
    glow = Image.new("RGBA", (SIZE, SIZE), (*AMBER, 0))
    ImageDraw.Draw(glow).ellipse(
        (SIZE * 0.08, SIZE * 0.08, SIZE * 0.92, SIZE * 0.92), fill=(*AMBER, 55)
    )
    background.alpha_composite(glow.filter(ImageFilter.GaussianBlur(80)))
    canvas.paste(background, mask=rounded_mask(SIZE, int(SIZE * 0.22)))

    side = int(SIZE * PHOTO_RATIO)
    offset = ((SIZE - side) // 2, (SIZE - side) // 2)
    border = Image.new("RGBA", (side + RING * 2, side + RING * 2), (*AMBER, 255))
    border_mask = rounded_mask(side + RING * 2, int(side * PHOTO_RADIUS) + RING)
    canvas.paste(border, (offset[0] - RING, offset[1] - RING), border_mask)
    framed = photo().resize((side, side), Image.LANCZOS)
    canvas.paste(framed, offset, rounded_mask(side, int(side * PHOTO_RADIUS)))
    return canvas


def save(image: Image.Image) -> None:
    image.save(OUT / "icon.png", optimize=True)
    image.resize((128, 128), Image.LANCZOS).save(OUT / "icon-128.png", optimize=True)
    print("wrote", (OUT / "icon.png").relative_to(ROOT), "and icon-128.png")


if __name__ == "__main__":
    save(icon())
