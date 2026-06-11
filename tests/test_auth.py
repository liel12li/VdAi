"""Tests for Instagram session management (no network calls)."""

import instaloader
import pytest

from vdai.instagram import auth


def test_session_file_normalizes_username(tmp_path):
    path = auth.session_file(tmp_path, "@My_Cafe ")
    assert path.name == "session-my_cafe"
    assert str(tmp_path) in str(path)


def test_configured_username_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("VDAI_IG_USER", "@Env_User")
    assert auth.configured_username(tmp_path) == "env_user"


def test_configured_username_from_newest_session(tmp_path, monkeypatch):
    monkeypatch.delenv("VDAI_IG_USER", raising=False)
    sessions = auth.sessions_dir(tmp_path)
    sessions.mkdir(parents=True)
    old = sessions / "session-old_account"
    new = sessions / "session-new_account"
    old.write_text("x")
    new.write_text("x")
    import os
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert auth.configured_username(tmp_path) == "new_account"


def test_configured_username_none(tmp_path, monkeypatch):
    monkeypatch.delenv("VDAI_IG_USER", raising=False)
    assert auth.configured_username(tmp_path) is None


def test_attach_session_anonymous_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("VDAI_IG_USER", raising=False)
    monkeypatch.delenv("VDAI_IG_PASSWORD", raising=False)

    class Boom:
        def __getattr__(self, name):  # loader must not be touched
            raise AssertionError("loader should not be used in anonymous mode")

    assert auth.attach_session(Boom(), tmp_path) is None


def test_logout_removes_sessions(tmp_path):
    sessions = auth.sessions_dir(tmp_path)
    sessions.mkdir(parents=True)
    (sessions / "session-a").write_text("x")
    (sessions / "session-b").write_text("x")
    removed = auth.logout(tmp_path)
    assert len(removed) == 2
    assert not list(sessions.glob("session-*"))


def test_logout_specific_user(tmp_path):
    sessions = auth.sessions_dir(tmp_path)
    sessions.mkdir(parents=True)
    (sessions / "session-a").write_text("x")
    (sessions / "session-b").write_text("x")
    removed = auth.logout(tmp_path, "@A")
    assert [p.name for p in removed] == ["session-a"]
    assert (sessions / "session-b").exists()


class _FakeLoader:
    """Stands in for instaloader.Instaloader in login flows."""

    def __init__(self, *args, **kwargs):
        self.two_factor_code = None
        self.saved_to = None

    def login(self, user, password):
        if password == "needs2fa":
            raise instaloader.exceptions.TwoFactorAuthRequiredException("2fa")
        if password != "correct":
            raise instaloader.exceptions.BadCredentialsException("bad")

    def two_factor_login(self, code):
        self.two_factor_code = code
        if code != "123456":
            raise instaloader.exceptions.BadCredentialsException("bad code")

    def save_session_to_file(self, filename):
        self.saved_to = filename
        from pathlib import Path
        Path(filename).write_text("session-data")


@pytest.fixture
def fake_loader(monkeypatch):
    monkeypatch.setattr(instaloader, "Instaloader", _FakeLoader)


def test_interactive_login_saves_session(tmp_path, fake_loader):
    auth.interactive_login("My_User", "correct", tmp_path)
    assert auth.session_file(tmp_path, "my_user").exists()


def test_interactive_login_bad_password(tmp_path, fake_loader):
    with pytest.raises(auth.InstagramAuthError, match="סיסמה שגויה"):
        auth.interactive_login("user", "wrong", tmp_path)
    assert not auth.session_file(tmp_path, "user").exists()


def test_interactive_login_two_factor_flow(tmp_path, fake_loader):
    auth.interactive_login(
        "user", "needs2fa", tmp_path, two_factor_provider=lambda: "123 456"
    )
    assert auth.session_file(tmp_path, "user").exists()


def test_interactive_login_two_factor_bad_code(tmp_path, fake_loader):
    with pytest.raises(auth.InstagramAuthError, match="הדו-שלבי שגוי"):
        auth.interactive_login(
            "user", "needs2fa", tmp_path, two_factor_provider=lambda: "000000"
        )


def test_attach_session_password_login_via_env(tmp_path, monkeypatch, fake_loader):
    monkeypatch.setenv("VDAI_IG_USER", "user")
    monkeypatch.setenv("VDAI_IG_PASSWORD", "correct")
    loader = _FakeLoader()
    assert auth.attach_session(loader, tmp_path) == "user"
    assert auth.session_file(tmp_path, "user").exists()


def test_attach_session_env_2fa_raises_helpful_error(tmp_path, monkeypatch, fake_loader):
    monkeypatch.setenv("VDAI_IG_USER", "user")
    monkeypatch.setenv("VDAI_IG_PASSWORD", "needs2fa")
    with pytest.raises(auth.InstagramAuthError, match="vdai login"):
        auth.attach_session(_FakeLoader(), tmp_path)
