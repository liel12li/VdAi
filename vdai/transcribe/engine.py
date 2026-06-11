"""Speech-to-text via faster-whisper, plus caption chunking and SRT export.

The whisper model is downloaded on first use (a few hundred MB for
``small``). All pure-python helpers here (chunking, SRT) are importable
without the model so they can be unit-tested offline.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import CaptionSegment, CaptionWord

logger = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    pass


def transcribe(
    media_path: str | Path,
    model_size: str = "small",
    language: str | None = None,
) -> list[CaptionSegment]:
    """Transcribe an audio or video file into timed caption segments.

    ``language`` is a two-letter code ('he', 'en', ...) or None for
    auto-detection.
    """
    path = Path(media_path)
    if not path.exists():
        raise TranscriptionError(f"הקובץ {media_path} לא נמצא")

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise TranscriptionError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from exc

    logger.info("Loading whisper model %r (first run downloads it)...", model_size)
    try:
        model = WhisperModel(model_size, device="auto", compute_type="auto")
    except Exception as exc:  # noqa: BLE001 - usually a blocked/failed download
        raise TranscriptionError(
            f"לא הצלחתי להוריד/לטעון את מודל התמלול '{model_size}' "
            f"(נדרשת גישה ל-huggingface.co בהרצה הראשונה): {exc}"
        ) from exc

    segments_iter, info = model.transcribe(
        str(path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )
    logger.info("Detected language: %s (p=%.2f)", info.language, info.language_probability)

    words: list[CaptionWord] = []
    for segment in segments_iter:
        for w in segment.words or []:
            token = w.word.strip()
            if token:
                words.append(CaptionWord(word=token, start=w.start, end=w.end))

    if not words:
        raise TranscriptionError("לא זוהה דיבור בקובץ")
    return chunk_words(words)


def chunk_words(
    words: list[CaptionWord],
    max_words: int = 4,
    max_duration: float = 2.6,
    max_gap: float = 0.8,
) -> list[CaptionSegment]:
    """Group word timestamps into short on-screen caption chunks.

    Reels captions read best in bursts of 2-4 words. A new chunk starts when
    the current one is full, runs too long, or there is a pause in speech.
    """
    segments: list[CaptionSegment] = []
    current: list[CaptionWord] = []

    def flush() -> None:
        if not current:
            return
        segments.append(
            CaptionSegment(
                text=" ".join(w.word for w in current),
                start=current[0].start,
                end=current[-1].end,
                words=list(current),
            )
        )
        current.clear()

    for word in words:
        if current:
            too_many = len(current) >= max_words
            too_long = word.end - current[0].start > max_duration
            gap = word.start - current[-1].end > max_gap
            ends_sentence = current[-1].word[-1:] in ".!?,؛;:"
            if too_many or too_long or gap or ends_sentence:
                flush()
        current.append(word)
    flush()

    # Avoid flickering: give very short chunks a minimum display time when
    # there is room before the next chunk starts.
    for i, seg in enumerate(segments):
        nxt = segments[i + 1].start if i + 1 < len(segments) else seg.end + 1.0
        if seg.duration < 0.6:
            seg.end = min(seg.start + 0.6, nxt)
    return segments


def segments_to_srt(segments: list[CaptionSegment]) -> str:
    """Serialize segments to SubRip (.srt) format."""
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_time(seg.start)} --> {_srt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round((seconds % 1) * 1000))
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d},{ms:03d}"
