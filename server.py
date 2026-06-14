import asyncio
import json
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from starlette.background import BackgroundTask

ACESTEP_API = "http://localhost:8001"
ACESTEP_OUTPUTS = Path.home() / "Projects/ai-music/ACE-Step-1.5/.cache/acestep/tmp/api_audio"
HERE = Path(__file__).parent
HISTORY_FILE = HERE / "history.json"

app = FastAPI()

# In-memory job registry: job_id -> {payload, track_id, mode}
_jobs: dict = {}


def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    return json.loads(HISTORY_FILE.read_text())


def save_history(history: list) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.get("/", response_class=HTMLResponse)
async def index():
    return (HERE / "index.html").read_text()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    """Proxy ACE-Step health so the UI can show model load state."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ACESTEP_API}/health")
            return resp.json()
    except Exception:
        return {"status": "unreachable", "models_initialized": False, "llm_initialized": False}


@app.get("/api/history")
async def get_history():
    return load_history()


@app.delete("/api/track/{track_id}")
async def delete_track(track_id: str):
    """Soft-delete: move to trash (trashed=True). Audio file is kept."""
    history = load_history()
    entry = next((e for e in history if e.get("id") == track_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Track not found")
    entry["trashed"] = True
    save_history(history)
    return {"trashed": track_id}


@app.delete("/api/track/{track_id}/permanent")
async def permanent_delete_track(track_id: str):
    """Hard-delete: remove from history and delete audio file."""
    history = load_history()
    idx = next((i for i, e in enumerate(history) if e.get("id") == track_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Track not found")
    entry = history.pop(idx)
    save_history(history)
    audio = ACESTEP_OUTPUTS / Path(entry.get("audio_file", "")).name
    if audio.exists():
        audio.unlink()
    return {"deleted": track_id}


@app.post("/api/track/{track_id}/restore")
async def restore_track(track_id: str):
    """Restore a trashed track back to the library."""
    history = load_history()
    entry = next((e for e in history if e.get("id") == track_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Track not found")
    entry.pop("trashed", None)
    save_history(history)
    return entry


@app.delete("/api/trash")
async def empty_trash():
    """Permanently delete all trashed tracks and their audio files."""
    history = load_history()
    kept, removed = [], []
    for e in history:
        if e.get("trashed"):
            audio = ACESTEP_OUTPUTS / Path(e.get("audio_file", "")).name
            if audio.exists():
                audio.unlink()
            removed.append(e["id"])
        else:
            kept.append(e)
    save_history(kept)
    return {"deleted": removed, "count": len(removed)}


@app.patch("/api/track/{track_id}")
async def patch_track(track_id: str, body: dict):
    history = load_history()
    entry = next((e for e in history if e.get("id") == track_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Track not found")
    for key in ("prompt", "trashed"):
        if key in body:
            if body[key] is None:
                entry.pop(key, None)
            else:
                entry[key] = body[key]
    save_history(history)
    return entry


SUPPORTED_FORMATS = {
    "mp3": ("audio/mpeg", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "wav": ("audio/wav", ["-c:a", "pcm_s16le"]),
    "flac": ("audio/flac", ["-c:a", "flac"]),
}


@app.get("/audio/{filename}")
async def serve_audio(filename: str, format: str | None = None):
    safe_name = Path(filename).name
    audio_path = ACESTEP_OUTPUTS / safe_name
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    src_ext = audio_path.suffix.lower().lstrip(".")
    media_types = {"mp3": "audio/mpeg", "flac": "audio/flac", "wav": "audio/wav", "opus": "audio/ogg"}

    if format is None or format == src_ext:
        return FileResponse(str(audio_path), media_type=media_types.get(src_ext, "audio/mpeg"))

    if format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    mime, codec_args = SUPPORTED_FORMATS[format]
    tmp = tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False)
    tmp.close()
    cmd = ["ffmpeg", "-y", "-i", str(audio_path), *codec_args, tmp.name]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        Path(tmp.name).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {stderr.decode()[:200]}")
    download_name = f"{audio_path.stem}.{format}"
    return FileResponse(
        tmp.name,
        media_type=mime,
        filename=download_name,
        background=BackgroundTask(lambda: Path(tmp.name).unlink(missing_ok=True)),
    )


@app.post("/api/generate")
async def generate(body: dict):
    """Queue a generation job, return job_id immediately."""
    track_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    mode = body.get("_mode", "simple")
    payload = {k: v for k, v in body.items() if not k.startswith("_")}
    _jobs[job_id] = {"payload": payload, "track_id": track_id, "mode": mode}
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    """SSE stream: runs the job and emits status events until done."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    payload = job["payload"]
    track_id = job["track_id"]
    mode = job["mode"]

    async def event_gen():
        async with httpx.AsyncClient(timeout=300.0) as client:

            # Check if models are loaded
            try:
                h = await client.get(f"{ACESTEP_API}/health")
                hdata = h.json().get("data", h.json())
                models_ok = hdata.get("models_initialized", True)
                llm_ok = hdata.get("llm_initialized", True)
                if not models_ok:
                    yield sse({"stage": "loading", "message": "Loading models into VRAM (first run may take a minute)...", "progress": 0})
                elif not llm_ok:
                    yield sse({"stage": "loading", "message": "Loading language model...", "progress": 0})
                else:
                    yield sse({"stage": "queued", "message": "Queued...", "progress": 0})
            except Exception:
                yield sse({"stage": "queued", "message": "Connecting to ACE-Step...", "progress": 0})

            # Submit job to ACE-Step
            try:
                resp = await client.post(f"{ACESTEP_API}/release_task", json=payload)
            except Exception as e:
                yield sse({"stage": "error", "message": f"ACE-Step unreachable: {e}"})
                return

            if resp.status_code != 200:
                yield sse({"stage": "error", "message": f"ACE-Step error {resp.status_code}: {resp.text[:200]}"})
                return

            job_data = resp.json()
            d = job_data.get("data", job_data)
            acestep_job_id = d.get("task_id") or d.get("job_id")
            if not acestep_job_id:
                yield sse({"stage": "error", "message": f"No task_id in ACE-Step response: {job_data}"})
                return

            yield sse({"stage": "generating", "message": "Generating...", "progress": 0})

            # Poll for completion using /query_result
            for _ in range(300):
                await asyncio.sleep(1)
                try:
                    poll = await client.post(
                        f"{ACESTEP_API}/query_result",
                        json={"task_id_list": json.dumps([acestep_job_id])},
                    )
                    outer = poll.json()
                except Exception:
                    continue

                items = outer.get("data", [])
                if not items:
                    continue

                item = items[0]
                item_status = item.get("status")  # 1=succeeded, 2=failed
                result_str = item.get("result", "")

                # Parse inner result JSON string
                try:
                    result_list = json.loads(result_str) if result_str else []
                    inner = result_list[0] if result_list else {}
                except Exception:
                    inner = {}

                stage = inner.get("stage", "")
                progress = float(inner.get("progress", 0))

                if "download" in str(stage).lower():
                    yield sse({"stage": "downloading", "message": "Downloading model files...", "progress": progress})
                    continue

                if stage == "succeeded" or item_status == 1:
                    # Extract audio file path from the /v1/audio?path=... URL
                    file_url = inner.get("file", "")
                    if "path=" in file_url:
                        audio_path = unquote(file_url.split("path=")[-1])
                    else:
                        audio_path = file_url
                    filename = Path(audio_path).name if audio_path else ""
                    if not filename:
                        yield sse({"stage": "error", "message": "No audio file in result"})
                        return

                    metas = inner.get("metas") or {}
                    raw_dur = metas.get("duration") or payload.get("audio_duration") or 0
                    duration = raw_dur if isinstance(raw_dur, (int, float)) else 0
                    entry = {
                        "id": track_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "mode": mode,
                        "prompt": inner.get("prompt") or payload.get("prompt") or payload.get("sample_query", ""),
                        "params": payload,
                        "audio_file": filename,
                        "duration": duration,
                    }
                    history = load_history()
                    history.insert(0, entry)
                    save_history(history)

                    _jobs.pop(job_id, None)
                    yield sse({"stage": "succeeded", "message": "Done!", "progress": 1, "track": entry, "audio_url": f"/audio/{filename}"})
                    return

                if item_status == 2 or stage in ("failed", "error"):
                    yield sse({"stage": "error", "message": f"Generation failed: {inner.get('error', stage or 'unknown')}"})
                    return

                if progress:
                    pct = int(progress * 100)
                    yield sse({"stage": "generating", "message": f"Generating... {pct}%", "progress": progress})

        yield sse({"stage": "error", "message": "Generation timed out after 5 minutes"})

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def main():
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=3000, reload=True, reload_excludes=[".venv", "*.pyc"])


if __name__ == "__main__":
    main()
