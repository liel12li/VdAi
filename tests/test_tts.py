"""Tests for the TTS module's pure logic (no network calls)."""

from vdai.ai.tts import narration_from_concept, pick_voice, words_from_boundaries
from vdai.models import ReelConcept, ReelScene


def test_words_from_boundaries_converts_offsets():
    events = [
        {"type": "WordBoundary", "offset": 0, "duration": 5_000_000, "text": "שלום"},
        {"type": "WordBoundary", "offset": 6_000_000, "duration": 4_000_000, "text": "עולם"},
    ]
    words = words_from_boundaries(events)
    assert len(words) == 2
    assert words[0].word == "שלום"
    assert words[0].start == 0.0
    assert words[0].end == 0.5
    assert words[1].start == 0.6
    assert words[1].end == 1.0


def test_words_from_boundaries_skips_empty():
    events = [{"offset": 0, "duration": 1, "text": "  "}]
    assert words_from_boundaries(events) == []


def test_pick_voice_hebrew():
    assert pick_voice("he", "female") == "he-IL-HilaNeural"
    assert pick_voice("he", "male") == "he-IL-AvriNeural"


def test_pick_voice_override_wins():
    assert pick_voice("he", "female", override="custom-Voice") == "custom-Voice"


def test_pick_voice_unknown_language_falls_back_to_english():
    assert pick_voice("xx", "female").startswith("en-")


def test_narration_from_concept_uses_explicit_script():
    concept = _concept(narration="זהו תסריט הקריינות המלא שלנו.")
    assert narration_from_concept(concept) == "זהו תסריט הקריינות המלא שלנו."


def test_narration_from_concept_composes_fallback():
    concept = _concept(narration="")
    text = narration_from_concept(concept)
    assert "הוק" in text and "סיום" in text
    assert text.endswith(".")


def _concept(narration=""):
    return ReelConcept(
        slug="t",
        title="בדיקה",
        hook="הוק פותח",
        scenes=[ReelScene(text="סצנה ראשונה"), ReelScene(text="סצנה שניה")],
        cta="משפט סיום",
        narration=narration,
    )
