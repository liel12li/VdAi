"""Web app tests: font route, robust JSON errors, and UI wiring."""

import instaloader
import pytest
from fastapi.testclient import TestClient

from vdai.web.app import app

client = TestClient(app)


def test_font_route_served():
    r = client.get("/font/heebo.ttf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/ttf"
    assert len(r.content) > 1000


def test_index_has_key_ui_elements():
    html = client.get("/").text
    for needle in [
        '/font/heebo.ttf', 'id="igConnectBtn"', 'id="igUser"', 'id="ig2faSubmit"',
        'id="drop"', 'name="username"', 'id="go"', 'class="cta"',
    ]:
        assert needle in html, needle


def test_manifest_and_status():
    assert client.get("/manifest.json").json()["short_name"] == "VdAi"
    assert "instagram_user" in client.get("/api/status").json()


def test_login_unexpected_error_returns_json_not_500(monkeypatch):
    """The JSON-parse bug: an unexpected exception must still be clean JSON."""
    class BoomLoader:
        def __init__(self, *a, **k):
            pass
        def login(self, u, p):
            raise RuntimeError("internal parse failure")

    monkeypatch.setattr(instaloader, "Instaloader", BoomLoader)
    r = client.post("/api/instagram/login", data={"username": "x", "password": "y"})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()  # must be valid JSON (this is the bug we fixed)
    assert "detail" in body


def test_login_bad_credentials_message(monkeypatch):
    class BadLoader:
        def __init__(self, *a, **k):
            pass
        def login(self, u, p):
            raise instaloader.exceptions.BadCredentialsException("bad")

    monkeypatch.setattr(instaloader, "Instaloader", BadLoader)
    r = client.post("/api/instagram/login", data={"username": "x", "password": "y"})
    assert r.status_code == 400
    assert "שגוי" in r.json()["detail"]


def test_logout_endpoint():
    r = client.post("/api/instagram/logout")
    assert r.status_code == 200
    assert "removed" in r.json()
