"""Run VdAi as a desktop app and install a desktop shortcut.

``vdai desktop``          — start the local server and open the UI in an
                            app-style window (native window when pywebview
                            is installed, otherwise a chromeless browser
                            window, otherwise the default browser).
``vdai install-desktop``  — put a VdAi icon on the user's Desktop that
                            launches the app, like any other application.
The web UI exposes the same installer via the "התקנה על שולחן העבודה"
button (POST /api/install-desktop).
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .config import ASSETS_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

APP_NAME = "VdAi"
ICON_PNG = ASSETS_DIR / "icon.png"
ICON_ICO = ASSETS_DIR / "icon.ico"


# --------------------------------------------------------------------------
# Launch (server + app window)
# --------------------------------------------------------------------------

def launch(host: str = "127.0.0.1", port: int = 8000, open_window: bool = True) -> None:
    """Start the server and present the UI like a desktop application."""
    server, thread, url = start_server(host, port)
    print(f"🎬 {APP_NAME} פועל בכתובת {url} (סגירה: Ctrl+C)")

    if open_window and _try_pywebview(url):
        server.should_exit = True  # window closed → shut the server down
        thread.join(timeout=5)
        return

    if open_window:
        _open_app_window(url)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=5)


def start_server(host: str, port: int):
    """Start uvicorn in a background thread; returns (server, thread, url)."""
    import uvicorn

    from .web.app import app

    port = _free_port(host, port)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("השרת המקומי לא הצליח לעלות")
        time.sleep(0.05)
    return server, thread, f"http://{host}:{port}"


def _free_port(host: str, preferred: int) -> int:
    if preferred:
        with socket.socket() as sock:
            if sock.connect_ex((host, preferred)) != 0:
                return preferred  # preferred port is free
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]  # OS-assigned free port


def _try_pywebview(url: str) -> bool:
    """Native window via pywebview, when the optional dependency exists."""
    try:
        import webview  # type: ignore[import-not-found]
    except ImportError:
        return False
    window_icon = str(ICON_PNG) if ICON_PNG.exists() else None
    webview.create_window(APP_NAME, url, width=1020, height=860)
    try:
        webview.start(icon=window_icon)
    except TypeError:  # older pywebview without icon kwarg
        webview.start()
    return True


_CHROMIUM_CANDIDATES = [
    "google-chrome", "chrome", "chromium", "chromium-browser",
    "msedge", "microsoft-edge", "brave-browser",
]


def _open_app_window(url: str) -> None:
    """Open the UI in a chromeless --app window when a browser supports it."""
    for name in _chromium_paths():
        try:
            subprocess.Popen(
                [name, f"--app={url}", "--window-size=1020,860"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            continue
    webbrowser.open(url)


def _chromium_paths() -> list[str]:
    paths = [p for n in _CHROMIUM_CANDIDATES if (p := shutil.which(n))]
    if sys.platform == "win32":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if not base:
                continue
            for rel in (r"Google\Chrome\Application\chrome.exe",
                        r"Microsoft\Edge\Application\msedge.exe"):
                candidate = Path(base) / rel
                if candidate.exists():
                    paths.append(str(candidate))
    if sys.platform == "darwin":
        for app in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
            if Path(app).exists():
                paths.append(app)
    return paths


# --------------------------------------------------------------------------
# Desktop shortcut installation
# --------------------------------------------------------------------------

def create_desktop_shortcut(desktop_dir: str | Path | None = None) -> Path:
    """Create a Desktop shortcut that launches VdAi; returns its path."""
    python = _launcher_python()
    workdir = str(PROJECT_ROOT)

    if sys.platform == "win32":
        return _install_windows(python, workdir, desktop_dir)
    if sys.platform == "darwin":
        return _install_macos(python, workdir, desktop_dir)
    return _install_linux(python, workdir, desktop_dir)


def _launcher_python() -> str:
    """The interpreter the shortcut should run (windowless on Windows)."""
    python = Path(sys.executable)
    if sys.platform == "win32" and python.name.lower() == "python.exe":
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(python)


def _desktop_dir(override: str | Path | None) -> Path:
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    home = Path.home()
    if sys.platform.startswith("linux"):
        xdg = _xdg_desktop(home)
        if xdg:
            return xdg
    desktop = home / "Desktop"
    chosen = desktop if desktop.is_dir() else home
    chosen.mkdir(parents=True, exist_ok=True)
    return chosen


def _xdg_desktop(home: Path) -> Path | None:
    config = home / ".config" / "user-dirs.dirs"
    if not config.exists():
        return None
    for line in config.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("XDG_DESKTOP_DIR"):
            raw = line.split("=", 1)[1].strip().strip('"')
            path = Path(raw.replace("$HOME", str(home)))
            if path.is_dir():
                return path
    return None


# ---- per-OS content builders (pure, unit-testable) ----

def windows_shortcut_script(python: str, workdir: str, lnk_path: str, icon: str) -> str:
    return f"""\
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{lnk_path}')
$s.TargetPath = '{python}'
$s.Arguments = '-m vdai desktop'
$s.WorkingDirectory = '{workdir}'
$s.IconLocation = '{icon}'
$s.Description = 'VdAi - Reels generator'
$s.Save()
"""


def macos_command_content(python: str, workdir: str) -> str:
    return (
        "#!/bin/bash\n"
        f'cd "{workdir}"\n'
        f'exec "{python}" -m vdai desktop\n'
    )


def linux_desktop_entry(python: str, workdir: str, icon: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=מחולל סרטוני Reels פרסומיים\n"
        f'Exec="{python}" -m vdai desktop\n'
        f"Path={workdir}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Video;\n"
    )


# ---- per-OS installers ----

def _install_windows(python: str, workdir: str, desktop_dir) -> Path:
    desktop = _desktop_dir(desktop_dir)
    lnk = desktop / f"{APP_NAME}.lnk"
    script = windows_shortcut_script(python, workdir, str(lnk), str(ICON_ICO))
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not lnk.exists():
        raise RuntimeError(f"יצירת קיצור הדרך נכשלה: {result.stderr.strip()[:300]}")
    return lnk


def _install_macos(python: str, workdir: str, desktop_dir) -> Path:
    desktop = _desktop_dir(desktop_dir)
    command = desktop / f"{APP_NAME}.command"
    command.write_text(macos_command_content(python, workdir), encoding="utf-8")
    command.chmod(0o755)
    return command


def _install_linux(python: str, workdir: str, desktop_dir) -> Path:
    desktop = _desktop_dir(desktop_dir)
    entry = linux_desktop_entry(python, workdir, str(ICON_PNG))
    shortcut = desktop / f"{APP_NAME.lower()}.desktop"
    shortcut.write_text(entry, encoding="utf-8")
    shortcut.chmod(0o755)
    # Also register in the applications menu
    apps_dir = Path.home() / ".local" / "share" / "applications"
    try:
        apps_dir.mkdir(parents=True, exist_ok=True)
        (apps_dir / shortcut.name).write_text(entry, encoding="utf-8")
    except OSError as exc:  # menu registration is a bonus
        logger.warning("Could not register app menu entry: %s", exc)
    return shortcut
