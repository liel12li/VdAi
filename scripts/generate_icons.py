"""Generate the VdAi app icons (PNG sizes + Windows .ico).

Run once and commit the outputs:
    python scripts/generate_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ACCENT_TOP = (211, 122, 86)
ACCENT_BOTTOM = (122, 59, 42)
SIZE = 512


def draw_icon(size: int = SIZE) -> Image.Image:
    scale = size / SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Vertical gradient background
    grad = Image.new("RGB", (size, size))
    gdraw = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / size
        gdraw.line(
            [(0, y), (size, y)],
            fill=tuple(int(ACCENT_TOP[c] * (1 - t) + ACCENT_BOTTOM[c] * t) for c in range(3)),
        )

    # Rounded-corner mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(110 * scale), fill=255
    )
    img.paste(grad, (0, 0), mask)
    draw = ImageDraw.Draw(img)

    # Film-clapper bar at the top
    bar_top, bar_h = int(86 * scale), int(54 * scale)
    draw.rounded_rectangle(
        [int(96 * scale), bar_top, size - int(96 * scale), bar_top + bar_h],
        radius=int(16 * scale), fill=(255, 250, 243, 235),
    )
    for i in range(4):
        x = int((132 + i * 72) * scale)
        draw.rounded_rectangle(
            [x, bar_top + int(12 * scale), x + int(30 * scale), bar_top + bar_h - int(12 * scale)],
            radius=int(6 * scale), fill=ACCENT_BOTTOM + (255,),
        )

    # Play triangle
    cx, cy = size / 2, size * 0.60
    r = 118 * scale
    draw.polygon(
        [(cx - r * 0.62, cy - r), (cx - r * 0.62, cy + r), (cx + r * 0.95, cy)],
        fill=(255, 250, 243, 245),
    )
    return img


def main() -> None:
    static = ROOT / "vdai" / "web" / "static"
    assets = ROOT / "assets"
    static.mkdir(parents=True, exist_ok=True)

    icon = draw_icon(SIZE)
    icon.save(assets / "icon.png")
    icon.resize((192, 192), Image.LANCZOS).save(static / "icon-192.png")
    icon.resize((512, 512), Image.LANCZOS).save(static / "icon-512.png")
    icon.save(
        assets / "icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"icons written to {assets} and {static}")


if __name__ == "__main__":
    main()
