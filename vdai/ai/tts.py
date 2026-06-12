"""Automatic voiceover via Microsoft Edge TTS (free, no API key).

The killer combo: the same synthesis stream also reports *word boundary*
timestamps, so captions are perfectly synced to the generated speech with
no transcription step at all.

Hebrew voices: he-IL-HilaNeural (female), he-IL-AvriNeural (male).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..models import CaptionSegment, CaptionWord
from ..transcribe.engine import chunk_words

logger = logging.getLogger(__name__)

# 100-nanosecond units, as reported by the edge-tts WordBoundary events
_HNS = 10_000_000

VOICES = {
    ("he", "female"): "he-IL-HilaNeural",
    ("he", "male"): "he-IL-AvriNeural",
    ("en", "female"): "en-US-JennyNeural",
    ("en", "male"): "en-US-GuyNeural",
    ("ar", "female"): "ar-SA-ZariyahNeural",
    ("ar", "male"): "ar-SA-HamedNeural",
    ("ru", "female"): "ru-RU-SvetlanaNeural",
    ("ru", "male"): "ru-RU-DmitryNeural",
    ("fr", "female"): "fr-FR-DeniseNeural",
    ("es", "female"): "es-ES-ElviraNeural",
}
DEFAULT_GENDER = "female"


class TTSError(RuntimeError):
    pass


def pick_voice(language: str, gender: str = DEFAULT_GENDER, override: str = "") -> str:
    if override:
        return override
    return (
        VOICES.get((language, gender))
        or VOICES.get((language, DEFAULT_GENDER))
        or VOICES[("en", gender if (("en", gender) in VOICES) else DEFAULT_GENDER)]
    )


def words_from_boundaries(events: list[dict]) -> list[CaptionWord]:
    """Convert edge-tts WordBoundary events into caption words (seconds)."""
    words = []
    for event in events:
        token = str(event.get("text", "")).strip()
        if not token:
            continue
        start = float(event["offset"]) / _HNS
        duration = float(event.get("duration", 0)) / _HNS
        words.append(CaptionWord(word=token, start=start, end=start + max(duration, 0.05)))
    return words


def synthesize(
    text: str,
    out_path: str | Path,
    voice: str,
    rate: str = "+0%",
) -> tuple[Path, list[CaptionSegment]]:
    """Generate speech audio for ``text`` and return (mp3 path, captions)."""
    text = " ".join(text.split())
    if not text:
        raise TTSError("אין טקסט קריינות")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        audio, events = asyncio.run(_stream(text, voice))
    except TTSError:
        raise
    except Exception as exc:  # noqa: BLE001 - usually network / blocked host
        raise TTSError(
            f"יצירת הקריינות נכשלה (נדרשת גישה לאינטרנט לשירות Edge TTS): {exc}"
        ) from exc

    if not audio:
        raise TTSError("שירות ה-TTS לא החזיר אודיו")
    out_path.write_bytes(audio)

    words = words_from_boundaries(events)
    captions = chunk_words(words) if words else []
    logger.info("TTS: %.1fs of narration, %d caption chunks (voice=%s)",
                words[-1].end if words else 0.0, len(captions), voice)
    return out_path, captions


async def _stream(text: str, voice: str) -> tuple[bytes, list[dict]]:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    audio = bytearray()
    events: list[dict] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            events.append(chunk)
    return bytes(audio), events


def narration_from_concept(concept) -> str:
    """Fallback narration when the concept has none: hook → scenes → CTA."""
    if concept.narration.strip():
        return concept.narration.strip()
    parts = [concept.hook] + [s.text for s in concept.scenes if s.text] + [concept.cta]
    sentences = [p.strip().rstrip(".!?") for p in parts if p and p.strip()]
    return ". ".join(sentences) + "."
