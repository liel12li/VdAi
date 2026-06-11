"""Tests for concept generation (template fallback path, no API needed)."""

from vdai.ai.creative import detect_language, generate_concepts, template_concepts
from vdai.models import BusinessProfile, Post, ReelConcept


def _profile(bio="מספרה בוטיק בתל אביב", full_name="מספרת דנה", n_media=4):
    return BusinessProfile(
        username="dana_hair",
        full_name=full_name,
        biography=bio,
        posts=[Post(media_path=f"/tmp/img_{i}.jpg") for i in range(n_media)],
    )


def test_detect_language_hebrew():
    assert detect_language(_profile()) == "he"


def test_detect_language_english():
    profile = _profile(bio="Boutique hair salon in Tel Aviv", full_name="Dana Hair")
    assert detect_language(profile) == "en"


def test_detect_language_explicit_wins():
    assert detect_language(_profile(), requested="en") == "en"


def test_template_concepts_structure():
    concepts = template_concepts(_profile(), count=3, language="he")
    assert len(concepts) == 3
    slugs = {c.slug for c in concepts}
    assert len(slugs) == 3  # distinct angles
    for concept in concepts:
        assert concept.hook
        assert concept.cta
        assert concept.caption
        assert 3 <= len(concept.scenes) <= 6
        assert concept.hashtags
        for scene in concept.scenes:
            assert 0 <= scene.media_index < 4
            assert scene.duration > 0


def test_template_concepts_use_business_name():
    concepts = template_concepts(_profile(), count=1, language="he")
    assert "מספרת דנה" in concepts[0].hook or "מספרת דנה" in concepts[0].caption


def test_generate_concepts_without_ai():
    concepts = generate_concepts(_profile(), count=2, language="auto", use_ai=False)
    assert len(concepts) == 2
    assert all(c.language == "he" for c in concepts)


def test_concept_roundtrip():
    concept = template_concepts(_profile(), count=1)[0]
    restored = ReelConcept.from_dict(concept.to_dict())
    assert restored == concept


def test_more_concepts_than_templates():
    concepts = template_concepts(_profile(), count=6, language="he")
    assert len(concepts) == 6
    assert len({c.slug for c in concepts}) == 6
