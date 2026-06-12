"""Tests for the desktop launcher and shortcut installer (no GUI needed)."""

import sys

import pytest

from vdai import desktop


def test_icons_exist():
    assert desktop.ICON_PNG.exists()
    assert desktop.ICON_ICO.exists()


def test_linux_desktop_entry_content():
    entry = desktop.linux_desktop_entry("/usr/bin/python3", "/opt/vdai", "/opt/icon.png")
    assert "[Desktop Entry]" in entry
    assert 'Exec="/usr/bin/python3" -m vdai desktop' in entry
    assert "Path=/opt/vdai" in entry
    assert "Icon=/opt/icon.png" in entry
    assert "Terminal=false" in entry


def test_macos_command_content():
    content = desktop.macos_command_content("/usr/bin/python3", "/opt/vdai")
    assert content.startswith("#!/bin/bash")
    assert 'cd "/opt/vdai"' in content
    assert 'exec "/usr/bin/python3" -m vdai desktop' in content


def test_windows_shortcut_script():
    script = desktop.windows_shortcut_script(
        r"C:\Python\pythonw.exe", r"C:\vdai", r"C:\Users\u\Desktop\VdAi.lnk", r"C:\icon.ico"
    )
    assert "CreateShortcut" in script
    assert "-m vdai desktop" in script
    assert "pythonw.exe" in script


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="linux shortcut path")
def test_create_desktop_shortcut_linux(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # keep the app-menu copy in tmp
    shortcut = desktop.create_desktop_shortcut(desktop_dir=tmp_path / "Desktop")
    assert shortcut.exists()
    assert shortcut.name == "vdai.desktop"
    content = shortcut.read_text(encoding="utf-8")
    assert "-m vdai desktop" in content
    assert str(desktop.ICON_PNG) in content
    # registered in the applications menu too
    assert (tmp_path / ".local" / "share" / "applications" / "vdai.desktop").exists()


def test_free_port_returns_usable_port():
    port = desktop._free_port("127.0.0.1", 0)
    assert 0 < port < 65536


def test_start_server_and_status_endpoint():
    server, thread, url = desktop.start_server("127.0.0.1", 0)
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(f"{url}/api/status", timeout=10) as resp:
            data = json.load(resp)
        assert "instagram_user" in data
        with urllib.request.urlopen(f"{url}/manifest.json", timeout=10) as resp:
            manifest = json.load(resp)
        assert manifest["short_name"] == "VdAi"
        with urllib.request.urlopen(f"{url}/static/icon-192.png", timeout=10) as resp:
            assert resp.status == 200
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not thread.is_alive()
