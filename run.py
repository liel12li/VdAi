#!/usr/bin/env python3
"""נקודת הכניסה הנוחה ל-VdAi.

הריצו את הקובץ הזה (לחיצה על ▶ ב-VS Code, או דאבל-קליק) — והאפליקציה
תיפתח כחלון. אפשר גם להעביר את אותן פקודות כמו ב-CLI, למשל:

    python run.py web
    python run.py generate some_business --count 3

הקובץ הזה הוא היחיד שבטוח להריץ ישירות; שאר הקבצים בתיקיית vdai/ הם
חלק מחבילה ונועדו לרוץ ביחד (``python -m vdai``).
"""

import os
import sys

# Make the bundled ``vdai`` package importable no matter where we're run from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _halt(message: str) -> None:
    print(message)
    try:
        input("\nלחצו Enter לסגירה...")
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(1)


def main() -> int:
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
