"""Generate reel concepts (hooks, copy, CTA, captions) for a business.

Uses the Claude API when ``ANTHROPIC_API_KEY`` is configured; otherwise
falls back to solid built-in templates so the pipeline always works.
"""

from __future__ import annotations

import logging
import os
import re

from ..config import settings
from ..models import BusinessProfile, ReelConcept, ReelScene

logger = logging.getLogger(__name__)

MOODS = ["energetic", "chill", "elegant", "uplifting"]
STYLES = ["clean", "bold", "elegant"]

_CONCEPTS_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Short ascii id for filenames, e.g. 'showcase'",
                    },
                    "title": {"type": "string"},
                    "hook": {
                        "type": "string",
                        "description": "Opening line, max 8 words, stops the scroll",
                    },
                    "scenes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {
                                    "type": "string",
                                    "description": "Overlay line, max 7 words",
                                },
                                "media_index": {"type": "integer"},
                                "duration": {"type": "number"},
                            },
                            "required": ["text", "media_index", "duration"],
                            "additionalProperties": False,
                        },
                    },
                    "cta": {"type": "string"},
                    "caption": {
                        "type": "string",
                        "description": "Instagram post caption for this reel",
                    },
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "music_mood": {"type": "string", "enum": MOODS},
                    "style": {"type": "string", "enum": STYLES},
                },
                "required": [
                    "slug",
                    "title",
                    "hook",
                    "scenes",
                    "cta",
                    "caption",
                    "hashtags",
                    "music_mood",
                    "style",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["concepts"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
You are a senior creative director specializing in short-form vertical video
ads (Instagram Reels) for small businesses. You write hooks that stop the
scroll in the first second, punchy on-screen lines, and clear calls to action.

You will receive a business profile and an indexed list of its available media
(photos/videos from its Instagram page). Design distinct reel concepts that a
video engine will render: each concept has a hook card, 3-5 scenes (each scene
shows one media item with a short overlay line), and a CTA outro.

Rules:
- Write ALL user-facing text (hook, scene texts, cta, caption) in the requested
  language. Hashtags may mix the requested language and English.
- Hook: max 8 words. Scene text: max 7 words. CTA: max 6 words, imperative.
- Each concept must have a clearly different angle (e.g. product showcase,
  social proof, behind the scenes, problem→solution, limited offer).
- media_index must reference the provided media list; prefer the most
  relevant/striking items, vary them between concepts when possible.
- duration per scene: between 1.8 and 4.0 seconds.
- Captions: 1-3 short sentences + a question or CTA, then 5-10 hashtags
  relevant to the business and locale.
- Never invent facts (prices, addresses, claims) that are not in the profile.
"""


def detect_language(profile: BusinessProfile, requested: str = "auto") -> str:
    """Return 'he' / 'en' (or any explicit requested code)."""
    if requested and requested != "auto":
        return requested
    text = " ".join(
        [profile.full_name, profile.biography] + [p.caption for p in profile.posts]
    )
    return "he" if re.search(r"[֐-׿]", text) else "en"


def generate_concepts(
    profile: BusinessProfile,
    count: int = 3,
    language: str = "auto",
    use_ai: bool = True,
) -> list[ReelConcept]:
    """Return ``count`` reel concepts for the profile."""
    lang = detect_language(profile, language)
    if use_ai and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return _claude_concepts(profile, count, lang)
        except Exception as exc:  # noqa: BLE001 - always deliver something
            logger.warning("Claude concept generation failed (%s); using templates", exc)
    return template_concepts(profile, count, lang)


def _media_inventory(profile: BusinessProfile) -> str:
    lines = []
    for i, post in enumerate(profile.posts):
        kind = "video" if post.is_video else "photo"
        caption = post.caption.replace("\n", " ")[:120]
        likes = f", {post.likes} likes" if post.likes else ""
        lines.append(f"[{i}] {kind}{likes} — caption: {caption!r}")
    return "\n".join(lines)


def _claude_concepts(profile: BusinessProfile, count: int, lang: str) -> list[ReelConcept]:
    import anthropic

    client = anthropic.Anthropic()
    lang_name = {"he": "Hebrew", "en": "English"}.get(lang, lang)

    user_prompt = f"""\
Business profile:
- Username: @{profile.username}
- Name: {profile.display_name}
- Bio: {profile.biography or "(empty)"}
- Followers: {profile.followers}
- Category: {profile.category or "(unknown)"}
- Website: {profile.external_url or "(none)"}

Available media ({len(profile.posts)} items):
{_media_inventory(profile)}

Create exactly {count} distinct reel concepts in {lang_name}.
"""

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": {"type": "json_schema", "schema": _CONCEPTS_SCHEMA}},
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")

    import json

    text = next(b.text for b in response.content if b.type == "text")
    raw = json.loads(text)["concepts"]
    concepts = [
        ReelConcept(
            slug=c["slug"],
            title=c["title"],
            hook=c["hook"],
            scenes=[ReelScene(**s) for s in c["scenes"]],
            cta=c["cta"],
            caption=c["caption"],
            hashtags=c["hashtags"],
            music_mood=c["music_mood"],
            style=c["style"],
            language=lang,
        )
        for c in raw
    ]
    return _sanitize(concepts, profile, count, lang)


def _sanitize(
    concepts: list[ReelConcept], profile: BusinessProfile, count: int, lang: str
) -> list[ReelConcept]:
    """Clamp model output to values the renderer can always handle."""
    n_media = max(1, len(profile.posts))
    cleaned: list[ReelConcept] = []
    for i, concept in enumerate(concepts[:count]):
        concept.slug = re.sub(r"[^a-z0-9_-]+", "-", concept.slug.lower()).strip("-") or f"reel-{i + 1}"
        concept.scenes = concept.scenes[:6] or [ReelScene(text=concept.hook)]
        for scene in concept.scenes:
            scene.media_index = min(max(scene.media_index, 0), n_media - 1)
            scene.duration = min(max(scene.duration, 1.8), 4.0)
        if concept.music_mood not in MOODS:
            concept.music_mood = "uplifting"
        if concept.style not in STYLES:
            concept.style = "clean"
        cleaned.append(concept)
    while len(cleaned) < count:
        cleaned.extend(
            template_concepts(profile, count - len(cleaned), lang, offset=len(cleaned))
        )
    # Unique slugs for filenames
    seen: set[str] = set()
    for i, concept in enumerate(cleaned):
        if concept.slug in seen:
            concept.slug = f"{concept.slug}-{i + 1}"
        seen.add(concept.slug)
    return cleaned[:count]


# --------------------------------------------------------------------------
# Template fallback (no API key needed)
# --------------------------------------------------------------------------

_TEMPLATES = {
    "he": [
        {
            "slug": "showcase",
            "title": "הצגת המוצרים",
            "hook": "מכירים את {name}?",
            "scenes": ["העבודות הכי שוות שלנו", "כל פרט מקבל תשומת לב", "איכות שרואים מקילומטר"],
            "cta": "עקבו ושלחו הודעה",
            "caption": "הצצה למה שאנחנו עושים ב{name} 🤩 איזה הכי אהבתם?",
            "music_mood": "uplifting",
            "style": "clean",
        },
        {
            "slug": "why-us",
            "title": "למה דווקא אנחנו",
            "hook": "3 סיבות לבחור בנו",
            "scenes": ["ניסיון של שנים בתחום", "שירות אישי לכל לקוח", "תוצאות שמדברות בעד עצמן"],
            "cta": "דברו איתנו עוד היום",
            "caption": "למה לקוחות חוזרים אלינו? בדיוק בגלל זה 💪 מחכים לכם בהודעות.",
            "music_mood": "energetic",
            "style": "bold",
        },
        {
            "slug": "behind-scenes",
            "title": "מאחורי הקלעים",
            "hook": "ככה זה נראה מבפנים",
            "scenes": ["הכל מתחיל באהבה למקצוע", "עובדים על כל פרט", "וזו התוצאה הסופית"],
            "cta": "בואו לבקר אותנו",
            "caption": "קצת מאחורי הקלעים של {name} ✨ יש שאלות? אנחנו פה.",
            "music_mood": "chill",
            "style": "elegant",
        },
        {
            "slug": "offer",
            "title": "הנעה לפעולה",
            "hook": "אל תפספסו את זה",
            "scenes": ["בדיוק מה שחיפשתם", "בדיוק במקום אחד", "מחכים רק לכם"],
            "cta": "שריינו מקום עכשיו",
            "caption": "הזמן הכי טוב להתחיל הוא עכשיו ⏰ שלחו לנו הודעה ונחזור אליכם.",
            "music_mood": "energetic",
            "style": "bold",
        },
    ],
    "en": [
        {
            "slug": "showcase",
            "title": "Product showcase",
            "hook": "Have you met {name}?",
            "scenes": ["Our finest work, in one place", "Every detail gets full attention", "Quality you can see"],
            "cta": "Follow & DM us",
            "caption": "A peek at what we do at {name} 🤩 Which one is your favorite?",
            "music_mood": "uplifting",
            "style": "clean",
        },
        {
            "slug": "why-us",
            "title": "Why choose us",
            "hook": "3 reasons to choose us",
            "scenes": ["Years of hands-on experience", "Personal service, every time", "Results that speak for themselves"],
            "cta": "Talk to us today",
            "caption": "Why do clients keep coming back? Exactly this 💪 DM us anytime.",
            "music_mood": "energetic",
            "style": "bold",
        },
        {
            "slug": "behind-scenes",
            "title": "Behind the scenes",
            "hook": "This is how it's made",
            "scenes": ["It starts with passion", "We sweat every detail", "And this is the result"],
            "cta": "Come visit us",
            "caption": "A little behind the scenes at {name} ✨ Questions? We're here.",
            "music_mood": "chill",
            "style": "elegant",
        },
        {
            "slug": "offer",
            "title": "Call to action",
            "hook": "Don't miss this",
            "scenes": ["Exactly what you were looking for", "All in one place", "We're waiting for you"],
            "cta": "Book your spot now",
            "caption": "The best time to start is now ⏰ Send us a message and we'll get back to you.",
            "music_mood": "energetic",
            "style": "bold",
        },
    ],
}


def template_concepts(
    profile: BusinessProfile, count: int = 3, language: str = "he", offset: int = 0
) -> list[ReelConcept]:
    """Deterministic concepts that work without any API access."""
    templates = _TEMPLATES.get(language, _TEMPLATES["en"])
    n_media = max(1, len(profile.posts))
    concepts = []
    for i in range(count):
        tpl = templates[(offset + i) % len(templates)]
        scenes = [
            ReelScene(
                text=line,
                media_index=(offset + i + j) % n_media,
                duration=2.8,
            )
            for j, line in enumerate(tpl["scenes"])
        ]
        hashtags = _default_hashtags(profile, language)
        concepts.append(
            ReelConcept(
                slug=f"{tpl['slug']}-{offset + i + 1}" if count > len(templates) else tpl["slug"],
                title=tpl["title"],
                hook=tpl["hook"].format(name=profile.display_name),
                scenes=scenes,
                cta=tpl["cta"],
                caption=tpl["caption"].format(name=profile.display_name),
                hashtags=hashtags,
                music_mood=tpl["music_mood"],
                style=tpl["style"],
                language=language,
            )
        )
    return concepts


def _default_hashtags(profile: BusinessProfile, language: str) -> list[str]:
    tags = [f"#{profile.username}"]
    words = re.findall(r"[\w֐-׿]{3,}", profile.biography)[:4]
    tags += [f"#{w}" for w in words]
    tags += ["#smallbusiness", "#reels"] if language == "en" else ["#עסקים_קטנים", "#ריל"]
    # Dedupe, keep order
    seen: set[str] = set()
    return [t for t in tags if not (t.lower() in seen or seen.add(t.lower()))][:8]
