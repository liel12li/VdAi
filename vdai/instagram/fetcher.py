"""Fetch a business profile (bio + recent media) from Instagram.

Three access levels:

1. **Logged-in** — when an account was connected with
   ``python -m vdai login`` (see :mod:`vdai.instagram.auth`), the saved
   session is attached automatically. Far more reliable against rate
   limits, and private profiles the account follows become accessible.

2. **Anonymous** — works for public profiles, but Instagram aggressively
   rate-limits anonymous requests, especially from datacenter IPs.

3. **Local folder** — ``load_local_profile(media_dir, ...)`` builds a
   profile from a folder of images/videos. Useful offline, for testing,
   or when the user already has the brand assets on disk.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..models import BusinessProfile, Post
from .auth import InstagramAuthError, attach_session, normalize_username

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}

_LOGIN_HINT = (
    "התחברו לחשבון האינסטגרם שלכם בתוך התוכנה (כפתור 'התחברות לאינסטגרם'), "
    "או העלו תמונות של העסק ידנית."
)


class InstagramFetchError(RuntimeError):
    """Raised when Instagram data could not be retrieved."""


def fetch_profile(
    username: str,
    cache_dir: str | Path = ".vdai_cache",
    max_posts: int = 12,
) -> BusinessProfile:
    """Download an Instagram profile's bio, picture and recent media."""
    try:
        import instaloader
    except ImportError as exc:  # pragma: no cover
        raise InstagramFetchError(
            "instaloader is not installed. Run: pip install instaloader"
        ) from exc

    raw = username
    username = normalize_username(username)
    if not username:
        raise InstagramFetchError(
            f"לא הצלחתי לזהות שם משתמש מתוך {raw!r}. הדביקו את הקישור לעמוד "
            "(למשל https://instagram.com/cafe_dizengoff) או את השם אחרי ה-@. "
            "אם הדבקתם קישור לפוסט בודד — הדביקו במקום זה את הקישור לעמוד עצמו."
        )
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
        viewer = attach_session(loader, cache_dir)
    except InstagramAuthError as exc:
        raise InstagramFetchError(str(exc)) from exc
    if viewer:
        logger.info("🔓 גולש כ-@%s", viewer)

    try:
        profile = instaloader.Profile.from_username(loader.context, username)
    except instaloader.exceptions.ProfileNotExistsException as exc:
        if not viewer:
            # Anonymous requests are very often rejected with a false
            # "not found" — Instagram now requires login for most access.
            raise InstagramFetchError(
                f"לא הצלחתי למצוא את @{username}. כדאי לבדוק שהשם נכון (בדיוק כמו "
                f"שמופיע באינסטגרם), אבל לרוב הסיבה היא שאינסטגרם חוסם גישה ללא "
                f"התחברות. {_LOGIN_HINT}"
            ) from exc
        raise InstagramFetchError(
            f"הפרופיל @{username} לא נמצא. בדקו שהשם מדויק (כמו שמופיע באינסטגרם, "
            "בלי רווחים)."
        ) from exc
    except instaloader.exceptions.LoginRequiredException as exc:
        raise InstagramFetchError(
            f"אינסטגרם דורש התחברות כדי לצפות ב-@{username}. {_LOGIN_HINT}"
        ) from exc
    except instaloader.exceptions.ConnectionException as exc:
        raise InstagramFetchError(_blocked_message(username, viewer, exc)) from exc

    if profile.is_private and not viewer:
        raise InstagramFetchError(
            f"הפרופיל @{username} פרטי. חברו חשבון שעוקב אחריו "
            f"(python -m vdai login) או העבירו חומרים דרך --media-dir."
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
    except instaloader.exceptions.PrivateProfileNotFollowedException as exc:
        raise InstagramFetchError(
            f"הפרופיל @{username} פרטי והחשבון המחובר (@{viewer}) לא עוקב אחריו."
        ) from exc
    except instaloader.exceptions.LoginRequiredException as exc:
        raise InstagramFetchError(
            f"אינסטגרם דורש התחברות כדי להוריד פוסטים מ-@{username}. {_LOGIN_HINT}"
        ) from exc
    except instaloader.exceptions.ConnectionException as exc:
        if not biz.posts:
            raise InstagramFetchError(_blocked_message(username, viewer, exc)) from exc
        logger.warning("Stopped fetching posts early: %s", exc)

    if not biz.posts:
        raise InstagramFetchError(
            f"לא נמצאו פוסטים נגישים בפרופיל @{username}."
        )
    return biz


def _blocked_message(username: str, viewer: str | None, exc: Exception) -> str:
    base = f"אינסטגרם חסם את הבקשה ל-@{username} (rate limit). "
    if viewer:
        return base + f"נסו שוב בעוד כמה דקות, או עבדו עם --media-dir. ({exc})"
    return base + f"נסו שוב מאוחר יותר, התחברו עם חשבון ({_LOGIN_HINT}) " \
                  f"או השתמשו ב---media-dir. ({exc})"


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
