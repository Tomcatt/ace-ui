import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

ACESTEP_API = "http://localhost:8001"
ACESTEP_OUTPUTS = Path.home() / "Projects/ACE-Step-1.5/gradio_outputs"
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


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    safe_name = Path(filename).name
    audio_path = ACESTEP_OUTPUTS / safe_name
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(str(audio_path), media_type="audio/mpeg")


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
            acestep_job_id = job_data.get("data", {}).get("job_id") or job_data.get("job_id")
            if not acestep_job_id:
                yield sse({"stage": "error", "message": "No job_id returned by ACE-Step"})
                return

            yield sse({"stage": "generating", "message": "Generating...", "progress": 0})

            # Poll for completion
            for _ in range(300):
                await asyncio.sleep(1)
                try:
                    poll = await client.get(f"{ACESTEP_API}/query_task/{acestep_job_id}")
                    result = poll.json()
                except Exception:
                    continue

                data = result.get("data", {})
                # Handle both list and dict responses
                if isinstance(data, list):
                    data = data[0] if data else {}

                api_status = data.get("status", "")
                stage = data.get("stage", "")
                progress = data.get("progress", 0)

                # Map numeric status to string if needed
                if isinstance(api_status, int):
                    api_status = {1: "running", 2: "succeeded", 3: "failed"}.get(api_status, "running")

                # Emit download detection
                if "download" in str(stage).lower():
                    yield sse({"stage": "downloading", "message": "Downloading model files...", "progress": progress})
                    continue

                if api_status == "succeeded" or stage == "succeeded":
                    # Find audio path
                    audio_path = (
                        data.get("audio_path")
                        or data.get("file")
                        or (data.get("results") or [{}])[0].get("audio_path", "")
                        or (data.get("results") or [{}])[0].get("file", "")
                    )
                    filename = Path(audio_path).name if audio_path else ""
                    if not filename:
                        yield sse({"stage": "error", "message": "Generation succeeded but no audio file returned"})
                        return

                    # Persist to history
                    entry = {
                        "id": track_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "mode": mode,
                        "prompt": payload.get("prompt", ""),
                        "params": payload,
                        "audio_file": filename,
                        "duration": data.get("duration") or (data.get("metas") or {}).get("duration") or 0,
                    }
                    history = load_history()
                    history.insert(0, entry)
                    save_history(history)

                    del _jobs[job_id]
                    yield sse({"stage": "succeeded", "message": "Done!", "progress": 1, "track": entry, "audio_url": f"/audio/{filename}"})
                    return

                if api_status in ("failed", "error") or stage == "failed":
                    yield sse({"stage": "error", "message": f"Generation failed: {data.get('error', stage)}"})
                    return

                # Emit progress for running jobs
                if progress:
                    pct = int(float(progress) * 100)
                    yield sse({"stage": "generating", "message": f"Generating... {pct}%", "progress": float(progress)})

        yield sse({"stage": "error", "message": "Generation timed out after 5 minutes"})

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def main():
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=3000, reload=True)


if __name__ == "__main__":
    main()
