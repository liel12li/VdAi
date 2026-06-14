"""Tests for username normalization and the web login flow (no network)."""

import instaloader
import pytest

from vdai.instagram import auth


# ---- normalize_username ----

@pytest.mark.parametrize("raw,expected", [
    ("cafe_dizengoff", "cafe_dizengoff"),
    ("@cafe_dizengoff", "cafe_dizengoff"),
    ("  @Cafe_Dizengoff  ", "cafe_dizengoff"),
    ("https://www.instagram.com/cafe_dizengoff/", "cafe_dizengoff"),
    ("https://instagram.com/cafe_dizengoff/?hl=en", "cafe_dizengoff"),
    ("instagram.com/cafe_dizengoff", "cafe_dizengoff"),
    ("www.instagram.com/cafe_dizengoff/reels/", "cafe_dizengoff"),
    ("http://instagram.com/Cafe.Dizengoff_1", "cafe.dizengoff_1"),
])
def test_normalize_username_variants(raw, expected):
    assert auth.normalize_username(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "@", "https://instagram.com/p/ABC123/", "instagram.com/reel/XYZ/",
    "https://www.instagram.com/explore/",
])
def test_normalize_username_rejects_non_handles(raw):
    assert auth.normalize_username(raw) == ""


def test_session_file_uses_normalized_handle(tmp_path):
    a = auth.session_file(tmp_path, "https://instagram.com/MyCafe/")
    b = auth.session_file(tmp_path, "@mycafe")
    assert a == b
    assert a.name == "session-mycafe"


# ---- web login flow (fake loader, no network) ----

class _FakeLoader:
    def __init__(self, *a, **k):
        self.saved = None

    def login(self, user, password):
        if password == "twofa":
            raise instaloader.exceptions.TwoFactorAuthRequiredException("2fa")
        if password != "correct":
            raise instaloader.exceptions.BadCredentialsException("bad")

    def two_factor_login(self, code):
        if code != "123456":
            raise instaloader.exceptions.BadCredentialsException("bad code")

    def save_session_to_file(self, filename):
        from pathlib import Path
        Path(filename).write_text("session")
        self.saved = filename


@pytest.fixture
def fake_loader(monkeypatch):
    monkeypatch.setattr(instaloader, "Instaloader", _FakeLoader)
    auth._PENDING_2FA.clear()


def test_begin_web_login_success(tmp_path, fake_loader):
    result = auth.begin_web_login("@MyCafe", "correct", tmp_path)
    assert result == {"status": "ok", "username": "mycafe"}
    assert auth.session_file(tmp_path, "mycafe").exists()


def test_begin_web_login_bad_password(tmp_path, fake_loader):
    with pytest.raises(auth.InstagramAuthError, match="שם המשתמש או הסיסמה"):
        auth.begin_web_login("mycafe", "wrong", tmp_path)


def test_begin_web_login_empty_username(tmp_path, fake_loader):
    with pytest.raises(auth.InstagramAuthError, match="שם משתמש"):
        auth.begin_web_login("https://instagram.com/p/ABC/", "correct", tmp_path)


def test_web_login_two_factor_flow(tmp_path, fake_loader):
    started = auth.begin_web_login("mycafe", "twofa", tmp_path)
    assert started["status"] == "2fa"
    login_id = started["login_id"]
    assert login_id in auth._PENDING_2FA

    done = auth.complete_web_login_2fa(login_id, "123 456", tmp_path)
    assert done == {"status": "ok", "username": "mycafe"}
    assert auth.session_file(tmp_path, "mycafe").exists()
    assert login_id not in auth._PENDING_2FA  # cleaned up


def test_web_login_two_factor_bad_code(tmp_path, fake_loader):
    started = auth.begin_web_login("mycafe", "twofa", tmp_path)
    with pytest.raises(auth.InstagramAuthError, match="קוד האימות שגוי"):
        auth.complete_web_login_2fa(started["login_id"], "000000", tmp_path)


def test_complete_2fa_expired_login_id(tmp_path, fake_loader):
    with pytest.raises(auth.InstagramAuthError, match="פג תוקף"):
        auth.complete_web_login_2fa("nonexistent", "123456", tmp_path)


# ---- checkpoint message + cookie-based login ----

def test_checkpoint_message_recommends_browser():
    exc = Exception("Checkpoint required. Point your browser to "
                    "https://www.instagram.com/auth_platform/codeentry/?x=1 - follow")
    out = auth._format_connection_error(exc)
    assert "התחברות דרך הדפדפן" in out
    assert "auth_platform" in out  # keeps the link for the user


def test_generic_connection_message():
    out = auth._format_connection_error(Exception("temporary failure"))
    assert "אינסטגרם חסם" in out


class _CookieLoader:
    """Fake loader exercising the cookie session path."""
    result = "liel_bentabo"

    def __init__(self, *a, **k):
        self.context = type("Ctx", (), {})()
        self.context._session = type("S", (), {"cookies": _DummyJar()})()
        self.context.username = None

    def test_login(self):
        return type(self).result

    def save_session_to_file(self, filename):
        from pathlib import Path
        Path(filename).write_text("session")


class _DummyJar:
    def update(self, cookies):
        self.cookies = cookies


def test_login_with_sessionid_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(instaloader, "Instaloader", _CookieLoader)
    result = auth.login_with_sessionid("abc123", tmp_path)
    assert result == {"status": "ok", "username": "liel_bentabo"}
    assert auth.session_file(tmp_path, "liel_bentabo").exists()


def test_login_with_sessionid_empty(tmp_path):
    with pytest.raises(auth.InstagramAuthError, match="sessionid"):
        auth.login_with_sessionid("   ", tmp_path)


def test_login_with_sessionid_invalid(tmp_path, monkeypatch):
    class Bad(_CookieLoader):
        result = None
    monkeypatch.setattr(instaloader, "Instaloader", Bad)
    with pytest.raises(auth.InstagramAuthError, match="לא תקף"):
        auth.login_with_sessionid("bad", tmp_path)


def test_import_browser_session_no_cookies(tmp_path, monkeypatch):
    import sys
    import types
    fake_bc3 = types.ModuleType("browser_cookie3")
    fake_bc3.firefox = lambda **k: (_ for _ in ()).throw(Exception("no firefox"))
    fake_bc3.chrome = lambda **k: {}  # empty cookies → test_login returns None
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_bc3)

    class NoLogin(_CookieLoader):
        result = None
    monkeypatch.setattr(instaloader, "Instaloader", NoLogin)
    with pytest.raises(auth.InstagramAuthError, match="לא נמצא חיבור פעיל"):
        auth.import_browser_session(tmp_path)


def test_import_browser_session_success(tmp_path, monkeypatch):
    import sys
    import types
    fake_bc3 = types.ModuleType("browser_cookie3")
    fake_bc3.chrome = lambda **k: {"sessionid": "x"}
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_bc3)
    monkeypatch.setattr(instaloader, "Instaloader", _CookieLoader)
    result = auth.import_browser_session(tmp_path, browser="chrome")
    assert result["status"] == "ok"
    assert result["username"] == "liel_bentabo"
