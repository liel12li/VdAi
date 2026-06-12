"""Burn transcribed captions onto an existing video file."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from moviepy import CompositeVideoClip, ImageClip, VideoFileClip

from ..models import CaptionSegment

logger = logging.getLogger(__name__)


def burn_captions(
    video_path: str | Path,
    captions: list[CaptionSegment],
    output_path: str | Path,
    y_ratio: float = 0.78,
    style: str = "pill",
) -> Path:
    """Overlay caption pills on ``video_path`` and write ``output_path``."""
    from .builder import caption_array

    source = VideoFileClip(str(video_path))
    try:
        width, height = source.w, source.h
        layers: list = [source]
        for seg in captions:
            if seg.start >= source.duration:
                break
            arr = caption_array(seg.text, (width, height), style)
            end = min(seg.end, source.duration)
            layers.append(
                ImageClip(arr)
                .with_start(seg.start)
                .with_duration(max(0.3, end - seg.start))
                .with_position(("center", int(height * y_ratio)))
            )

        final = CompositeVideoClip(layers, size=(width, height)).with_duration(source.duration)
        if source.audio is not None:
            final = final.with_audio(source.audio)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        final.write_videofile(
            str(output_path),
            fps=source.fps or 30,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=os.cpu_count() or 2,
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            logger=None,
        )
        return output_path
    finally:
        source.close()
