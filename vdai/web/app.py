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
from fastapi.responses import FileResponse, HTMLResponse

from ..config import FORMAT_PRESETS, settings

logger = logging.getLogger(__name__)

app = FastAPI(title="VdAi", version="0.2.0")

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


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
        _JOBS[job_id] = {"status": "queued", "step": "ממתין בתור...", "outputs": [], "error": None}

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

        results = run_generation(profile, options, on_step=on_step)

        base = f"/api/jobs/{job_id}/files"
        outputs = [
            {
                "file": r.video.name,
                "url": f"{base}/{r.video.name}",
                "cover_url": f"{base}/{r.cover.name}" if r.cover else None,
                "zip_url": f"{base}/{r.package.name}" if r.package else None,
                "title": r.concept.title,
                "caption": r.concept.caption,
                "hashtags": r.concept.hashtags,
                "narration": r.concept.narration,
            }
            for r in results
        ]
        _set(job_id, status="done", step="הסתיים ✓", outputs=outputs)
    except Exception as exc:  # noqa: BLE001 - job boundary
        logger.exception("Job %s failed", job_id)
        _set(job_id, status="error", error=str(exc), step="שגיאה")
    finally:
        media_tmp = settings.cache_dir / "jobs" / job_id / "media"
        if media_tmp.exists():
            shutil.rmtree(media_tmp, ignore_errors=True)
