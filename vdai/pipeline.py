"""The shared generation pipeline used by both the CLI and the web UI.

profile → concepts (Claude / templates) → narration audio (TTS or a
recorded voiceover, transcribed) → render per concept × format → cover +
publish package.
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import format_size, settings
from .models import (
    BrandKit,
    BusinessProfile,
    CaptionSegment,
    ReelConcept,
    concepts_from_json,
    concepts_to_json,
)

logger = logging.getLogger(__name__)

StepCallback = Callable[[str], None]


@dataclass
class GenerationOptions:
    count: int = 3
    language: str = "auto"
    use_ai: bool = True
    use_vision: bool = True
    tone: str = "auto"
    formats: list[str] = field(default_factory=lambda: ["reel"])
    draft: bool = False
    voiceover: Optional[str] = None  # recorded narration file
    tts: bool = False  # synthesize narration automatically
    tts_voice: str = ""  # explicit edge-tts voice
    tts_gender: str = "female"
    music: Optional[str] = None
    out_dir: Path = field(default_factory=lambda: settings.output_dir)
    package: bool = False
    jobs: int = 1
    caption_style: str = "pill"
    progress_bar: bool = True
    whisper_model: str = ""
    brand: Optional[BrandKit] = None
    concepts_file: Optional[str] = None  # render pre-edited concepts as-is


@dataclass
class ReelOutput:
    video: Path
    concept: ReelConcept
    fmt: str
    cover: Optional[Path] = None
    package: Optional[Path] = None
    srt_segments: Optional[list[CaptionSegment]] = None


def run_generation(
    profile: BusinessProfile,
    options: GenerationOptions,
    on_step: StepCallback | None = None,
) -> list[ReelOutput]:
    """Run the full pipeline; returns one output per concept × format."""
    step = on_step or (lambda msg: logger.info("%s", msg))
    out_dir = Path(options.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    concepts = _get_concepts(profile, options, step)
    (out_dir / f"{profile.username}_concepts.json").write_text(
        concepts_to_json(concepts), encoding="utf-8"
    )

    render_jobs = _plan_renders(profile, concepts, options, out_dir, step)
    outputs = _render_all(render_jobs, options, step)

    for output in outputs:
        cover = output.video.with_name(output.video.stem + "_cover.jpg")
        try:
            from .video.builder import save_cover

            output.cover = save_cover(output.video, cover)
        except Exception as exc:  # noqa: BLE001 - cover is a bonus
            logger.warning("Could not create cover for %s: %s", output.video.name, exc)
        if options.package:
            from .packaging import export_package

            output.package = export_package(
                output.video,
                output.concept,
                cover_path=output.cover,
                captions=output.srt_segments,
            )
    return outputs


# --------------------------------------------------------------------------
# Concepts
# --------------------------------------------------------------------------

def _get_concepts(profile, options, step) -> list[ReelConcept]:
    from .ai.creative import apply_brand, generate_concepts

    if options.concepts_file:
        step(f"טוען קונספטים ערוכים מ-{options.concepts_file}")
        concepts = concepts_from_json(options.concepts_file)
        if not concepts:
            raise ValueError(f"לא נמצאו קונספטים בקובץ {options.concepts_file}")
    else:
        step("בונה קונספטים..." + (" (Claude רואה את התמונות)" if options.use_vision else ""))
        concepts = generate_concepts(
            profile,
            count=options.count,
            language=options.language,
            use_ai=options.use_ai,
            use_vision=options.use_vision,
            tone=(options.brand.tone if options.brand and options.brand.tone else options.tone),
        )
    return apply_brand(concepts, options.brand)


# --------------------------------------------------------------------------
# Narration: recorded voiceover (whisper) or synthesized (edge-tts)
# --------------------------------------------------------------------------

def _narration_for(
    concept: ReelConcept, profile, options, out_dir: Path, step
) -> tuple[Optional[str], Optional[list[CaptionSegment]]]:
    if options.voiceover:
        return options.voiceover, _shared_voiceover_captions(options, step)
    if not options.tts:
        return None, None

    from .ai.tts import narration_from_concept, pick_voice, synthesize

    voice = pick_voice(
        concept.language,
        options.tts_gender,
        options.tts_voice or (options.brand.tts_voice if options.brand else ""),
    )
    text = narration_from_concept(concept)
    step(f"מקריא את '{concept.title}' (קול: {voice})")
    audio_path = out_dir / f"{profile.username}_{concept.slug}_voice.mp3"
    path, captions = synthesize(text, audio_path, voice)
    return str(path), captions


_VOICEOVER_CACHE: dict[str, list[CaptionSegment]] = {}


def _shared_voiceover_captions(options, step) -> list[CaptionSegment]:
    """Transcribe the recorded voiceover once, reuse for every concept."""
    key = str(options.voiceover)
    if key not in _VOICEOVER_CACHE:
        from .transcribe.engine import transcribe

        step("מתמלל את הקריינות (Whisper)...")
        lang = None if options.language in ("auto", "", None) else options.language
        _VOICEOVER_CACHE[key] = transcribe(
            options.voiceover,
            model_size=options.whisper_model or settings.whisper_model,
            language=lang,
        )
    return _VOICEOVER_CACHE[key]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

@dataclass
class _RenderJob:
    profile: BusinessProfile
    concept: ReelConcept
    fmt: str
    output_path: Path
    size: tuple[int, int]
    fps: int
    voiceover: Optional[str]
    captions: Optional[list[CaptionSegment]]
    music: Optional[str]
    accent: Optional[tuple[int, int, int]]
    logo: Optional[str]
    progress_bar: bool
    caption_style: str
    preset: str


def _plan_renders(profile, concepts, options, out_dir, step) -> list[_RenderJob]:
    jobs = []
    fps = 24 if options.draft else settings.fps
    preset = "ultrafast" if options.draft else "medium"
    accent = options.brand.accent_rgb if options.brand else None
    logo = options.brand.logo if options.brand and options.brand.logo else None

    for concept in concepts:
        voice_path, captions = _narration_for(concept, profile, options, out_dir, step)
        for fmt in options.formats:
            suffix = "" if fmt == "reel" else f"_{fmt}"
            suffix += "_draft" if options.draft else ""
            output = out_dir / f"{profile.username}_{concept.slug}{suffix}.mp4"
            jobs.append(_RenderJob(
                profile=profile,
                concept=concept,
                fmt=fmt,
                output_path=output,
                size=format_size(fmt, draft=options.draft),
                fps=fps,
                voiceover=voice_path,
                captions=captions,
                music=options.music,
                accent=accent,
                logo=logo,
                progress_bar=options.progress_bar,
                caption_style=options.caption_style,
                preset=preset,
            ))
    return jobs


def _execute_render(job: _RenderJob) -> Path:
    from .video.builder import build_reel

    return build_reel(
        job.profile,
        job.concept,
        job.output_path,
        voiceover=job.voiceover,
        captions=job.captions,
        music=job.music,
        size=job.size,
        fps=job.fps,
        accent=job.accent,
        logo=job.logo,
        progress_bar=job.progress_bar,
        caption_style=job.caption_style,
        preset=job.preset,
    )


def _render_all(render_jobs: list[_RenderJob], options, step) -> list[ReelOutput]:
    outputs = []
    total = len(render_jobs)
    if options.jobs > 1 and total > 1:
        step(f"מרנדר {total} סרטונים במקביל ({options.jobs} תהליכים)...")
        with ProcessPoolExecutor(max_workers=options.jobs) as pool:
            for job, video in zip(render_jobs, pool.map(_execute_render, render_jobs)):
                outputs.append(_to_output(job, video))
    else:
        for i, job in enumerate(render_jobs, start=1):
            step(f"מרנדר ({i}/{total}): {job.concept.title} [{job.fmt}]")
            outputs.append(_to_output(job, _execute_render(job)))
    return outputs


def _to_output(job: _RenderJob, video: Path) -> ReelOutput:
    return ReelOutput(
        video=video, concept=job.concept, fmt=job.fmt, srt_segments=job.captions
    )
