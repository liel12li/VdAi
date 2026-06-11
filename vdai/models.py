"""Core data models shared across the VdAi pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Post:
    """A single media item belonging to a business profile."""

    media_path: str
    is_video: bool = False
    caption: str = ""
    likes: int = 0
    shortcode: str = ""


@dataclass
class BusinessProfile:
    """Everything we know about the business we are promoting."""

    username: str
    full_name: str = ""
    biography: str = ""
    followers: int = 0
    external_url: str = ""
    category: str = ""
    profile_pic_path: str = ""
    posts: list[Post] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.full_name or self.username

    def media_paths(self) -> list[str]:
        return [p.media_path for p in self.posts]

    def to_dict(self) -> dict:
        return asdict(self)

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def from_dict(cls, data: dict) -> "BusinessProfile":
        posts = [Post(**p) for p in data.pop("posts", [])]
        return cls(posts=posts, **data)


@dataclass
class ReelScene:
    """One visual beat in a reel: a media item plus a short overlay line."""

    text: str
    media_index: int = 0
    duration: float = 2.8


@dataclass
class ReelConcept:
    """A complete creative concept for one promotional reel."""

    slug: str
    title: str
    hook: str
    scenes: list[ReelScene]
    cta: str
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    music_mood: str = "uplifting"
    style: str = "clean"  # clean | bold | elegant
    language: str = "he"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReelConcept":
        scenes = [ReelScene(**s) for s in data.pop("scenes", [])]
        return cls(scenes=scenes, **data)


@dataclass
class CaptionWord:
    word: str
    start: float
    end: float


@dataclass
class CaptionSegment:
    """A caption chunk displayed on screen between start and end."""

    text: str
    start: float
    end: float
    words: list[CaptionWord] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def concepts_to_json(concepts: list[ReelConcept]) -> str:
    return json.dumps(
        [c.to_dict() for c in concepts], ensure_ascii=False, indent=2
    )


def load_profile_json(path: str | Path) -> Optional[BusinessProfile]:
    p = Path(path)
    if not p.exists():
        return None
    return BusinessProfile.from_dict(json.loads(p.read_text(encoding="utf-8")))
