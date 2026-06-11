"""Visual helpers: brand color extraction, gradients, Ken Burns motion."""

from __future__ import annotations

import colorsys
from pathlib import Path

import numpy as np
from PIL import Image


def dominant_color(image_path: str | Path) -> tuple[int, int, int]:
    """Estimate a brand accent color from an image (e.g. the profile pic)."""
    try:
        img = Image.open(image_path).convert("RGB").resize((64, 64))
    except Exception:  # noqa: BLE001 - color is cosmetic, never fail on it
        return (203, 109, 81)  # warm terracotta default
    paletted = img.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
    palette = paletted.getpalette()
    counts = sorted(paletted.getcolors(), reverse=True)
    # Prefer the most common color that is not near-black/near-white
    for _, idx in counts:
        r, g, b = palette[idx * 3 : idx * 3 + 3]
        _, lightness, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if 0.12 < lightness < 0.92 and saturation > 0.12:
            return (r, g, b)
    r, g, b = palette[counts[0][1] * 3 : counts[0][1] * 3 + 3]
    return (r, g, b)


def darken(color: tuple[int, int, int], factor: float = 0.45) -> tuple[int, int, int]:
    return tuple(int(c * factor) for c in color)  # type: ignore[return-value]


def vertical_gradient(
    size: tuple[int, int],
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
) -> np.ndarray:
    """RGB gradient image as a numpy array (for ColorClip-like backgrounds)."""
    width, height = size
    t = np.linspace(0.0, 1.0, height)[:, None]
    top_arr = np.array(top, dtype=np.float32)
    bottom_arr = np.array(bottom, dtype=np.float32)
    column = top_arr * (1 - t) + bottom_arr * t  # (height, 3)
    return np.repeat(column[:, None, :], width, axis=1).astype(np.uint8)


def readability_overlay(size: tuple[int, int], strength: int = 110) -> np.ndarray:
    """RGBA overlay darkening top and bottom thirds so text stays readable."""
    width, height = size
    alpha = np.zeros((height, 1), dtype=np.float32)
    third = height / 3
    ys = np.arange(height, dtype=np.float32)
    alpha[:, 0] = np.clip((third - ys) / third, 0, 1) + np.clip((ys - 2 * third) / third, 0, 1)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 3] = np.repeat((alpha * strength).astype(np.uint8), width, axis=1)
    return rgba


def cover_image(image_path: str | Path, size: tuple[int, int], overscan: float = 1.0) -> Image.Image:
    """Open an image and scale+crop it to completely cover ``size``."""
    target_w, target_h = int(size[0] * overscan), int(size[1] * overscan)
    img = Image.open(image_path).convert("RGB")
    scale = max(target_w / img.width, target_h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - target_w) // 2
    top = (img.height - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def ken_burns_clip(image_path: str | Path, duration: float, size: tuple[int, int], direction: int = 0):
    """A photo clip with gentle drift (pan) — cheap, professional motion.

    The image is overscanned by 12% and the visible window pans across it.
    ``direction`` rotates between four pan paths so consecutive scenes differ.
    """
    from moviepy import ImageClip

    overscan = 1.12
    img = cover_image(image_path, size, overscan=overscan)
    frame = np.array(img)
    clip = ImageClip(frame).with_duration(duration)

    max_dx = img.width - size[0]
    max_dy = img.height - size[1]
    paths = [
        ((0, 0), (-max_dx, -max_dy)),
        ((-max_dx, 0), (0, -max_dy)),
        ((0, -max_dy), (-max_dx, 0)),
        ((-max_dx, -max_dy), (0, 0)),
    ]
    (x0, y0), (x1, y1) = paths[direction % len(paths)]

    def position(t: float):
        p = min(1.0, t / duration) if duration else 0.0
        # ease-in-out for smoother motion
        p = p * p * (3 - 2 * p)
        return (x0 + (x1 - x0) * p, y0 + (y1 - y0) * p)

    return clip.with_position(position)
