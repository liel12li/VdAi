"""Assemble a finished reel (9:16 mp4) from a profile + concept.

Layout per reel:
  [scene 0 + hook]  [scene 1..n + overlay pills]  [CTA outro card]
with crossfades, a @username watermark, optional burned-in captions
(synced to a voiceover) and a music bed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    afx,
    vfx,
)

from ..config import settings
from ..models import BusinessProfile, CaptionSegment, ReelConcept
from . import effects, text as textmod

logger = logging.getLogger(__name__)

CROSSFADE = 0.45
OUTRO_DURATION = 3.0
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

_STYLE = {
    "clean": {"hook_size": 0.088, "pill_alpha": 150, "accent_in_pill": False},
    "bold": {"hook_size": 0.102, "pill_alpha": 200, "accent_in_pill": True},
    "elegant": {"hook_size": 0.082, "pill_alpha": 120, "accent_in_pill": False},
}


def build_reel(
    profile: BusinessProfile,
    concept: ReelConcept,
    output_path: str | Path,
    voiceover: str | Path | None = None,
    captions: list[CaptionSegment] | None = None,
    music: str | Path | None = None,
    size: tuple[int, int] | None = None,
    fps: int | None = None,
) -> Path:
    """Render the reel and return the output path."""
    size = size or settings.size
    fps = fps or settings.fps
    width, height = size
    style = _STYLE.get(concept.style, _STYLE["clean"])

    brand = effects.dominant_color(
        profile.profile_pic_path or (profile.posts[0].media_path if profile.posts else "")
    )

    voice_clip = AudioFileClip(str(voiceover)) if voiceover else None
    durations = _scene_durations(concept, voice_clip.duration if voice_clip else None)

    open_clips: list = []  # source clips to close after writing
    try:
        scene_clips = []
        for i, (scene, duration) in enumerate(zip(concept.scenes, durations)):
            base = _scene_base(profile, scene.media_index, duration, size, i, open_clips)
            layers = [base]
            if i == 0:
                layers.append(ImageClip(effects.readability_overlay(size)).with_duration(duration))
                layers.append(_hook_layer(concept.hook, size, style, duration))
            elif scene.text:
                layers.append(_pill_layer(scene.text, size, style, duration,
                                          top=bool(captions)))
            scene_clips.append(CompositeVideoClip(layers, size=size).with_duration(duration))

        scene_clips.append(_outro_card(profile, concept, brand, size))

        video = _crossfade_concat(scene_clips, size)
        total = video.duration

        overlays = [video, _watermark(profile.username, size, total)]
        if captions:
            overlays.extend(_caption_layers(captions, size, total))
        final = CompositeVideoClip(overlays, size=size).with_duration(total)
        final = final.with_effects([vfx.FadeOut(0.4)])

        audio = _mix_audio(voice_clip, music, concept.music_mood, total)
        if audio is not None:
            final = final.with_audio(audio)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Rendering %s (%.1fs at %dx%d)...", output_path.name, total, width, height)
        final.write_videofile(
            str(output_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=os.cpu_count() or 2,
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            logger=None,
        )
        return output_path
    finally:
        for clip in open_clips:
            try:
                clip.close()
            except Exception:  # noqa: BLE001
                pass
        if voice_clip is not None:
            voice_clip.close()


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------

def _scene_durations(concept: ReelConcept, voice_duration: float | None) -> list[float]:
    durations = [max(1.2, s.duration) for s in concept.scenes]
    if voice_duration:
        # Scenes (plus crossfade overlap savings) should cover the voiceover,
        # leaving the outro to start as the speech ends.
        n = len(durations)
        overlap = CROSSFADE * n  # n transitions including into the outro
        target = max(voice_duration + 0.6 - OUTRO_DURATION + overlap, n * 1.2)
        factor = target / sum(durations)
        durations = [min(6.0, max(1.2, d * factor)) for d in durations]
    return durations


# --------------------------------------------------------------------------
# Visual layers
# --------------------------------------------------------------------------

def _scene_base(profile, media_index, duration, size, scene_no, open_clips):
    post = profile.posts[media_index % len(profile.posts)]
    if post.is_video:
        try:
            source = VideoFileClip(post.media_path)
            open_clips.append(source)
            clip = source.without_audio()
            if clip.duration and clip.duration > duration:
                clip = clip.subclipped(0, duration)
            else:
                duration = min(duration, clip.duration or duration)
            return _cover(clip, size).with_duration(duration)
        except Exception as exc:  # noqa: BLE001 - corrupt video → fall back to motion-less frame
            logger.warning("Could not use video %s (%s); skipping", post.media_path, exc)
    return effects.ken_burns_clip(post.media_path, duration, size, direction=scene_no)


def _cover(clip, size):
    width, height = size
    scale = max(width / clip.w, height / clip.h)
    clip = clip.resized((round(clip.w * scale), round(clip.h * scale)))
    return clip.with_effects(
        [vfx.Crop(x_center=clip.w / 2, y_center=clip.h / 2, width=width, height=height)]
    )


def _hook_layer(hook, size, style, duration):
    width, height = size
    arr = textmod.text_array(
        hook,
        font_size=int(height * style["hook_size"]),
        max_width=int(width * 0.86),
        shadow=True,
    )
    return (
        ImageClip(arr)
        .with_duration(duration)
        .with_position(("center", "center"))
        .with_effects([vfx.CrossFadeIn(min(0.5, duration / 3))])
    )


def _pill_layer(line, size, style, duration, top=False):
    width, height = size
    arr = textmod.text_array(
        line,
        font_size=int(height * 0.034),
        max_width=int(width * 0.84),
        pill=True,
        pill_color=(0, 0, 0, style["pill_alpha"]),
    )
    y = int(height * 0.12) if top else int(height * 0.78)
    return (
        ImageClip(arr)
        .with_duration(duration)
        .with_position(("center", y))
        .with_effects([vfx.CrossFadeIn(min(0.4, duration / 3))])
    )


def _watermark(username, size, duration):
    width, height = size
    arr = textmod.text_array(
        f"@{username}",
        font_size=int(height * 0.020),
        pill=True,
        pill_color=(0, 0, 0, 110),
        pill_padding=(26, 12),
    )
    return ImageClip(arr).with_duration(duration).with_position(("center", int(height * 0.030)))


def _caption_layers(captions, size, total):
    width, height = size
    layers = []
    for seg in captions:
        if seg.start >= total:
            break
        arr = textmod.text_array(
            seg.text,
            font_size=int(height * 0.030),
            max_width=int(width * 0.86),
            pill=True,
            pill_color=(0, 0, 0, 185),
            color=(255, 235, 120),  # warm yellow — the reels captions standard
        )
        end = min(seg.end, total - 0.1)
        layers.append(
            ImageClip(arr)
            .with_start(seg.start)
            .with_duration(max(0.3, end - seg.start))
            .with_position(("center", int(height * 0.70)))
        )
    return layers


def _outro_card(profile, concept, brand, size):
    width, height = size
    bg = effects.vertical_gradient(size, effects.darken(brand, 0.55), effects.darken(brand, 0.18))
    layers = [ImageClip(bg).with_duration(OUTRO_DURATION)]

    pic = _circle_profile_pic(profile, int(height * 0.13))
    if pic is not None:
        layers.append(
            ImageClip(pic)
            .with_duration(OUTRO_DURATION)
            .with_position(("center", int(height * 0.26)))
        )

    cta = textmod.text_array(
        concept.cta,
        font_size=int(height * 0.052),
        max_width=int(width * 0.84),
        shadow=True,
    )
    layers.append(
        ImageClip(cta).with_duration(OUTRO_DURATION).with_position(("center", int(height * 0.45)))
    )

    handle = textmod.text_array(f"@{profile.username}", font_size=int(height * 0.030))
    layers.append(
        ImageClip(handle).with_duration(OUTRO_DURATION).with_position(("center", int(height * 0.58)))
    )
    return CompositeVideoClip(layers, size=size).with_duration(OUTRO_DURATION)


def _circle_profile_pic(profile, diameter):
    if not profile.profile_pic_path or not Path(profile.profile_pic_path).exists():
        return None
    import numpy as np
    from PIL import Image, ImageDraw, ImageOps

    try:
        img = Image.open(profile.profile_pic_path).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    img = ImageOps.fit(img, (diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, diameter - 1, diameter - 1], fill=255)
    rgba = img.convert("RGBA")
    rgba.putalpha(mask)
    return np.array(rgba)


def _crossfade_concat(clips, size):
    placed = []
    start = 0.0
    for i, clip in enumerate(clips):
        if i > 0:
            start -= CROSSFADE
            clip = clip.with_effects([vfx.CrossFadeIn(CROSSFADE)])
        placed.append(clip.with_start(start))
        start += clip.duration
    return CompositeVideoClip(placed, size=size).with_duration(start)


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------

def _mix_audio(voice_clip, music, mood, total):
    tracks = []
    if voice_clip is not None:
        tracks.append(voice_clip.with_effects([afx.AudioFadeOut(0.3)]))

    music_path = Path(music) if music else _pick_music(mood)
    if music_path is not None and music_path.exists():
        level = 0.16 if voice_clip is not None else 0.6
        music_clip = AudioFileClip(str(music_path))
        music_clip = music_clip.with_effects(
            [afx.AudioLoop(duration=total), afx.MultiplyVolume(level), afx.AudioFadeOut(1.2)]
        )
        tracks.append(music_clip)
    elif music:
        logger.warning("Music file %s not found — rendering without music", music)

    if not tracks:
        return None
    if len(tracks) == 1:
        return tracks[0].with_duration(min(total, tracks[0].duration))
    return CompositeAudioClip(tracks).with_duration(total)


def _pick_music(mood: str) -> Path | None:
    """Pick a track from the user's music folder, preferring mood matches."""
    music_dir = settings.music_dir
    if not music_dir.is_dir():
        return None
    files = sorted(p for p in music_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    if not files:
        return None
    for f in files:
        if mood.lower() in f.stem.lower():
            return f
    return files[0]
