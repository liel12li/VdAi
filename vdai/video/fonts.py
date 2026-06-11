"""Locate a font with Hebrew support for text rendering.

Priority: VDAI_FONT env var → bundled Heebo (variable font, OFL licensed)
→ common system fonts with Hebrew coverage.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from ..config import ASSETS_DIR

_BUNDLED = ASSETS_DIR / "fonts" / "Heebo[wght].ttf"

_SYSTEM_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Hebrew.ttc",  # macOS
    "C:\\Windows\\Fonts\\arialbd.ttf",  # Windows
]


class FontNotFoundError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def find_font_path() -> str:
    override = os.environ.get("VDAI_FONT", "")
    if override:
        if Path(override).exists():
            return override
        raise FontNotFoundError(f"VDAI_FONT points to a missing file: {override}")
    if _BUNDLED.exists():
        return str(_BUNDLED)
    for candidate in _SYSTEM_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise FontNotFoundError(
        "No Hebrew-capable font found. Set VDAI_FONT to a .ttf file with "
        "Hebrew glyphs (e.g. Heebo, Rubik, DejaVu Sans)."
    )


def load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load the project font at the given pixel size.

    The bundled Heebo file is a variable font; we select the Bold/Regular
    named instance when supported and silently keep the default otherwise.
    """
    font = ImageFont.truetype(find_font_path(), size)
    try:
        font.set_variation_by_name("Bold" if bold else "Regular")
    except (OSError, NotImplementedError, ValueError):
        pass  # static font (e.g. DejaVu) or no variation support — nothing to do
    return font
