"""Runtime configuration for VdAi, mostly driven by environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"

# Output format presets: name -> (width, height)
FORMAT_PRESETS: dict[str, tuple[int, int]] = {
    "reel": (1080, 1920),      # Reels / Stories / TikTok (9:16)
    "square": (1080, 1080),    # Feed square (1:1)
    "portrait": (1080, 1350),  # Feed portrait (4:5)
    "wide": (1920, 1080),      # YouTube / website (16:9)
}


def format_size(fmt: str, draft: bool = False) -> tuple[int, int]:
    """Resolve a format name to pixel dimensions (halved in draft mode)."""
    if fmt not in FORMAT_PRESETS:
        raise ValueError(
            f"פורמט לא מוכר: {fmt!r}. אפשרויות: {', '.join(FORMAT_PRESETS)}"
        )
    width, height = FORMAT_PRESETS[fmt]
    if draft:
        width, height = (width // 2) & ~1, (height // 2) & ~1  # keep even
    return width, height


@dataclass
class Settings:
    # Claude API
    anthropic_model: str = os.environ.get("VDAI_MODEL", "claude-opus-4-8")

    # Whisper transcription
    whisper_model: str = os.environ.get("VDAI_WHISPER_MODEL", "small")

    # Video output
    width: int = int(os.environ.get("VDAI_WIDTH", "1080"))
    height: int = int(os.environ.get("VDAI_HEIGHT", "1920"))
    fps: int = int(os.environ.get("VDAI_FPS", "30"))

    # Paths
    output_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("VDAI_OUTPUT_DIR", "outputs"))
    )
    cache_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("VDAI_CACHE_DIR", ".vdai_cache"))
    )
    music_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("VDAI_MUSIC_DIR", str(ASSETS_DIR / "music")))
    )

    # Optional explicit font override (path to a .ttf with Hebrew support)
    font_path: str = os.environ.get("VDAI_FONT", "")

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
