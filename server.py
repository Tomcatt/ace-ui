import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

ACESTEP_API = "http://localhost:8001"
ACESTEP_OUTPUTS = Path.home() / "Projects/ACE-Step-1.5/gradio_outputs"
HERE = Path(__file__).parent
HISTORY_FILE = HERE / "history.json"

app = FastAPI()


def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    return json.loads(HISTORY_FILE.read_text())


def save_history(history: list) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


@app.get("/", response_class=HTMLResponse)
async def index():
    return (HERE / "index.html").read_text()


@app.get("/health")
async def health():
    return {"status": "ok"}


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
    track_id = str(uuid.uuid4())
    mode = body.get("_mode", "simple")

    # Strip internal keys before forwarding to ACE-Step
    payload = {k: v for k, v in body.items() if not k.startswith("_")}

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(f"{ACESTEP_API}/release_task", json=payload)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"ACE-Step API error: {resp.text}")
        job_data = resp.json()
        job_id = job_data.get("data", {}).get("job_id") or job_data.get("job_id")
        if not job_id:
            raise HTTPException(status_code=502, detail="No job_id in ACE-Step response")

        for _ in range(300):
            await asyncio.sleep(1)
            poll = await client.get(f"{ACESTEP_API}/query_task/{job_id}")
            result = poll.json()
            data = result.get("data", {})
            status = data.get("status", "")

            if status == "succeeded":
                audio_path = data.get("audio_path") or (data.get("results") or [{}])[0].get("audio_path", "")
                filename = Path(audio_path).name if audio_path else ""
                if not filename:
                    raise HTTPException(status_code=502, detail="No audio path in result")

                entry = {
                    "id": track_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mode": mode,
                    "prompt": payload.get("prompt", ""),
                    "params": payload,
                    "audio_file": filename,
                    "duration": data.get("duration", 0),
                }
                history = load_history()
                history.insert(0, entry)
                save_history(history)
                return {"track": entry, "audio_url": f"/audio/{filename}"}

            if status in ("failed", "error"):
                raise HTTPException(status_code=500, detail=f"Generation failed: {data.get('error', '')}")

        raise HTTPException(status_code=504, detail="Generation timed out")


def main():
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=3000, reload=True)


if __name__ == "__main__":
    main()
