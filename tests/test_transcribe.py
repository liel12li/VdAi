"""Tests for caption chunking and SRT export (no whisper model needed)."""

from vdai.models import CaptionWord
from vdai.transcribe.engine import chunk_words, segments_to_srt


def _words(spec):
    """spec: list of (word, start, end)"""
    return [CaptionWord(word=w, start=s, end=e) for w, s, e in spec]


def test_chunk_words_groups_short_bursts():
    words = _words([
        ("שלום", 0.0, 0.3), ("לכולם", 0.35, 0.7), ("ברוכים", 0.75, 1.1),
        ("הבאים", 1.15, 1.5), ("לעסק", 1.55, 1.9), ("שלנו", 1.95, 2.3),
    ])
    segments = chunk_words(words, max_words=4)
    assert len(segments) == 2
    assert segments[0].text == "שלום לכולם ברוכים הבאים"
    assert segments[1].text == "לעסק שלנו"


def test_chunk_words_breaks_on_pause():
    words = _words([("היי", 0.0, 0.4), ("חברים", 0.5, 0.9), ("בואו", 3.0, 3.4)])
    segments = chunk_words(words, max_gap=0.8)
    assert len(segments) == 2
    assert segments[1].text == "בואו"


def test_chunk_words_breaks_on_punctuation():
    words = _words([("נכון.", 0.0, 0.4), ("אז", 0.5, 0.7), ("ככה", 0.75, 1.0)])
    segments = chunk_words(words)
    assert segments[0].text == "נכון."
    assert segments[1].text == "אז ככה"


def test_min_display_time():
    words = _words([("רגע", 0.0, 0.2), ("אחד", 5.0, 5.2)])
    segments = chunk_words(words)
    assert all(seg.duration >= 0.2 for seg in segments)
    assert segments[0].end >= 0.6  # extended, has room before next


def test_srt_format():
    segments = chunk_words(_words([("שלום", 0.0, 0.5), ("עולם", 0.6, 1.2)]))
    srt = segments_to_srt(segments)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "שלום עולם" in srt
    assert "-->" in srt
