"""Runtime configuration for VdAi, mostly driven by environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"


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
