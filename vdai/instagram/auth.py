"""Instagram account login & session management.

Connecting an account gives the fetcher "eyes" on Instagram: logged-in
requests are far less likely to be rate-limited, and private profiles the
account follows become accessible.

Flow: ``python -m vdai login <username>`` performs an interactive login
(password + optional 2FA code) and saves an instaloader session file under
the cache directory. Every subsequent fetch transparently reuses it.
The password itself is never stored — only the session cookies.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_PREFIX = "session-"


class InstagramAuthError(RuntimeError):
    pass


def sessions_dir(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / "instagram"


def session_file(cache_dir: str | Path, username: str) -> Path:
    return sessions_dir(cache_dir) / f"{SESSION_PREFIX}{_norm(username)}"


def _norm(username: str) -> str:
    return username.lstrip("@").strip().lower()


def configured_username(cache_dir: str | Path) -> str | None:
    """The account to act as: VDAI_IG_USER, else the newest saved session."""
    env_user = os.environ.get("VDAI_IG_USER", "").strip()
    if env_user:
        return _norm(env_user)
    directory = sessions_dir(cache_dir)
    if not directory.is_dir():
        return None
    sessions = sorted(
        directory.glob(f"{SESSION_PREFIX}*"), key=lambda p: p.stat().st_mtime
    )
    if not sessions:
        return None
    return sessions[-1].name[len(SESSION_PREFIX):]


def attach_session(loader, cache_dir: str | Path) -> str | None:
    """Attach the configured account to an Instaloader instance.

    Returns the username on success, ``None`` when no account is configured
    (anonymous mode). A corrupt session falls back to anonymous with a
    warning; bad env credentials raise so the user notices.
    """
    username = configured_username(cache_dir)
    if not username:
        return None

    path = session_file(cache_dir, username)
    if path.exists():
        try:
            loader.load_session_from_file(username, str(path))
            logger.info("Using saved Instagram session of @%s", username)
            return username
        except Exception as exc:  # noqa: BLE001 - stale/corrupt session file
            logger.warning(
                "הסשן השמור של @%s לא תקין (%s) — הריצו שוב: python -m vdai login %s",
                username, exc, username,
            )

    password = os.environ.get("VDAI_IG_PASSWORD", "")
    if password:
        _password_login(loader, username, password, cache_dir)
        return username
    return None


def _password_login(loader, username: str, password: str, cache_dir: str | Path) -> None:
    import instaloader

    try:
        loader.login(username, password)
    except instaloader.exceptions.TwoFactorAuthRequiredException as exc:
        raise InstagramAuthError(
            f"לחשבון @{username} מופעל אימות דו-שלבי — התחברו פעם אחת באופן "
            f"אינטראקטיבי: python -m vdai login {username}"
        ) from exc
    except instaloader.exceptions.BadCredentialsException as exc:
        raise InstagramAuthError(f"סיסמה שגויה לחשבון @{username}") from exc
    except instaloader.exceptions.ConnectionException as exc:
        raise InstagramAuthError(
            f"אינסטגרם חסם את ניסיון ההתחברות של @{username} ({exc}). "
            "אשרו את ההתחברות באפליקציה ונסו שוב."
        ) from exc
    _save(loader, username, cache_dir)


def interactive_login(
    username: str,
    password: str,
    cache_dir: str | Path,
    two_factor_provider=None,
) -> None:
    """Login with password, asking for a 2FA code via ``two_factor_provider``
    when Instagram requires one, then persist the session."""
    import instaloader

    username = _norm(username)
    loader = instaloader.Instaloader(quiet=True)
    try:
        loader.login(username, password)
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        if two_factor_provider is None:
            raise InstagramAuthError("נדרש קוד אימות דו-שלבי")
        code = str(two_factor_provider()).strip().replace(" ", "")
        try:
            loader.two_factor_login(code)
        except instaloader.exceptions.BadCredentialsException as exc:
            raise InstagramAuthError("קוד האימות הדו-שלבי שגוי") from exc
    except instaloader.exceptions.BadCredentialsException as exc:
        raise InstagramAuthError(f"סיסמה שגויה לחשבון @{username}") from exc
    except instaloader.exceptions.ConnectionException as exc:
        raise InstagramAuthError(
            f"אינסטגרם חסם את ניסיון ההתחברות ({exc}). "
            "פתחו את אפליקציית אינסטגרם, אשרו שזה אתם ('It was me'), ונסו שוב."
        ) from exc
    _save(loader, username, cache_dir)


def _save(loader, username: str, cache_dir: str | Path) -> Path:
    path = session_file(cache_dir, username)
    path.parent.mkdir(parents=True, exist_ok=True)
    loader.save_session_to_file(str(path))
    try:
        path.chmod(0o600)  # session cookies grant account access — owner only
    except OSError:
        pass
    logger.info("Instagram session of @%s saved to %s", username, path)
    return path


def check_session(cache_dir: str | Path) -> tuple[str | None, bool]:
    """(configured username, is the saved session still valid on Instagram)."""
    import instaloader

    username = configured_username(cache_dir)
    if not username:
        return None, False
    path = session_file(cache_dir, username)
    if not path.exists():
        return username, False
    loader = instaloader.Instaloader(quiet=True)
    try:
        loader.load_session_from_file(username, str(path))
        return username, loader.test_login() is not None
    except Exception:  # noqa: BLE001
        return username, False


def logout(cache_dir: str | Path, username: str | None = None) -> list[Path]:
    """Delete saved session file(s); returns the paths removed."""
    directory = sessions_dir(cache_dir)
    if not directory.is_dir():
        return []
    pattern = f"{SESSION_PREFIX}{_norm(username)}" if username else f"{SESSION_PREFIX}*"
    removed = []
    for path in directory.glob(pattern):
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed
