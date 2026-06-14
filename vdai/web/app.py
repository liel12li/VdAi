"""Local web UI: submit a business (Instagram username or uploaded media),
get back rendered reels + covers + publish packages. Jobs run in background
threads and are polled by the page.
"""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import ASSETS_DIR, FORMAT_PRESETS, settings

logger = logging.getLogger(__name__)

app = FastAPI(title="VdAi", version="0.2.0")

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_FONT_FILE = ASSETS_DIR / "fonts" / "Heebo[wght].ttf"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/font/heebo.ttf")
def heebo_font():
    """Serve the bundled Hebrew font so the UI looks the same offline.

    Served outside ``/static`` because the StaticFiles mount there would
    otherwise shadow this route and 404 (the real file name has brackets).
    """
    if _FONT_FILE.exists():
        return FileResponse(_FONT_FILE, media_type="font/ttf")
    raise HTTPException(404, "font not bundled")


@app.get("/manifest.json")
def manifest() -> JSONResponse:
    return JSONResponse({
        "name": "VdAi — מחולל סרטוני Reels",
        "short_name": "VdAi",
        "start_url": "/",
        "display": "standalone",
        "dir": "rtl",
        "lang": "he",
        "background_color": "#f6f2ea",
        "theme_color": "#c96f4a",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })


@app.post("/api/instagram/login")
def instagram_login(username: str = Form(...), password: str = Form(...)):
    """Step 1 of connecting an Instagram account (password)."""
    from ..instagram.auth import InstagramAuthError, begin_web_login

    try:
        return begin_web_login(username, password, settings.cache_dir)
    except InstagramAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - always return JSON, never a 500 page
        logger.exception("Instagram login endpoint error")
        raise HTTPException(400, f"ההתחברות נכשלה: {exc}") from exc


@app.post("/api/instagram/import-browser")
def instagram_import_browser(browser: str = Form("auto")):
    """Connect by importing cookies from a browser you're logged into."""
    from ..instagram.auth import InstagramAuthError, import_browser_session

    try:
        return import_browser_session(settings.cache_dir, browser)
    except InstagramAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - always JSON
        logger.exception("Browser import error")
        raise HTTPException(400, f"הייבוא נכשל: {exc}") from exc


@app.post("/api/instagram/login/sessionid")
def instagram_login_sessionid(sessionid: str = Form(...)):
    """Connect by pasting a sessionid cookie (bulletproof manual fallback)."""
    from ..instagram.auth import InstagramAuthError, login_with_sessionid

    try:
        return login_with_sessionid(sessionid, settings.cache_dir)
    except InstagramAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - always JSON
        logger.exception("sessionid login error")
        raise HTTPException(400, f"ההתחברות נכשלה: {exc}") from exc


@app.post("/api/instagram/login/2fa")
def instagram_login_2fa(login_id: str = Form(...), code: str = Form(...)):
    """Step 2: submit the two-factor authentication code."""
    from ..instagram.auth import InstagramAuthError, complete_web_login_2fa

    try:
        return complete_web_login_2fa(login_id, code, settings.cache_dir)
    except InstagramAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - always return JSON, never a 500 page
        logger.exception("Instagram 2FA endpoint error")
        raise HTTPException(400, f"האימות נכשל: {exc}") from exc


@app.post("/api/instagram/logout")
def instagram_logout():
    from ..instagram.auth import logout

    removed = logout(settings.cache_dir)
    return {"removed": len(removed)}


@app.post("/api/install-desktop")
def install_desktop():
    """Create a VdAi shortcut on this machine's Desktop (local app usage)."""
    from ..desktop import create_desktop_shortcut

    try:
        path = create_desktop_shortcut()
    except Exception as exc:  # noqa: BLE001 - surface a friendly error
        logger.exception("Desktop shortcut installation failed")
        raise HTTPException(500, f"ההתקנה נכשלה: {exc}") from exc
    return {"path": str(path)}


@app.get("/api/status")
def status():
    from ..instagram.auth import configured_username

    return {
        "instagram_user": configured_username(settings.cache_dir),
        "formats": list(FORMAT_PRESETS),
    }


@app.post("/api/jobs")
async def create_job(
    background: BackgroundTasks,
    username: str = Form(""),
    name: str = Form(""),
    bio: str = Form(""),
    count: int = Form(3),
    lang: str = Form("auto"),
    tone: str = Form("auto"),
    fmt: str = Form("reel"),
    tts: bool = Form(False),
    tts_gender: str = Form("female"),
    draft: bool = Form(False),
    caption_style: str = Form("pill"),
    use_ai: bool = Form(True),
    media: list[UploadFile] = File(default=[]),
    voiceover: UploadFile | None = File(default=None),
    music: UploadFile | None = File(default=None),
):
    username = username.strip().lstrip("@")
    media = [m for m in media if m and m.filename]
    if not username and not media:
        raise HTTPException(400, "צריך שם משתמש אינסטגרם או קבצי מדיה")

    job_id = uuid.uuid4().hex[:12]
    job_dir = settings.cache_dir / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    media_dir = None
    if media:
        media_dir = job_dir / "media"
        media_dir.mkdir(exist_ok=True)
        for i, upload in enumerate(media):
            suffix = Path(upload.filename).suffix.lower() or ".jpg"
            (media_dir / f"media_{i:02d}{suffix}").write_bytes(await upload.read())

    voice_path = await _save_upload(voiceover, job_dir, "voiceover")
    music_path = await _save_upload(music, job_dir, "music")

    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "queued", "step": "ממתין בתור...",
                         "outputs": [], "concepts": [], "error": None}

    params = {
        "username": username, "name": name, "bio": bio, "count": count,
        "lang": lang, "tone": tone, "fmt": fmt, "tts": tts and not voice_path,
        "tts_gender": tts_gender, "draft": draft, "caption_style": caption_style,
        "use_ai": use_ai, "media_dir": str(media_dir) if media_dir else None,
        "voice_path": voice_path, "music_path": music_path,
    }
    background.add_task(_run_job, job_id, params)
    return {"job_id": job_id}


async def _save_upload(upload: UploadFile | None, job_dir: Path, stem: str) -> str | None:
    if upload is None or not upload.filename:
        return None
    path = job_dir / f"{stem}{Path(upload.filename).suffix.lower()}"
    path.write_bytes(await upload.read())
    return str(path)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs/{job_id}/files/{filename}")
def job_file(job_id: str, filename: str):
    job_dir = (settings.cache_dir / "jobs" / job_id / "out").resolve()
    path = (job_dir / Path(filename).name).resolve()
    if not str(path).startswith(str(job_dir)) or not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path)


def _set(job_id: str, **fields) -> None:
    with _JOBS_LOCK:
        _JOBS[job_id].update(fields)


def _run_job(job_id: str, p: dict) -> None:
    from ..instagram.fetcher import fetch_profile, load_local_profile
    from ..pipeline import GenerationOptions, run_generation

    try:
        out_dir = settings.cache_dir / "jobs" / job_id / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        if p["media_dir"]:
            profile = load_local_profile(
                p["media_dir"], username=p["username"] or p["name"] or "my_business",
                full_name=p["name"], biography=p["bio"],
            )
        else:
            _set(job_id, status="running", step=f"מוריד נתונים מ-@{p['username']}...")
            profile = fetch_profile(p["username"], cache_dir=settings.cache_dir)

        options = GenerationOptions(
            count=p["count"],
            language=p["lang"],
            use_ai=p["use_ai"],
            tone=p["tone"],
            formats=[p["fmt"]],
            draft=p["draft"],
            voiceover=p["voice_path"],
            tts=p["tts"],
            tts_gender=p["tts_gender"],
            music=p["music_path"],
            out_dir=out_dir,
            package=True,
            caption_style=p["caption_style"],
        )

        def on_step(msg: str) -> None:
            _set(job_id, status="running", step=msg)

        base = f"/api/jobs/{job_id}/files"

        def on_concepts(concepts) -> None:
            # Show the ideas + copy immediately, before videos finish rendering.
            _set(job_id, concepts=[
                {"title": c.title, "caption": c.caption, "hashtags": c.hashtags,
                 "narration": c.narration}
                for c in concepts
            ])

        live_outputs: list[dict] = []

        def on_reel(r) -> None:
            live_outputs.append({
                "file": r.video.name,
                "url": f"{base}/{r.video.name}",
                "cover_url": f"{base}/{r.cover.name}" if r.cover else None,
                "zip_url": f"{base}/{r.package.name}" if r.package else None,
                "title": r.concept.title,
                "caption": r.concept.caption,
                "hashtags": r.concept.hashtags,
                "narration": r.concept.narration,
            })
            _set(job_id, outputs=list(live_outputs))

        run_generation(profile, options, on_step=on_step,
                       on_concepts=on_concepts, on_reel=on_reel)

        _set(job_id, status="done", step="הסתיים ✓")
    except Exception as exc:  # noqa: BLE001 - job boundary
        logger.exception("Job %s failed", job_id)
        _set(job_id, status="error", error=str(exc), step="שגיאה")
    finally:
        media_tmp = settings.cache_dir / "jobs" / job_id / "media"
        if media_tmp.exists():
            shutil.rmtree(media_tmp, ignore_errors=True)
