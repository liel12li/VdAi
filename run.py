#!/usr/bin/env python3
"""נקודת הכניסה הנוחה ל-VdAi.

הריצו את הקובץ הזה (לחיצה על ▶ ב-VS Code, או דאבל-קליק) — והאפליקציה
תיפתח כחלון. בהרצה הראשונה, אם חסרות ספריות, הן יותקנו אוטומטית.

אפשר גם להעביר את אותן פקודות כמו ב-CLI, למשל:
    python run.py web
    python run.py generate some_business --count 3

הקובץ הזה הוא היחיד שבטוח להריץ ישירות; שאר הקבצים בתיקיית vdai/ הם
חלק מחבילה ונועדו לרוץ ביחד (``python -m vdai``).
"""

import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)  # make the bundled ``vdai`` package importable

# import name -> pip requirement. These are the packages required just to
# launch the app and render videos. Transcription (faster-whisper) and
# auto-voiceover (edge-tts) are installed too but are not required to start,
# so a failure there (e.g. on a brand-new Python with no wheels yet) still
# lets the app run.
CORE_DEPS = {
    "anthropic": "anthropic>=0.69",
    "moviepy": "moviepy>=2.1.2",
    "imageio_ffmpeg": "imageio-ffmpeg>=0.5",
    "PIL": "Pillow>=10.0",
    "numpy": "numpy>=1.26",
    "bidi": "python-bidi>=0.6",
    "instaloader": "instaloader>=4.14",
    "requests": "requests>=2.31",
    "fastapi": "fastapi>=0.110",
    "uvicorn": "uvicorn>=0.29",
    "multipart": "python-multipart>=0.0.9",
}
OPTIONAL_DEPS = {
    "faster_whisper": "faster-whisper>=1.0",
    "edge_tts": "edge-tts>=6.1",
    "browser_cookie3": "browser_cookie3>=0.19",
}


def _missing(deps: dict[str, str]) -> list[str]:
    return [req for mod, req in deps.items() if importlib.util.find_spec(mod) is None]


def _pip_install(requirements: list[str], quiet: bool = False) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", *requirements]
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL} if quiet else {}
    try:
        return subprocess.run(cmd, **kwargs).returncode == 0
    except Exception:  # noqa: BLE001 - pip not runnable
        return False


def _ensure_dependencies() -> None:
    """Install missing packages on first run so the app 'just works'."""
    if os.environ.get("VDAI_NO_AUTOINSTALL"):
        return

    if not _missing(CORE_DEPS):
        return  # everything needed to launch is present — start immediately

    print("📦 התקנה ראשונית של הספריות הנדרשות — זה יכול לקחת כמה דקות, רק בפעם הראשונה...\n")
    req_file = os.path.join(ROOT, "requirements.txt")
    missing_core = _missing(CORE_DEPS)

    # Happy path: install everything from requirements.txt (live pip output).
    ok = os.path.exists(req_file) and _pip_install(["-r", req_file])
    if not ok or _missing(CORE_DEPS):
        # Fallback: install just the core packages, so a failing optional
        # package (common on a freshly released Python with no wheels) does
        # not prevent the app from running. Optional extras are attempted
        # quietly and never block startup.
        print("\nמנסה להתקין את הספריות החיוניות בלבד...\n")
        _pip_install(missing_core)
        if _missing(OPTIONAL_DEPS):
            _pip_install(_missing(OPTIONAL_DEPS), quiet=True)

    still_missing = _missing(CORE_DEPS)
    if still_missing:
        _halt(
            "⚠️  לא הצלחתי להתקין חלק מהספריות:\n    "
            + "\n    ".join(still_missing)
            + "\n\nרוב הסיכויים שגרסת ה-Python שלך חדשה מדי (אני רואה "
            f"{sys.version_info.major}.{sys.version_info.minor}) "
            "ועדיין אין לחלק מהספריות התאמה אליה.\n"
            "הפתרון הקל: התקינו Python 3.12 מ-python.org, ובחרו אותו ב-VS Code "
            "(Ctrl+Shift+P → Python: Select Interpreter), ואז הריצו שוב את run.py.\n\n"
            "לחלופין, התקנה ידנית בטרמינל:\n"
            "    pip install -r requirements.txt"
        )
    print("\n✅ הספריות הותקנו. ממשיך...\n")


def _halt(message: str) -> None:
    print(message)
    try:
        input("\nלחצו Enter לסגירה...")
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(1)


def main() -> int:
    _ensure_dependencies()
    try:
        from vdai.cli import main as cli_main
    except ImportError as exc:
        _halt(
            "⚠️  נראה שחסרות ספריות. פתחו טרמינל בתיקייה הזו והריצו פעם אחת:\n\n"
            "    pip install -r requirements.txt\n\n"
            f"(פירוט טכני: {exc})"
        )

    # No arguments → open the desktop app window, like any other application.
    if len(sys.argv) == 1:
        sys.argv.append("desktop")
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
