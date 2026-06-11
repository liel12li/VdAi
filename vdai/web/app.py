"""Local web UI: submit a business (Instagram username or uploaded media),
get back rendered reels + post copy. Jobs run in background threads and are
polled by the page.
"""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from ..config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="VdAi", version="0.1.0")

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    from ..instagram.auth import configured_username

    return {"instagram_user": configured_username(settings.cache_dir)}


@app.post("/api/jobs")
async def create_job(
    background: BackgroundTasks,
    username: str = Form(""),
    name: str = Form(""),
    bio: str = Form(""),
    count: int = Form(3),
    lang: str = Form("auto"),
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

    background.add_task(
        _run_job, job_id, username, name, bio, count, lang, use_ai,
        str(media_dir) if media_dir else None, voice_path, music_path,
    )
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


def _run_job(job_id, username, name, bio, count, lang, use_ai, media_dir, voice_path, music_path):
    from ..ai.creative import generate_concepts
    from ..instagram.fetcher import fetch_profile, load_local_profile
    from ..video.builder import build_reel

    try:
        out_dir = settings.cache_dir / "jobs" / job_id / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        if media_dir:
            profile = load_local_profile(media_dir, username=username or name or "my_business",
                                         full_name=name, biography=bio)
        else:
            _set(job_id, status="running", step=f"מוריד נתונים מ-@{username}...")
            profile = fetch_profile(username, cache_dir=settings.cache_dir)

        _set(job_id, status="running", step="Claude בונה קונספטים...")
        concepts = generate_concepts(profile, count=count, language=lang, use_ai=use_ai)

        captions = None
        if voice_path:
            _set(job_id, step="מתמלל את הקריינות (Whisper)...")
            from ..transcribe.engine import transcribe

            whisper_lang = None if lang in ("auto", "", None) else lang
            captions = transcribe(voice_path, model_size=settings.whisper_model,
                                  language=whisper_lang)

        outputs = []
        for i, concept in enumerate(concepts, start=1):
            _set(job_id, step=f"מרנדר סרטון {i}/{len(concepts)}: {concept.title}")
            path = out_dir / f"{profile.username}_{concept.slug}.mp4"
            build_reel(profile, concept, path, voiceover=voice_path,
                       captions=captions, music=music_path)
            outputs.append({
                "file": path.name,
                "url": f"/api/jobs/{job_id}/files/{path.name}",
                "title": concept.title,
                "caption": concept.caption,
                "hashtags": concept.hashtags,
            })
            _set(job_id, outputs=outputs)

        _set(job_id, status="done", step="הסתיים ✓")
    except Exception as exc:  # noqa: BLE001 - job boundary
        logger.exception("Job %s failed", job_id)
        _set(job_id, status="error", error=str(exc), step="שגיאה")
    finally:
        media_tmp = settings.cache_dir / "jobs" / job_id / "media"
        if media_tmp.exists():
            shutil.rmtree(media_tmp, ignore_errors=True)
