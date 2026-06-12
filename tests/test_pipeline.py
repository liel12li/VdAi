"""Tests for format presets, brand kit and the packaging module."""

import json
import zipfile

import pytest

from vdai.ai.creative import apply_brand, template_concepts
from vdai.config import FORMAT_PRESETS, format_size
from vdai.models import BrandKit, BusinessProfile, CaptionSegment, Post, concepts_from_json
from vdai.packaging import caption_text, export_package


def _profile(n=3):
    return BusinessProfile(
        username="biz",
        full_name="העסק",
        biography="ביו",
        posts=[Post(media_path=f"/tmp/p{i}.jpg") for i in range(n)],
    )


# ---- formats ----

def test_format_size_known_presets():
    assert format_size("reel") == (1080, 1920)
    assert format_size("square") == (1080, 1080)
    assert format_size("portrait") == (1080, 1350)
    assert format_size("wide") == (1920, 1080)


def test_format_size_draft_halves_and_stays_even():
    for fmt in FORMAT_PRESETS:
        w, h = format_size(fmt, draft=True)
        assert w % 2 == 0 and h % 2 == 0
        assert w <= FORMAT_PRESETS[fmt][0] // 2 + 1


def test_format_size_unknown_raises():
    with pytest.raises(ValueError, match="פורמט לא מוכר"):
        format_size("story9000")


# ---- brand kit ----

def test_brand_kit_load_and_accent(tmp_path):
    path = tmp_path / "brand.json"
    path.write_text(json.dumps({"accent": "#C96F4A", "cta": "בואו אלינו"}), encoding="utf-8")
    kit = BrandKit.load(path)
    assert kit.accent_rgb == (0xC9, 0x6F, 0x4A)
    assert kit.cta == "בואו אלינו"


def test_brand_kit_bad_accent(tmp_path):
    path = tmp_path / "brand.json"
    path.write_text(json.dumps({"accent": "red"}), encoding="utf-8")
    with pytest.raises(ValueError, match="צבע מותג"):
        BrandKit.load(path)


def test_brand_kit_ignores_unknown_keys(tmp_path):
    path = tmp_path / "brand.json"
    path.write_text(json.dumps({"cta": "x", "future_field": 1}), encoding="utf-8")
    assert BrandKit.load(path).cta == "x"


def test_apply_brand_overrides_cta_and_appends_hashtags():
    concepts = template_concepts(_profile(), count=2, language="he")
    kit = BrandKit(cta="הזמינו עכשיו", hashtags=["#חדש", "#ריל"])  # #ריל already exists
    apply_brand(concepts, kit)
    for concept in concepts:
        assert concept.cta == "הזמינו עכשיו"
        assert "#חדש" in concept.hashtags
        assert sum(1 for t in concept.hashtags if t.lower() == "#ריל") == 1


def test_apply_brand_none_is_noop():
    concepts = template_concepts(_profile(), count=1)
    assert apply_brand(concepts, None) is concepts


# ---- narration in templates ----

def test_template_concepts_have_narration():
    for concept in template_concepts(_profile(), count=3, language="he"):
        assert concept.narration
        assert concept.narration.endswith(".")
        assert concept.cta.rstrip(".!?") in concept.narration


# ---- concepts round-trip for the edit flow ----

def test_concepts_from_json_list_and_wrapped(tmp_path):
    concepts = template_concepts(_profile(), count=2)
    as_list = tmp_path / "a.json"
    as_list.write_text(
        json.dumps([c.to_dict() for c in concepts], ensure_ascii=False), encoding="utf-8"
    )
    wrapped = tmp_path / "b.json"
    wrapped.write_text(
        json.dumps({"concepts": [c.to_dict() for c in concepts]}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert concepts_from_json(as_list) == concepts
    assert concepts_from_json(wrapped) == concepts


# ---- packaging ----

def test_caption_text_includes_copy_hashtags_narration():
    concept = template_concepts(_profile(), count=1)[0]
    text = caption_text(concept)
    assert concept.caption in text
    assert concept.hashtags[0] in text
    assert concept.narration in text


# ---- full pipeline integration (real draft render, no AI/network) ----

def test_run_generation_end_to_end(tmp_path):
    from PIL import Image

    from vdai.pipeline import GenerationOptions, run_generation

    media = tmp_path / "media"
    media.mkdir()
    for i, color in enumerate([(200, 90, 60), (60, 120, 200)]):
        Image.new("RGB", (800, 600), color).save(media / f"p{i}.jpg")

    profile = BusinessProfile(
        username="pipeline_biz",
        full_name="עסק הצינור",
        biography="בדיקת אינטגרציה",
        posts=[Post(media_path=str(p)) for p in sorted(media.glob("*.jpg"))],
    )
    options = GenerationOptions(
        count=1,
        language="he",
        use_ai=False,
        formats=["square"],
        draft=True,
        out_dir=tmp_path / "out",
        package=True,
    )
    steps: list[str] = []
    outputs = run_generation(profile, options, on_step=steps.append)

    assert len(outputs) == 1
    out = outputs[0]
    assert out.video.exists() and out.video.stat().st_size > 10_000
    assert "_square_draft" in out.video.name
    assert out.cover is not None and out.cover.exists()
    assert out.package is not None and zipfile.ZipFile(out.package).namelist()
    assert (tmp_path / "out" / "pipeline_biz_concepts.json").exists()
    assert steps  # progress was reported

    from moviepy import VideoFileClip

    with VideoFileClip(str(out.video)) as clip:
        assert (clip.w, clip.h) == (540, 540)


def test_export_package(tmp_path):
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"fake-video")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"fake-cover")
    concept = template_concepts(_profile(), count=1)[0]
    captions = [CaptionSegment(text="שלום", start=0.0, end=1.0)]

    zip_path = export_package(video, concept, cover_path=cover, captions=captions)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as bundle:
        names = set(bundle.namelist())
        assert names == {"reel.mp4", "cover.jpg", "caption.txt", "captions.srt"}
        assert "שלום" in bundle.read("captions.srt").decode("utf-8")
