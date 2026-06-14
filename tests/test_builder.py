"""End-to-end smoke test: render a small real reel from synthetic media."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from vdai.ai.creative import template_concepts
from vdai.models import BusinessProfile, CaptionSegment, Post
from vdai.video.builder import build_reel


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("media")
    colors = [(201, 90, 60), (60, 120, 201), (90, 170, 90)]
    for i, color in enumerate(colors):
        img = Image.new("RGB", (1200, 900), color)
        draw = ImageDraw.Draw(img)
        draw.ellipse([400, 250, 800, 650], fill=(245, 240, 230))
        img.save(directory / f"photo_{i}.jpg", quality=90)
    return directory


@pytest.fixture(scope="module")
def profile(media_dir):
    posts = [Post(media_path=str(p)) for p in sorted(media_dir.glob("*.jpg"))]
    return BusinessProfile(
        username="test_business",
        full_name="העסק לדוגמה",
        biography="קפה ומאפים בלב העיר",
        posts=posts,
        profile_pic_path=posts[0].media_path,
    )


def test_build_reel_smoke(profile, tmp_path):
    concept = template_concepts(profile, count=1, language="he")[0]
    # Keep the test fast: short scenes, small frame
    for scene in concept.scenes:
        scene.duration = 1.2
    out = tmp_path / "reel.mp4"
    result = build_reel(profile, concept, out, size=(270, 480), fps=12)
    assert result.exists()
    assert result.stat().st_size > 10_000

    from moviepy import VideoFileClip

    with VideoFileClip(str(result)) as clip:
        assert clip.w == 270 and clip.h == 480
        expected = sum(s.duration for s in concept.scenes) + 3.0  # + outro
        assert clip.duration == pytest.approx(expected, abs=2.5)


def test_karaoke_bursts_from_word_timings():
    from vdai.models import CaptionWord
    from vdai.video.builder import _karaoke_bursts

    words = [
        CaptionWord("ברוכים", 0.0, 0.4), CaptionWord("הבאים", 0.45, 0.9),
        CaptionWord("אלינו", 0.95, 1.3),
    ]
    caps = [CaptionSegment(text="ברוכים הבאים אלינו", start=0.0, end=1.3, words=words)]
    bursts = _karaoke_bursts(caps, max_words=2)
    assert [b[0] for b in bursts] == ["ברוכים הבאים", "אלינו"]
    assert bursts[0][1] == 0.0 and bursts[0][2] == 0.9


def test_karaoke_bursts_fallback_without_word_timings():
    from vdai.video.builder import _karaoke_bursts

    caps = [CaptionSegment(text="שלום עולם", start=0.5, end=1.5)]  # no .words
    bursts = _karaoke_bursts(caps)
    assert bursts == [("שלום עולם", 0.5, 1.5)]


def test_build_reel_karaoke_captions(profile, tmp_path):
    from vdai.models import CaptionWord

    concept = template_concepts(profile, count=1, language="he")[0]
    concept.scenes = concept.scenes[:2]
    for scene in concept.scenes:
        scene.duration = 1.2
    words = [CaptionWord("שלום", 0.2, 0.7), CaptionWord("לכולם", 0.8, 1.4)]
    captions = [CaptionSegment(text="שלום לכולם", start=0.2, end=1.4, words=words)]
    out = tmp_path / "karaoke.mp4"
    result = build_reel(profile, concept, out, captions=captions,
                        size=(270, 480), fps=12, caption_style="karaoke")
    assert result.exists() and result.stat().st_size > 10_000


def test_build_reel_with_captions(profile, tmp_path):
    concept = template_concepts(profile, count=1, language="he")[0]
    concept.scenes = concept.scenes[:2]
    for scene in concept.scenes:
        scene.duration = 1.2
    captions = [
        CaptionSegment(text="שלום לכולם", start=0.2, end=1.0),
        CaptionSegment(text="ברוכים הבאים", start=1.1, end=2.0),
    ]
    out = tmp_path / "reel_captions.mp4"
    result = build_reel(profile, concept, out, captions=captions, size=(270, 480), fps=12)
    assert result.exists()
    assert result.stat().st_size > 10_000
