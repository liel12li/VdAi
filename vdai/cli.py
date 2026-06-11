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
    gen.add_argument("--voiceover", help="קובץ אודיו של קריינות — יתומלל ויוטמע ככתוביות")
    gen.add_argument("--music", help="קובץ מוזיקת רקע (אחרת נבחר מ-assets/music אם קיים)")
    gen.add_argument("--out", default=str(settings.output_dir), help="תיקיית פלט")
    gen.add_argument("--no-ai", action="store_true", help="דילוג על Claude — שימוש בתבניות מובנות")
    gen.add_argument("--whisper-model", default=settings.whisper_model,
                     help="גודל מודל התמלול (tiny/base/small/medium/large-v3)")
    gen.add_argument("--width", type=int, default=settings.width)
    gen.add_argument("--height", type=int, default=settings.height)
    gen.set_defaults(func=_cmd_generate)

    # ---- transcribe ----
    tr = sub.add_parser("transcribe", help="תמלול אודיו/וידאו, יצוא SRT וצריבת כתוביות")
    tr.add_argument("input", help="קובץ אודיו או וידאו לתמלול")
    tr.add_argument("--lang", default=None, help="קוד שפה (he/en...). ברירת מחדל: זיהוי אוטומטי")
    tr.add_argument("--srt", help="נתיב לשמירת קובץ SRT")
    tr.add_argument("--burn", help="וידאו קיים שעליו ייצרבו הכתוביות")
    tr.add_argument("--out", help="נתיב פלט לוידאו עם כתוביות (עם --burn)")
    tr.add_argument("--whisper-model", default=settings.whisper_model)
    tr.set_defaults(func=_cmd_transcribe)

    # ---- web ----
    web = sub.add_parser("web", help="הרצת ממשק ווב מקומי")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    web.set_defaults(func=_cmd_web)

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
    from .ai.creative import generate_concepts
    from .models import concepts_to_json
    from .video.builder import build_reel

    profile = _load_profile(args)
    print(f"🧠 בונה {args.count} קונספטים ל-{profile.display_name} ...")
    concepts = generate_concepts(
        profile, count=args.count, language=args.lang, use_ai=not args.no_ai
    )

    captions = None
    if args.voiceover:
        from .transcribe.engine import transcribe

        print("🎙️  מתמלל את הקריינות ...")
        lang = None if args.lang in ("auto", None) else args.lang
        captions = transcribe(args.voiceover, model_size=args.whisper_model, language=lang)
        print(f"   {len(captions)} מקטעי כתוביות")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{profile.username}_concepts.json").write_text(
        concepts_to_json(concepts), encoding="utf-8"
    )

    outputs = []
    for i, concept in enumerate(concepts, start=1):
        path = out_dir / f"{profile.username}_{concept.slug}.mp4"
        print(f"🎬 ({i}/{len(concepts)}) מרנדר: {concept.title} → {path.name}")
        build_reel(
            profile,
            concept,
            path,
            voiceover=args.voiceover,
            captions=captions,
            music=args.music,
            size=(args.width, args.height),
        )
        outputs.append((path, concept))

    print("\n✅ מוכן! קבצים שנוצרו:")
    for path, concept in outputs:
        print(f"   {path}")
        print(f"     קופי לפוסט: {concept.caption}")
        print(f"     האשטגים: {' '.join(concept.hashtags)}")
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
        burn_captions(args.burn, captions, out)
        print(f"✅ נשמר: {out}")
    elif args.out:
        print("שימו לב: --out רלוונטי רק יחד עם --burn")
    return 0


def _cmd_web(args) -> int:
    import uvicorn

    from .web.app import app

    print(f"🌐 ממשק זמין בכתובת http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
