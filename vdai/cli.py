"""VdAi command line interface.

Examples:
    python -m vdai generate some_business --count 3
    python -m vdai generate --media-dir ./photos --name "מספרת דנה" --bio "מספרה בוטיק בתל אביב"
    python -m vdai generate some_business --voiceover voice.mp3
    python -m vdai transcribe voice.mp3 --srt voice.srt
    python -m vdai transcribe voice.mp3 --burn existing.mp4 --out with_captions.mp4
    python -m vdai web
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import settings


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        logging.getLogger("vdai").error("%s", exc)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vdai",
        description="VdAi — מחולל סרטוני Reels פרסומיים מעמוד אינסטגרם של עסק",
    )
    sub = parser.add_subparsers(dest="command")

    # ---- analyze ----
    analyze = sub.add_parser("analyze", help="ניתוח פרופיל בלבד (ללא רינדור)")
    _add_source_args(analyze)
    analyze.set_defaults(func=_cmd_analyze)

    # ---- generate ----
    gen = sub.add_parser("generate", help="יצירת סרטוני Reels מוכנים לפרסום")
    _add_source_args(gen)
    gen.add_argument("--count", type=int, default=3, help="כמה סרטונים לייצר (ברירת מחדל: 3)")
    gen.add_argument("--lang", default="auto", help="שפת הטקסטים: he / en / auto")
    gen.add_argument("--tone", default="auto",
                     choices=["auto", "warm", "luxury", "energetic", "young", "professional"],
                     help="טון המותג בכתיבה")
    gen.add_argument("--format", default="reel", dest="formats",
                     help="פורמטים מופרדים בפסיק: reel,square,portrait,wide")
    gen.add_argument("--voiceover", help="קובץ קריינות מוקלטת — יתומלל ויוטמע ככתוביות")
    gen.add_argument("--tts", action="store_true",
                     help="קריינות אוטומטית: Claude כותב תסריט והתוכנה מקריאה אותו")
    gen.add_argument("--tts-voice", default="", help="קול ספציפי (למשל he-IL-AvriNeural)")
    gen.add_argument("--tts-gender", default="female", choices=["female", "male"],
                     help="מין הקול בקריינות האוטומטית")
    gen.add_argument("--music", help="קובץ מוזיקת רקע (אחרת נבחר מ-assets/music אם קיים)")
    gen.add_argument("--brand", help="קובץ ערכת מותג JSON (ראו brand.example.json)")
    gen.add_argument("--caption-style", default="pill", choices=["pill", "bold", "minimal"],
                     help="סגנון הכתוביות")
    gen.add_argument("--no-progress-bar", action="store_true", help="בלי פס התקדמות עליון")
    gen.add_argument("--draft", action="store_true",
                     help="מצב טיוטה: חצי רזולוציה ורינדור מהיר לבדיקת כיוון")
    gen.add_argument("--package", action="store_true",
                     help="אריזת כל סרטון ל-zip מוכן לפרסום (וידאו+קאבר+קופי+SRT)")
    gen.add_argument("--jobs", type=int, default=1, help="רינדור מקבילי של N סרטונים")
    gen.add_argument("--out", default=str(settings.output_dir), help="תיקיית פלט")
    gen.add_argument("--no-ai", action="store_true", help="דילוג על Claude — שימוש בתבניות מובנות")
    gen.add_argument("--no-vision", action="store_true",
                     help="בלי לשלוח את התמונות ל-Claude (חוסך טוקנים)")
    gen.add_argument("--concepts-only", action="store_true",
                     help="שלב 1: יצירת קונספטים בלבד לעריכה, בלי רינדור")
    gen.add_argument("--from-concepts", help="שלב 2: רינדור מקובץ קונספטים ערוך")
    gen.add_argument("--whisper-model", default=settings.whisper_model,
                     help="גודל מודל התמלול (tiny/base/small/medium/large-v3)")
    gen.set_defaults(func=_cmd_generate)

    # ---- transcribe ----
    tr = sub.add_parser("transcribe", help="תמלול אודיו/וידאו, יצוא SRT וצריבת כתוביות")
    tr.add_argument("input", help="קובץ אודיו או וידאו לתמלול")
    tr.add_argument("--lang", default=None, help="קוד שפה (he/en...). ברירת מחדל: זיהוי אוטומטי")
    tr.add_argument("--srt", help="נתיב לשמירת קובץ SRT")
    tr.add_argument("--burn", help="וידאו קיים שעליו ייצרבו הכתוביות")
    tr.add_argument("--out", help="נתיב פלט לוידאו עם כתוביות (עם --burn)")
    tr.add_argument("--caption-style", default="pill", choices=["pill", "bold", "minimal"])
    tr.add_argument("--whisper-model", default=settings.whisper_model)
    tr.set_defaults(func=_cmd_transcribe)

    # ---- login / logout ----
    login = sub.add_parser(
        "login",
        help="חיבור חשבון אינסטגרם — נותן לתוכנה 'עיניים' יציבות באינסטגרם",
    )
    login.add_argument("ig_username", nargs="?", help="שם המשתמש שלכם באינסטגרם")
    login.add_argument("--check", action="store_true",
                       help="בדיקה מול אינסטגרם שהחיבור השמור עדיין תקף")
    login.set_defaults(func=_cmd_login)

    logout = sub.add_parser("logout", help="מחיקת חיבור אינסטגרם שמור מהמחשב")
    logout.add_argument("ig_username", nargs="?", help="חשבון ספציפי (ברירת מחדל: כולם)")
    logout.set_defaults(func=_cmd_logout)

    # ---- web ----
    web = sub.add_parser("web", help="הרצת ממשק ווב מקומי")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    web.set_defaults(func=_cmd_web)

    # ---- desktop ----
    desktop = sub.add_parser("desktop", help="פתיחת VdAi כחלון אפליקציה על המחשב")
    desktop.add_argument("--port", type=int, default=8000)
    desktop.add_argument("--no-window", action="store_true", help="שרת בלבד, בלי לפתוח חלון")
    desktop.set_defaults(func=_cmd_desktop)

    install = sub.add_parser(
        "install-desktop", help="יצירת קיצור דרך של VdAi על שולחן העבודה"
    )
    install.set_defaults(func=_cmd_install_desktop)

    return parser


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("username", nargs="?", help="שם משתמש אינסטגרם ציבורי (למשל cafe_dizengoff)")
    parser.add_argument("--media-dir", help="לחלופין: תיקייה מקומית עם תמונות/סרטונים של העסק")
    parser.add_argument("--name", default="", help="שם העסק (במצב --media-dir)")
    parser.add_argument("--bio", default="", help="תיאור קצר של העסק (במצב --media-dir)")
    parser.add_argument("--max-posts", type=int, default=12, help="כמה פוסטים להוריד מאינסטגרם")


def _load_profile(args):
    from .instagram.fetcher import fetch_profile, load_local_profile

    if args.media_dir:
        return load_local_profile(
            args.media_dir,
            username=args.username or args.name or "my_business",
            full_name=args.name,
            biography=args.bio,
        )
    if not args.username:
        raise SystemExit("צריך לציין שם משתמש אינסטגרם או --media-dir עם תיקייה מקומית")
    print(f"⬇️  מוריד נתונים מהפרופיל @{args.username} ...")
    return fetch_profile(args.username, cache_dir=settings.cache_dir, max_posts=args.max_posts)


def _cmd_analyze(args) -> int:
    profile = _load_profile(args)
    print(f"\n📊 {profile.display_name} (@{profile.username})")
    if profile.biography:
        print(f"   ביו: {profile.biography}")
    if profile.followers:
        print(f"   עוקבים: {profile.followers:,}")
    print(f"   מדיה זמינה: {len(profile.posts)} פריטים "
          f"({sum(p.is_video for p in profile.posts)} סרטונים)")
    settings.ensure_dirs()
    out = settings.output_dir / f"{profile.username}_profile.json"
    profile.save_json(out)
    print(f"   נשמר: {out}")
    return 0


def _cmd_generate(args) -> int:
    from .models import BrandKit, concepts_to_json
    from .pipeline import GenerationOptions, run_generation

    if args.voiceover and args.tts:
        raise SystemExit("בחרו או --voiceover (הקלטה שלכם) או --tts (קריינות אוטומטית), לא שניהם")

    profile = _load_profile(args)

    options = GenerationOptions(
        count=args.count,
        language=args.lang,
        use_ai=not args.no_ai,
        use_vision=not args.no_vision,
        tone=args.tone,
        formats=[f.strip() for f in args.formats.split(",") if f.strip()],
        draft=args.draft,
        voiceover=args.voiceover,
        tts=args.tts,
        tts_voice=args.tts_voice,
        tts_gender=args.tts_gender,
        music=args.music,
        out_dir=Path(args.out),
        package=args.package,
        jobs=args.jobs,
        caption_style=args.caption_style,
        progress_bar=not args.no_progress_bar,
        whisper_model=args.whisper_model,
        brand=BrandKit.load(args.brand) if args.brand else None,
        concepts_file=args.from_concepts,
    )

    if args.concepts_only:
        from .ai.creative import apply_brand, generate_concepts

        print(f"🧠 בונה {args.count} קונספטים ל-{profile.display_name} ...")
        concepts = apply_brand(
            generate_concepts(profile, count=args.count, language=args.lang,
                              use_ai=not args.no_ai, use_vision=not args.no_vision,
                              tone=args.tone),
            options.brand,
        )
        options.out_dir.mkdir(parents=True, exist_ok=True)
        path = options.out_dir / f"{profile.username}_concepts.json"
        path.write_text(concepts_to_json(concepts), encoding="utf-8")
        print(f"📝 הקונספטים נשמרו לעריכה: {path}")
        print(f"   אחרי העריכה: python -m vdai generate ... --from-concepts {path}")
        return 0

    outputs = run_generation(profile, options, on_step=lambda msg: print(f"▸ {msg}"))

    print("\n✅ מוכן! קבצים שנוצרו:")
    for output in outputs:
        print(f"   🎬 {output.video}")
        if output.cover:
            print(f"      קאבר: {output.cover.name}")
        if output.package:
            print(f"      חבילת פרסום: {output.package.name}")
        print(f"      קופי: {output.concept.caption}")
        print(f"      האשטגים: {' '.join(output.concept.hashtags)}")
    return 0


def _cmd_transcribe(args) -> int:
    from .transcribe.engine import segments_to_srt, transcribe

    captions = transcribe(args.input, model_size=args.whisper_model, language=args.lang)
    text = " ".join(seg.text for seg in captions)
    print(f"\n📝 תמלול:\n{text}\n")

    if args.srt:
        Path(args.srt).write_text(segments_to_srt(captions), encoding="utf-8")
        print(f"💾 SRT נשמר: {args.srt}")

    if args.burn:
        from .video.captions import burn_captions

        out = args.out or str(Path(args.burn).with_stem(Path(args.burn).stem + "_captioned"))
        print(f"🎬 צורב כתוביות אל {out} ...")
        burn_captions(args.burn, captions, out, style=args.caption_style)
        print(f"✅ נשמר: {out}")
    elif args.out:
        print("שימו לב: --out רלוונטי רק יחד עם --burn")
    return 0


def _cmd_login(args) -> int:
    from .instagram.auth import check_session, configured_username, interactive_login

    if args.check:
        username, valid = check_session(settings.cache_dir)
        if not username:
            print("אין חשבון אינסטגרם מחובר. התחברו עם: python -m vdai login <שם_משתמש>")
            return 1
        if valid:
            print(f"✅ החיבור של @{username} תקף — לתוכנה יש עיניים באינסטגרם.")
            return 0
        print(f"⚠️  הסשן של @{username} כבר לא תקף. התחברו שוב: python -m vdai login {username}")
        return 1

    username = args.ig_username or configured_username(settings.cache_dir)
    if not username:
        raise SystemExit("ציינו שם משתמש: python -m vdai login <שם_משתמש>")

    import getpass

    print(f"🔐 מתחבר לאינסטגרם כ-@{username}")
    print("   (הסיסמה לא נשמרת — נשמרות רק עוגיות הסשן, מקומית בלבד)")
    password = getpass.getpass("   סיסמה: ")
    interactive_login(
        username,
        password,
        settings.cache_dir,
        two_factor_provider=lambda: input("   קוד אימות דו-שלבי (מהאפליקציה/SMS): "),
    )
    print(f"✅ מחובר! מעכשיו כל הורדה מאינסטגרם תשתמש בחשבון @{username}.")
    print("   ניתוק: python -m vdai logout")
    return 0


def _cmd_logout(args) -> int:
    from .instagram.auth import logout

    removed = logout(settings.cache_dir, args.ig_username)
    if removed:
        for path in removed:
            print(f"🗑️  נמחק: {path}")
        print("התוכנה תמשיך לעבוד במצב אנונימי (פרופילים ציבוריים בלבד).")
    else:
        print("לא נמצא חיבור שמור.")
    return 0


def _cmd_web(args) -> int:
    import uvicorn

    from .web.app import app

    print(f"🌐 ממשק זמין בכתובת http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_desktop(args) -> int:
    from .desktop import launch

    launch(port=args.port, open_window=not args.no_window)
    return 0


def _cmd_install_desktop(args) -> int:
    from .desktop import create_desktop_shortcut

    path = create_desktop_shortcut()
    print(f"✅ נוצר קיצור דרך על שולחן העבודה: {path}")
    print("   לחיצה כפולה עליו תפתח את VdAi כמו כל אפליקציה.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
