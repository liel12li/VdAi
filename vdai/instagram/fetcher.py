"""Fetch a business profile (bio + recent media) from Instagram.

Two modes:

1. ``fetch_profile(username)`` — uses :mod:`instaloader` to download the
   public profile picture and recent posts into a local cache directory.
   Instagram aggressively rate-limits anonymous requests from datacenter
   IPs, so this can fail; callers should surface the error and suggest
   the local-folder mode.

2. ``load_local_profile(media_dir, ...)`` — builds a profile from a local
   folder of images/videos. Useful offline, for testing, or when the user
   already has the brand assets on disk.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..models import BusinessProfile, Post

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


class InstagramFetchError(RuntimeError):
    """Raised when Instagram data could not be retrieved."""


def fetch_profile(
    username: str,
    cache_dir: str | Path = ".vdai_cache",
    max_posts: int = 12,
) -> BusinessProfile:
    """Download a public Instagram profile's bio, picture and recent media."""
    try:
        import instaloader
    except ImportError as exc:  # pragma: no cover
        raise InstagramFetchError(
            "instaloader is not installed. Run: pip install instaloader"
        ) from exc

    username = username.lstrip("@").strip().rstrip("/").split("/")[-1]
    target_dir = Path(cache_dir) / "instagram" / username
    target_dir.mkdir(parents=True, exist_ok=True)

    loader = instaloader.Instaloader(
        dirname_pattern=str(target_dir),
        download_comments=False,
        download_geotags=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        quiet=True,
    )

    try:
        profile = instaloader.Profile.from_username(loader.context, username)
    except instaloader.exceptions.ProfileNotExistsException as exc:
        raise InstagramFetchError(f"הפרופיל @{username} לא נמצא") from exc
    except instaloader.exceptions.ConnectionException as exc:
        raise InstagramFetchError(
            f"אינסטגרם חסם את הבקשה (rate limit). נסו שוב מאוחר יותר או השתמשו "
            f"ב---media-dir עם תיקייה מקומית. ({exc})"
        ) from exc

    if profile.is_private:
        raise InstagramFetchError(
            f"הפרופיל @{username} פרטי — אפשר לעבוד רק עם פרופילים ציבוריים, "
            "או להעביר חומרים דרך --media-dir."
        )

    biz = BusinessProfile(
        username=profile.username,
        full_name=profile.full_name or "",
        biography=profile.biography or "",
        followers=profile.followers,
        external_url=profile.external_url or "",
        category=getattr(profile, "business_category_name", "") or "",
    )

    # Profile picture
    try:
        loader.download_profilepic(profile)
        pics = sorted(target_dir.glob("*profile_pic*"))
        if pics:
            biz.profile_pic_path = str(pics[-1])
    except Exception as exc:  # noqa: BLE001 - non-fatal
        logger.warning("Could not download profile picture: %s", exc)

    # Recent posts
    count = 0
    try:
        for post in profile.get_posts():
            if count >= max_posts:
                break
            try:
                loader.download_post(post, target=username)
            except Exception as exc:  # noqa: BLE001 - skip broken posts
                logger.warning("Skipping post %s: %s", post.shortcode, exc)
                continue
            media = _newest_media(target_dir, exclude={p.media_path for p in biz.posts})
            if media is None:
                continue
            biz.posts.append(
                Post(
                    media_path=str(media),
                    is_video=media.suffix.lower() in VIDEO_EXTS,
                    caption=(post.caption or "")[:500],
                    likes=post.likes or 0,
                    shortcode=post.shortcode,
                )
            )
            count += 1
    except instaloader.exceptions.ConnectionException as exc:
        if not biz.posts:
            raise InstagramFetchError(
                f"אינסטגרם חסם את הורדת הפוסטים ({exc}). נסו שוב מאוחר יותר."
            ) from exc
        logger.warning("Stopped fetching posts early: %s", exc)

    if not biz.posts:
        raise InstagramFetchError(
            f"לא נמצאו פוסטים ציבוריים בפרופיל @{username}."
        )
    return biz


def _newest_media(directory: Path, exclude: set[str]) -> Path | None:
    candidates = [
        p
        for p in directory.iterdir()
        if p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS
        and "profile_pic" not in p.name
        and str(p) not in exclude
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_local_profile(
    media_dir: str | Path,
    username: str = "my_business",
    full_name: str = "",
    biography: str = "",
) -> BusinessProfile:
    """Build a profile from a local folder of images and videos."""
    directory = Path(media_dir)
    if not directory.is_dir():
        raise InstagramFetchError(f"התיקייה {media_dir} לא קיימת")

    files = sorted(
        p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS
    )
    if not files:
        raise InstagramFetchError(
            f"לא נמצאו תמונות או סרטונים בתיקייה {media_dir} "
            f"(נתמכים: {', '.join(sorted(IMAGE_EXTS | VIDEO_EXTS))})"
        )

    username = re.sub(r"[^\w.]+", "_", username.lstrip("@")) or "my_business"
    posts = [
        Post(media_path=str(p), is_video=p.suffix.lower() in VIDEO_EXTS)
        for p in files
    ]
    return BusinessProfile(
        username=username,
        full_name=full_name,
        biography=biography,
        posts=posts,
    )
