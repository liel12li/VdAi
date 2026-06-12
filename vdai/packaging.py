"""Bundle a rendered reel into a ready-to-publish package.

The zip contains everything a social manager needs:
  reel.mp4, cover.jpg, caption.txt (copy + hashtags), captions.srt (if any)
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from .models import CaptionSegment, ReelConcept

logger = logging.getLogger(__name__)


def caption_text(concept: ReelConcept) -> str:
    parts = [concept.caption.strip()]
    if concept.hashtags:
        parts += ["", " ".join(concept.hashtags)]
    if concept.narration.strip():
        parts += ["", "--- תסריט קריינות ---", concept.narration.strip()]
    return "\n".join(parts).strip() + "\n"


def export_package(
    video_path: str | Path,
    concept: ReelConcept,
    cover_path: str | Path | None = None,
    captions: list[CaptionSegment] | None = None,
    zip_path: str | Path | None = None,
) -> Path:
    """Write a publish-ready zip next to the video; returns the zip path."""
    video_path = Path(video_path)
    zip_path = Path(zip_path) if zip_path else video_path.with_suffix(".zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(video_path, video_path.name)
        if cover_path and Path(cover_path).exists():
            bundle.write(cover_path, Path(cover_path).name)
        bundle.writestr("caption.txt", caption_text(concept))
        if captions:
            from .transcribe.engine import segments_to_srt

            bundle.writestr("captions.srt", segments_to_srt(captions))
    logger.info("Publish package: %s", zip_path)
    return zip_path
