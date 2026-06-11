"""RTL-aware text rendering with Pillow.

MoviePy's TextClip depends on ImageMagick and has poor RTL support, so all
text is rendered here with Pillow into RGBA numpy arrays and composited as
ImageClips.

Hebrew handling: when Pillow was built with libraqm, ``draw.text`` runs the
bidi algorithm itself, so we pass *logical* text with ``direction="rtl"``.
Without raqm we reorder with python-bidi first. Applying both would flip the
text twice and render it backwards.
"""

from __future__ import annotations

import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from .fonts import load_font

_RTL_RE = re.compile(r"[֐-׿؀-ۿ]")  # Hebrew + Arabic ranges

HAS_RAQM = features.check("raqm")


def is_rtl(text: str) -> bool:
    return bool(_RTL_RE.search(text))


def to_display(text: str) -> str:
    """Reorder logical→visual for renderers without their own bidi (no raqm)."""
    if not is_rtl(text):
        return text
    from bidi.algorithm import get_display

    return get_display(text)


def _direction(text: str) -> str | None:
    return "rtl" if (HAS_RAQM and is_rtl(text)) else None


def line_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    direction = _direction(text)
    if direction:
        return font.getlength(text, direction=direction)
    return font.getlength(text)


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy word-wrap in *logical* order; returns logical-order lines."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and line_width(font, candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def render_text_image(
    text: str,
    font_size: int = 72,
    color: tuple[int, int, int] = (255, 255, 255),
    max_width: int = 900,
    line_spacing: float = 1.18,
    stroke_width: int = 0,
    stroke_color: tuple[int, int, int] = (0, 0, 0),
    pill: bool = False,
    pill_color: tuple[int, int, int, int] = (0, 0, 0, 160),
    pill_padding: tuple[int, int] = (38, 22),
    shadow: bool = False,
) -> Image.Image:
    """Render (possibly multi-line, possibly RTL) text to an RGBA image."""
    font = load_font(font_size)
    lines = wrap_text(text, font, max_width - (pill_padding[0] * 2 if pill else 0))
    if not HAS_RAQM:
        lines = [to_display(line) for line in lines]

    line_height = int(font_size * line_spacing)
    pad_x, pad_y = pill_padding if pill else (stroke_width + 8, stroke_width + 8)
    text_width = max(int(line_width(font, line)) for line in lines)
    width = text_width + pad_x * 2
    height = line_height * len(lines) + pad_y * 2

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if pill:
        radius = min(34, height // 2)
        draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=radius, fill=pill_color)

    if shadow:
        shadow_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_img)
        _draw_lines(shadow_draw, lines, font, width, pad_y, line_height,
                    (0, 0, 0, 200), 0, (0, 0, 0), offset=(3, 4))
        shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(4))
        img = Image.alpha_composite(img, shadow_img)
        draw = ImageDraw.Draw(img)

    _draw_lines(draw, lines, font, width, pad_y, line_height,
                color + (255,), stroke_width, stroke_color)
    return img


def _draw_lines(draw, lines, font, width, pad_y, line_height,
                fill, stroke_width, stroke_color, offset=(0, 0)):
    for i, line in enumerate(lines):
        w = line_width(font, line)
        x = (width - w) / 2 + offset[0]
        y = pad_y + i * line_height + offset[1]
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_color + (255,) if stroke_width else None,
            direction=_direction(line),
        )


def text_array(text: str, **kwargs) -> np.ndarray:
    """Convenience: rendered text as an RGBA numpy array (for ImageClip)."""
    return np.array(render_text_image(text, **kwargs))
