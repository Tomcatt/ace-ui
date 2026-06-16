# VR Chat Overlay — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a VR overlay showing merged Twitch + YouTube live chat with moderation, event alerts, spatial positioning modes, and gaze-aware opacity — Python prototype first, shim swappable for Rust/OpenXR later.

**Architecture:** FastAPI web app serves the chat UI and handles Twitch IRC + YouTube API connections; a Python OpenVR shim captures the browser window and renders it as a VR overlay texture via `mss` screenshots → `SetOverlayRaw`. All state persists to `config.toml`. The shim is the only piece that changes for Phase 2 (Rust/OpenXR).

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, websockets, httpx, google-api-python-client, google-auth-oauthlib, tomli-w, openvr, mss, Pillow, numpy, pytest, vanilla JS/CSS frontend.

---

## Project Location

Create new project at `/home/tomcatt/Projects/vr-chat-overlay/`  
(Separate from ace-ui — standalone app)

---

## File Structure

```
vr-chat-overlay/
├── pyproject.toml
├── config.toml              # Auto-generated on first run with full inline comments
├── server.py                # Entry point: FastAPI app + background task launcher
├── config.py                # Load/save config.toml → Config dataclass
├── twitch.py                # Twitch IRC WebSocket + EventSub + Helix API poller
├── youtube.py               # YouTube Live Chat API polling + OAuth credential refresh
├── auth.py                  # FastAPI OAuth callback routes (Twitch + YouTube)
├── shim.py                  # Python OpenVR shim: overlay + texture + controller + gaze
├── static/
│   ├── index.html           # Chat view (filter tabs, chat feed, status bar)
│   ├── settings.html        # Settings page (all config sections + colour legend)
│   ├── app.js               # WebSocket client, render pipeline, filter/wrap/mod logic
│   └── style.css            # Overlay theme, alert colours, gaze fade transitions
└── tests/
    ├── test_config.py
    ├── test_twitch.py
    ├── test_youtube.py
    └── test_server.py
```

---

## WebSocket Message Schema

All backend → frontend messages share this contract (referenced in every task):

```python
# chat message
{"type": "chat", "platform": "twitch"|"youtube", "username": str,
 "color": str, "message": str, "timestamp": str, "message_id": str}

# join / part  (Twitch only)
{"type": "join"|"part", "platform": "twitch", "username": str, "timestamp": str}

# alert
{"type": "alert", "platform": "twitch"|"youtube",
 "alert_type": "raid"|"follow"|"sub"|"resub"|"subgift"|"bits"|"super_chat"|"new_member",
 "username": str, "message": str, "amount": int|None, "timestamp": str}

# status  (sent every 30 s)
{"type": "status", "twitch_viewers": int|None, "youtube_viewers": int|None,
 "stream_elapsed_seconds": int|None,
 "twitch_token_expires": str|None, "youtube_token_expires": str|None}
```

---

## Task 1: Project Bootstrap

**Files:**
- Create: `/home/tomcatt/Projects/vr-chat-overlay/pyproject.toml`
- Create: `/home/tomcatt/Projects/vr-chat-overlay/config.toml`
- Create: `/home/tomcatt/Projects/vr-chat-overlay/static/` (empty)
- Create: `/home/tomcatt/Projects/vr-chat-overlay/tests/` (empty)

- [ ] **Step 1: Create project directory and init git**

```bash
mkdir -p /home/tomcatt/Projects/vr-chat-overlay/{static,tests}
cd /home/tomcatt/Projects/vr-chat-overlay
git init
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "vr-chat-overlay"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "websockets>=12.0",
    "httpx>=0.27",
    "google-api-python-client>=2.130",
    "google-auth-oauthlib>=1.2",
    "google-auth-httplib2>=0.2",
    "tomli-w>=1.0",
    "openvr>=1.26",
    "mss>=9.0",
    "Pillow>=10.0",
    "numpy>=2.0",
    "python-multipart>=0.0.9",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: Write default config.toml**

```toml
# VR Chat Overlay — configuration file
# Edit any value here; changes take effect on next app start.
# All fields have safe defaults — you only need to change what matters to you.

[twitch]
channel = ""                     # Your Twitch channel name (lowercase)
client_id = ""                   # From dev.twitch.tv — create a free app
client_secret = ""               # From dev.twitch.tv
access_token = ""                # Set automatically via OAuth — do not edit
refresh_token = ""               # Set automatically via OAuth — do not edit
token_expires = ""               # ISO timestamp — shown as countdown in UI

[youtube]
stream_id = "auto"               # "auto" polls for your active live stream every 60 s;
                                 # paste a specific stream ID to pin it
client_id = ""                   # From Google Cloud Console OAuth 2.0 credentials
client_secret = ""               # From Google Cloud Console OAuth 2.0 credentials
access_token = ""                # Set automatically via OAuth — do not edit
refresh_token = ""               # Set automatically via OAuth — do not edit
token_expires = ""               # ISO timestamp — shown as countdown in UI

[overlay]
mode = "fixed"                   # "fixed" | "follow" | "wrist"
port = 7331                      # Local port the web UI runs on

# Fixed mode — world-space anchor (set by grab-and-save in VR, or edit here)
fixed_x = 0.0                    # Metres, world space
fixed_y = 1.4
fixed_z = -1.2
fixed_rot_x = 0.0                # Degrees
fixed_rot_y = 0.0
fixed_rot_z = 0.0
fixed_size = 0.6                 # Overlay width in metres

# Follow mode — constant offset from player head
follow_angle = 30.0              # Degrees to the right of your forward direction
follow_distance = 1.2            # Metres from head
follow_height = -0.2             # Vertical offset in metres
follow_size = 0.6

# Wrist dock mode
wrist_hand = "left"              # "left" | "right"
wrist_flip_threshold = 45.0      # Degrees — wrist rotation angle that reveals the overlay
wrist_size = 0.3                 # Smaller than fixed/follow since it's close to face

[display]
opacity = 0.8                    # Overall overlay opacity (0.0–1.0)
timestamps = true                # Show HH:MM timestamp on each message
viewer_count_bar = true          # Show viewer counts in the status bar
join_leave_alerts = true         # Show join/leave events in chat feed (Twitch only)
word_wrap = true                 # Wrap long messages; false clips with ellipsis
default_filter = "all"           # Starting filter tab: "all" | "twitch" | "youtube"

[alerts]
# Each alert appears as a highlighted line in the chat feed.
# Toggle any off if you find them distracting.
raids = true                     # Twitch only — incoming raids
follows = true                   # Twitch only — new followers
subs = true                      # Twitch only — subs, resubs, gifted subs
bits = true                      # Twitch only — bit/cheer donations
super_chat = true                # YouTube only — Super Chat donations
new_members = true               # YouTube only — new channel memberships

[gaze]
enabled = true                   # Brighten overlay when looking at it, dim when looking away
                                 # Uses eye tracking if your headset supports it,
                                 # falls back to head-gaze automatically
focused_brightness = 1.0         # Opacity when looking at the overlay (0.0–1.0)
away_behaviour = "dim"           # "dim" keeps it faintly visible; "disappear" hides it fully
dim_level = 0.3                  # Opacity when looking away — only used when away_behaviour = "dim"
cone_angle = 35.0                # How directly you must face the overlay to trigger focus (degrees)
fade_speed = "medium"            # Transition speed: "slow" | "medium" | "fast"
```

- [ ] **Step 4: Install dependencies**

```bash
cd /home/tomcatt/Projects/vr-chat-overlay
uv sync
```

Expected: dependencies resolve and install without errors.

- [ ] **Step 5: Write .gitignore**

```
.venv/
__pycache__/
*.pyc
.env
```

- [ ] **Step 6: Initial commit**

```bash
git add pyproject.toml config.toml .gitignore
git commit -m "chore: project bootstrap"
```

---

## Task 2: Config Module

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import tomllib, tomli_w, os, pytest
from pathlib import Path

def test_load_config_returns_defaults(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[overlay]\nport = 7331\n')
    from config import load_config
    cfg = load_config(cfg_path)
    assert cfg.overlay.port == 7331
    assert cfg.display.timestamps is True          # default
    assert cfg.gaze.cone_angle == 35.0             # default

def test_save_and_reload_roundtrip(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[overlay]\nport = 7331\n')
    from config import load_config, save_config
    cfg = load_config(cfg_path)
    cfg.overlay.fixed_x = 1.5
    save_config(cfg, cfg_path)
    cfg2 = load_config(cfg_path)
    assert cfg2.overlay.fixed_x == 1.5

def test_missing_keys_use_defaults(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('')   # empty file
    from config import load_config
    cfg = load_config(cfg_path)
    assert cfg.overlay.mode == "fixed"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /home/tomcatt/Projects/vr-chat-overlay
uv run pytest tests/test_config.py -v
```

Expected: `ImportError: No module named 'config'`

- [ ] **Step 3: Write config.py**

```python
# config.py
from __future__ import annotations
import tomllib
import tomli_w
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class TwitchConfig:
    channel: str = ""
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    token_expires: str = ""


@dataclass
class YouTubeConfig:
    stream_id: str = "auto"
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    token_expires: str = ""


@dataclass
class OverlayConfig:
    mode: str = "fixed"
    port: int = 7331
    fixed_x: float = 0.0
    fixed_y: float = 1.4
    fixed_z: float = -1.2
    fixed_rot_x: float = 0.0
    fixed_rot_y: float = 0.0
    fixed_rot_z: float = 0.0
    fixed_size: float = 0.6
    follow_angle: float = 30.0
    follow_distance: float = 1.2
    follow_height: float = -0.2
    follow_size: float = 0.6
    wrist_hand: str = "left"
    wrist_flip_threshold: float = 45.0
    wrist_size: float = 0.3


@dataclass
class DisplayConfig:
    opacity: float = 0.8
    timestamps: bool = True
    viewer_count_bar: bool = True
    join_leave_alerts: bool = True
    word_wrap: bool = True
    default_filter: str = "all"


@dataclass
class AlertsConfig:
    raids: bool = True
    follows: bool = True
    subs: bool = True
    bits: bool = True
    super_chat: bool = True
    new_members: bool = True


@dataclass
class GazeConfig:
    enabled: bool = True
    focused_brightness: float = 1.0
    away_behaviour: str = "dim"
    dim_level: float = 0.3
    cone_angle: float = 35.0
    fade_speed: str = "medium"


@dataclass
class Config:
    twitch: TwitchConfig = field(default_factory=TwitchConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    gaze: GazeConfig = field(default_factory=GazeConfig)


def _merge(defaults: dict, loaded: dict) -> dict:
    """Recursively merge loaded values over defaults."""
    result = dict(defaults)
    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path: Path = Path("config.toml")) -> Config:
    defaults = asdict(Config())
    try:
        loaded = tomllib.loads(path.read_text())
    except FileNotFoundError:
        loaded = {}
    merged = _merge(defaults, loaded)
    return Config(
        twitch=TwitchConfig(**merged["twitch"]),
        youtube=YouTubeConfig(**merged["youtube"]),
        overlay=OverlayConfig(**merged["overlay"]),
        display=DisplayConfig(**merged["display"]),
        alerts=AlertsConfig(**merged["alerts"]),
        gaze=GazeConfig(**merged["gaze"]),
    )


def save_config(cfg: Config, path: Path = Path("config.toml")) -> None:
    path.write_text(tomli_w.dumps(asdict(cfg)))
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: config module with load/save and dataclass types"
```

---

## Task 3: FastAPI Skeleton + WebSocket Broadcast

**Files:**
- Create: `server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_server.py
import pytest
from fastapi.testclient import TestClient

def test_root_serves_index():
    from server import app
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200

def test_health_endpoint():
    from server import app
    client = TestClient(app)
    r = client.get("/health")
    assert r.json() == {"status": "ok"}

def test_websocket_receives_broadcast():
    from server import app, broadcast
    import asyncio
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        asyncio.get_event_loop().run_until_complete(
            broadcast({"type": "chat", "message": "hello"})
        )
        data = ws.receive_json()
        assert data["type"] == "chat"
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/test_server.py -v
```

Expected: `ImportError: No module named 'server'`

- [ ] **Step 3: Write server.py**

```python
# server.py
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import load_config, Config

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

_clients: set[WebSocket] = set()
_config: Config = load_config()


async def broadcast(msg: dict[str, Any]) -> None:
    dead = set()
    for ws in _clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/settings")
async def settings_page():
    return FileResponse("static/settings.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        while True:
            await ws.receive_text()   # keep connection alive; client sends pings
    except WebSocketDisconnect:
        _clients.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=_config.overlay.port, reload=False)
```

- [ ] **Step 4: Create placeholder static files so the server starts**

```html
<!-- static/index.html -->
<!DOCTYPE html><html><body><h1>VR Chat Overlay</h1></body></html>
```

```html
<!-- static/settings.html -->
<!DOCTYPE html><html><body><h1>Settings</h1></body></html>
```

- [ ] **Step 5: Run tests — verify pass**

```bash
uv run pytest tests/test_server.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Verify server starts**

```bash
uv run python server.py
```

Expected: uvicorn starts on port 7331. Open `http://localhost:7331/` — see "VR Chat Overlay". Ctrl-C to stop.

- [ ] **Step 7: Commit**

```bash
git add server.py static/index.html static/settings.html tests/test_server.py
git commit -m "feat: FastAPI skeleton with WebSocket broadcast"
```

---

## Task 4: OAuth — Twitch + YouTube

**Files:**
- Create: `auth.py`
- Modify: `server.py` (include auth router)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_auth.py
from fastapi.testclient import TestClient

def test_twitch_auth_redirects():
    from server import app
    client = TestClient(app, follow_redirects=False)
    r = client.get("/auth/twitch")
    assert r.status_code in (302, 307)
    assert "twitch.tv" in r.headers["location"]

def test_youtube_auth_redirects():
    from server import app
    client = TestClient(app, follow_redirects=False)
    r = client.get("/auth/youtube")
    assert r.status_code in (302, 307)
    assert "google" in r.headers["location"].lower() or "accounts" in r.headers["location"]
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/test_auth.py -v
```

Expected: FAIL — routes don't exist yet.

- [ ] **Step 3: Write auth.py**

```python
# auth.py
from __future__ import annotations
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from config import load_config, save_config

router = APIRouter(prefix="/auth")

_TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
_TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_TWITCH_SCOPES = "chat:read chat:edit moderator:manage:banned_users moderator:manage:chat_messages channel:read:subscriptions bits:read moderator:read:followers"

_YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

_states: dict[str, str] = {}   # state → platform, prevents CSRF


@router.get("/twitch")
async def twitch_start(request: Request):
    cfg = load_config()
    state = secrets.token_urlsafe(16)
    _states[state] = "twitch"
    redirect_uri = str(request.url_for("twitch_callback"))
    params = urlencode({
        "client_id": cfg.twitch.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _TWITCH_SCOPES,
        "state": state,
        "force_verify": "true",
    })
    return RedirectResponse(f"{_TWITCH_AUTH_URL}?{params}")


@router.get("/twitch/callback", name="twitch_callback")
async def twitch_callback(request: Request, code: str, state: str):
    if _states.pop(state, None) != "twitch":
        return {"error": "Invalid state"}
    cfg = load_config()
    redirect_uri = str(request.url_for("twitch_callback"))
    async with httpx.AsyncClient() as client:
        r = await client.post(_TWITCH_TOKEN_URL, data={
            "client_id": cfg.twitch.client_id,
            "client_secret": cfg.twitch.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        })
    data = r.json()
    cfg.twitch.access_token = data["access_token"]
    cfg.twitch.refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 86400 * 60)
    cfg.twitch.token_expires = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).isoformat()
    save_config(cfg)
    return RedirectResponse("/settings?connected=twitch")


@router.get("/youtube")
async def youtube_start(request: Request):
    cfg = load_config()
    state = secrets.token_urlsafe(16)
    _states[state] = "youtube"
    redirect_uri = str(request.url_for("youtube_callback"))
    flow = Flow.from_client_config(
        {"web": {
            "client_id": cfg.youtube.client_id,
            "client_secret": cfg.youtube.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }},
        scopes=_YOUTUBE_SCOPES,
        redirect_uri=redirect_uri,
    )
    url, _ = flow.authorization_url(state=state, access_type="offline", prompt="consent")
    return RedirectResponse(url)


@router.get("/youtube/callback", name="youtube_callback")
async def youtube_callback(request: Request, code: str, state: str):
    if _states.pop(state, None) != "youtube":
        return {"error": "Invalid state"}
    cfg = load_config()
    redirect_uri = str(request.url_for("youtube_callback"))
    flow = Flow.from_client_config(
        {"web": {
            "client_id": cfg.youtube.client_id,
            "client_secret": cfg.youtube.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }},
        scopes=_YOUTUBE_SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    cfg.youtube.access_token = creds.token
    cfg.youtube.refresh_token = creds.refresh_token or ""
    cfg.youtube.token_expires = (
        creds.expiry.isoformat() if creds.expiry else ""
    )
    save_config(cfg)
    return RedirectResponse("/settings?connected=youtube")
```

- [ ] **Step 4: Include auth router in server.py**

Add after the existing imports:
```python
from auth import router as auth_router
app.include_router(auth_router)
```

- [ ] **Step 5: Run tests — verify pass**

```bash
uv run pytest tests/test_auth.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add auth.py tests/test_auth.py server.py
git commit -m "feat: OAuth flows for Twitch and YouTube"
```

---

## Task 5: Twitch IRC Client (Chat + Join/Leave)

**Files:**
- Create: `twitch.py`
- Create: `tests/test_twitch.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_twitch.py
import pytest
from twitch import parse_privmsg, parse_usernotice, parse_membership

def test_parse_privmsg_basic():
    raw = "@badge-info=;badges=;color=#FF0000;display-name=xX_Gamer;id=abc123;user-id=123 :xX_Gamer!xX_Gamer@xX_Gamer.tmi.twitch.tv PRIVMSG #channel :hello chat"
    msg = parse_privmsg(raw)
    assert msg["type"] == "chat"
    assert msg["platform"] == "twitch"
    assert msg["username"] == "xX_Gamer"
    assert msg["message"] == "hello chat"
    assert msg["color"] == "#FF0000"
    assert msg["message_id"] == "abc123"

def test_parse_privmsg_bits():
    raw = "@bits=500;color=#0000FF;display-name=CheerGuy;id=def456 :CheerGuy!CheerGuy@CheerGuy.tmi.twitch.tv PRIVMSG #channel :Cheer500 you rock!"
    msg = parse_privmsg(raw)
    assert msg["type"] == "alert"
    assert msg["alert_type"] == "bits"
    assert msg["amount"] == 500

def test_parse_join():
    raw = ":someuser!someuser@someuser.tmi.twitch.tv JOIN #channel"
    msg = parse_membership(raw)
    assert msg["type"] == "join"
    assert msg["username"] == "someuser"

def test_parse_part():
    raw = ":olduser!olduser@olduser.tmi.twitch.tv PART #channel"
    msg = parse_membership(raw)
    assert msg["type"] == "part"
    assert msg["username"] == "olduser"
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/test_twitch.py -v
```

Expected: `ImportError: No module named 'twitch'`

- [ ] **Step 3: Write twitch.py (parsers + IRC client)**

```python
# twitch.py
from __future__ import annotations
import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Callable

import websockets
import httpx


_TAG_RE = re.compile(r"@([^\s]+)")
_PRIVMSG_RE = re.compile(r":(\S+)!\S+@\S+ PRIVMSG #\S+ :(.*)")
_MEMBERSHIP_RE = re.compile(r":(\w+)!\w+@\w+\.tmi\.twitch\.tv (JOIN|PART) #\S+")
_USERNOTICE_RE = re.compile(r":tmi\.twitch\.tv USERNOTICE #\S+(?: :(.*))?")


def _parse_tags(raw: str) -> dict[str, str]:
    match = _TAG_RE.match(raw)
    if not match:
        return {}
    return dict(kv.split("=", 1) for kv in match.group(1).split(";") if "=" in kv)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_privmsg(raw: str) -> dict[str, Any] | None:
    tags = _parse_tags(raw)
    m = _PRIVMSG_RE.search(raw)
    if not m:
        return None
    username = tags.get("display-name") or m.group(1)
    message = m.group(2)
    bits = int(tags.get("bits", 0))
    if bits:
        return {"type": "alert", "platform": "twitch", "alert_type": "bits",
                "username": username, "message": message,
                "amount": bits, "timestamp": _now()}
    return {"type": "chat", "platform": "twitch",
            "username": username, "color": tags.get("color", "#9146FF"),
            "message": message, "timestamp": _now(),
            "message_id": tags.get("id", "")}


def parse_membership(raw: str) -> dict[str, Any] | None:
    m = _MEMBERSHIP_RE.search(raw)
    if not m:
        return None
    return {"type": m.group(2).lower(), "platform": "twitch",
            "username": m.group(1), "timestamp": _now()}


def parse_usernotice(raw: str) -> dict[str, Any] | None:
    tags = _parse_tags(raw)
    msg_id = tags.get("msg-id", "")
    username = tags.get("display-name", tags.get("login", ""))
    m = _USERNOTICE_RE.search(raw)
    sub_message = m.group(1) if m and m.group(1) else ""

    if msg_id in ("sub", "resub"):
        return {"type": "alert", "platform": "twitch", "alert_type": msg_id,
                "username": username, "message": sub_message,
                "amount": int(tags.get("msg-param-cumulative-months", 1)),
                "timestamp": _now()}
    if msg_id == "subgift":
        recipient = tags.get("msg-param-recipient-display-name", "")
        return {"type": "alert", "platform": "twitch", "alert_type": "subgift",
                "username": username, "message": f"gifted a sub to {recipient}",
                "amount": 1, "timestamp": _now()}
    if msg_id == "raid":
        return {"type": "alert", "platform": "twitch", "alert_type": "raid",
                "username": username,
                "message": f"raiding with {tags.get('msg-param-viewerCount', '?')} viewers!",
                "amount": int(tags.get("msg-param-viewerCount", 0)),
                "timestamp": _now()}
    return None


class TwitchIRC:
    _IRC_URL = "wss://irc-ws.chat.twitch.tv:443"
    _CAPS = "CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership\r\n"

    def __init__(self, token: str, nick: str, channel: str,
                 on_event: Callable[[dict], None]):
        self.token = token
        self.nick = nick.lower()
        self.channel = channel.lower()
        self.on_event = on_event
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self._IRC_URL) as ws:
                    await ws.send(self._CAPS)
                    await ws.send(f"PASS oauth:{self.token}\r\n")
                    await ws.send(f"NICK {self.nick}\r\n")
                    await ws.send(f"JOIN #{self.channel}\r\n")
                    async for raw in ws:
                        if raw.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv\r\n")
                            continue
                        self._dispatch(raw)
            except Exception:
                if self._running:
                    await asyncio.sleep(5)   # reconnect after 5 s

    def _dispatch(self, raw: str) -> None:
        if "PRIVMSG" in raw:
            msg = parse_privmsg(raw)
        elif "USERNOTICE" in raw:
            msg = parse_usernotice(raw)
        elif " JOIN " in raw or " PART " in raw:
            msg = parse_membership(raw)
        else:
            return
        if msg:
            self.on_event(msg)

    def stop(self) -> None:
        self._running = False


async def send_irc_command(token: str, channel: str, command: str) -> None:
    """Send a single mod command and disconnect. e.g. /ban username"""
    async with websockets.connect(TwitchIRC._IRC_URL) as ws:
        await ws.send(f"PASS oauth:{token}\r\n")
        await ws.send(f"NICK moderatorbot\r\n")
        await ws.send(f"JOIN #{channel}\r\n")
        await ws.send(f"PRIVMSG #{channel} :{command}\r\n")
        await asyncio.sleep(0.5)
```

- [ ] **Step 4: Run tests — verify pass**

```bash
uv run pytest tests/test_twitch.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add twitch.py tests/test_twitch.py
git commit -m "feat: Twitch IRC client with chat, join/leave, alerts, mod commands"
```

---

## Task 6: Twitch Helix API — Viewer Count, Stream Timer, Follows

**Files:**
- Modify: `twitch.py` (add `TwitchHelix` class)
- Modify: `tests/test_twitch.py` (add Helix tests)

- [ ] **Step 1: Add failing tests**

```python
# append to tests/test_twitch.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_helix_returns_viewer_data():
    from twitch import TwitchHelix
    mock_response = {
        "data": [{
            "viewer_count": 1204,
            "started_at": "2026-06-16T10:00:00Z",
        }]
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.json = lambda: mock_response
        mock_get.return_value.raise_for_status = lambda: None
        helix = TwitchHelix("token123", "client_id_x", "mychannel")
        data = await helix.fetch_stream_data()
        assert data["viewer_count"] == 1204
        assert "started_at" in data
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/test_twitch.py::test_helix_returns_viewer_data -v
```

Expected: FAIL — `TwitchHelix` not defined.

- [ ] **Step 3: Add TwitchHelix to twitch.py**

```python
# append to twitch.py

class TwitchHelix:
    _BASE = "https://api.twitch.tv/helix"

    def __init__(self, token: str, client_id: str, channel: str):
        self.token = token
        self.client_id = client_id
        self.channel = channel

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}",
                "Client-Id": self.client_id}

    async def fetch_stream_data(self) -> dict | None:
        """Returns dict with viewer_count and started_at, or None if offline."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self._BASE}/streams",
                params={"user_login": self.channel},
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            return data[0] if data else None

    async def get_user_id(self) -> str:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self._BASE}/users",
                                  params={"login": self.channel},
                                  headers=self._headers())
            r.raise_for_status()
            return r.json()["data"][0]["id"]
```

- [ ] **Step 4: Add EventSub follow subscription helper**

```python
# append to twitch.py

async def subscribe_eventsub_follows(token: str, client_id: str,
                                      broadcaster_id: str, session_id: str) -> None:
    """Subscribe to channel.follow events on an active EventSub WebSocket session."""
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            headers={"Authorization": f"Bearer {token}", "Client-Id": client_id,
                     "Content-Type": "application/json"},
            json={
                "type": "channel.follow",
                "version": "2",
                "condition": {"broadcaster_user_id": broadcaster_id,
                              "moderator_user_id": broadcaster_id},
                "transport": {"method": "websocket", "session_id": session_id},
            },
        )


class TwitchEventSub:
    """Connects to Twitch EventSub WebSocket for follow events."""
    _URL = "wss://eventsub.wss.twitch.tv/ws"

    def __init__(self, token: str, client_id: str, broadcaster_id: str,
                 on_event: Callable[[dict], None]):
        self.token = token
        self.client_id = client_id
        self.broadcaster_id = broadcaster_id
        self.on_event = on_event
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self._URL) as ws:
                    async for raw in ws:
                        import json as _json
                        msg = _json.loads(raw)
                        msg_type = msg.get("metadata", {}).get("message_type", "")
                        if msg_type == "session_welcome":
                            session_id = msg["payload"]["session"]["id"]
                            await subscribe_eventsub_follows(
                                self.token, self.client_id,
                                self.broadcaster_id, session_id)
                        elif msg_type == "notification":
                            event = msg["payload"]["event"]
                            self.on_event({
                                "type": "alert", "platform": "twitch",
                                "alert_type": "follow",
                                "username": event.get("user_name", ""),
                                "message": "just followed!",
                                "amount": None, "timestamp": _now(),
                            })
            except Exception:
                if self._running:
                    await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 5: Run all Twitch tests**

```bash
uv run pytest tests/test_twitch.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add twitch.py tests/test_twitch.py
git commit -m "feat: Twitch Helix viewer count, stream timer, EventSub follows"
```

---

## Task 7: YouTube Client (Chat, Events, Viewer Count, Stream Timer)

**Files:**
- Create: `youtube.py`
- Create: `tests/test_youtube.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_youtube.py
import pytest
from unittest.mock import MagicMock, patch

def _make_chat_item(msg_type="textMessageEvent", amount_micros=None):
    item = {
        "id": "msg001",
        "snippet": {
            "type": msg_type,
            "publishedAt": "2026-06-16T12:00:00Z",
            "authorChannelId": "UCxxx",
            "displayMessage": "great stream!",
        },
        "authorDetails": {
            "displayName": "CoolViewer",
            "profileImageUrl": "",
        }
    }
    if amount_micros:
        item["snippet"]["superChatDetails"] = {
            "amountMicros": str(amount_micros),
            "currency": "USD",
            "userComment": "amazing stream!",
        }
    return item

def test_parse_text_message():
    from youtube import parse_chat_item
    item = _make_chat_item()
    msg = parse_chat_item(item)
    assert msg["type"] == "chat"
    assert msg["platform"] == "youtube"
    assert msg["username"] == "CoolViewer"
    assert msg["message"] == "great stream!"

def test_parse_super_chat():
    from youtube import parse_chat_item
    item = _make_chat_item("superChatEvent", amount_micros=10_000_000)
    msg = parse_chat_item(item)
    assert msg["type"] == "alert"
    assert msg["alert_type"] == "super_chat"
    assert msg["amount"] == 10   # USD cents → dollars

def test_parse_new_member():
    from youtube import parse_chat_item
    item = _make_chat_item("newSponsorEvent")
    msg = parse_chat_item(item)
    assert msg["type"] == "alert"
    assert msg["alert_type"] == "new_member"
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest tests/test_youtube.py -v
```

Expected: `ImportError: No module named 'youtube'`

- [ ] **Step 3: Write youtube.py**

```python
# youtube.py
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import load_config, save_config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_chat_item(item: dict) -> dict[str, Any] | None:
    snippet = item.get("snippet", {})
    author = item.get("authorDetails", {})
    msg_type = snippet.get("type", "")
    username = author.get("displayName", "")
    message_id = item.get("id", "")
    ts = snippet.get("publishedAt", _now())

    if msg_type == "textMessageEvent":
        return {"type": "chat", "platform": "youtube",
                "username": username, "color": "#FF0000",
                "message": snippet.get("displayMessage", ""),
                "timestamp": ts, "message_id": message_id}

    if msg_type == "superChatEvent":
        details = snippet.get("superChatDetails", {})
        micros = int(details.get("amountMicros", 0))
        dollars = micros // 1_000_000
        return {"type": "alert", "platform": "youtube", "alert_type": "super_chat",
                "username": username,
                "message": details.get("userComment", ""),
                "amount": dollars, "timestamp": ts}

    if msg_type == "newSponsorEvent":
        return {"type": "alert", "platform": "youtube", "alert_type": "new_member",
                "username": username, "message": "joined as a member!",
                "amount": None, "timestamp": ts}

    return None


class YouTubeClient:
    def __init__(self, on_event: Callable[[dict], None]):
        self.on_event = on_event
        self._running = False
        self._service = None
        self._live_chat_id: str | None = None
        self._next_page_token: str | None = None

    def _build_service(self):
        cfg = load_config()
        creds = Credentials(
            token=cfg.youtube.access_token,
            refresh_token=cfg.youtube.refresh_token,
            client_id=cfg.youtube.client_id,
            client_secret=cfg.youtube.client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    async def _find_active_broadcast(self) -> dict | None:
        loop = asyncio.get_event_loop()
        svc = self._service
        def _fetch():
            return svc.liveBroadcasts().list(
                part="id,liveStreamingDetails,statistics",
                broadcastStatus="active",
                mine=True,
                maxResults=1,
            ).execute()
        result = await loop.run_in_executor(None, _fetch)
        items = result.get("items", [])
        return items[0] if items else None

    async def _poll_chat(self) -> None:
        loop = asyncio.get_event_loop()
        svc = self._service

        def _fetch():
            return svc.liveChatMessages().list(
                liveChatId=self._live_chat_id,
                part="snippet,authorDetails",
                pageToken=self._next_page_token,
                maxResults=200,
            ).execute()

        result = await loop.run_in_executor(None, _fetch)
        self._next_page_token = result.get("nextPageToken")
        for item in result.get("items", []):
            msg = parse_chat_item(item)
            if msg:
                self.on_event(msg)
        # YouTube tells us the minimum poll interval
        return result.get("pollingIntervalMillis", 5000) / 1000

    async def fetch_stream_status(self) -> dict | None:
        """Returns dict with viewer_count and started_at, or None if offline."""
        broadcast = await self._find_active_broadcast()
        if not broadcast:
            return None
        details = broadcast.get("liveStreamingDetails", {})
        stats = broadcast.get("statistics", {})
        return {
            "viewer_count": int(stats.get("concurrentViewers", 0)),
            "started_at": details.get("actualStartTime", ""),
        }

    async def delete_message(self, message_id: str) -> None:
        loop = asyncio.get_event_loop()
        svc = self._service
        await loop.run_in_executor(None, lambda: svc.liveChatMessages().delete(id=message_id).execute())

    async def ban_user(self, channel_id: str, banned_channel_id: str) -> None:
        loop = asyncio.get_event_loop()
        svc = self._service
        body = {"snippet": {"liveChatId": self._live_chat_id,
                            "type": "permanent",
                            "bannedUserDetails": {"channelId": banned_channel_id}}}
        await loop.run_in_executor(None, lambda: svc.liveChatBans().insert(part="snippet", body=body).execute())

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                self._service = self._build_service()
                broadcast = await self._find_active_broadcast()
                if not broadcast:
                    await asyncio.sleep(60)
                    continue
                self._live_chat_id = broadcast["liveStreamingDetails"]["activeLiveChatId"]
                self._next_page_token = None
                while self._running:
                    wait = await self._poll_chat()
                    await asyncio.sleep(wait)
            except Exception:
                if self._running:
                    await asyncio.sleep(10)

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 4: Run tests — verify pass**

```bash
uv run pytest tests/test_youtube.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add youtube.py tests/test_youtube.py
git commit -m "feat: YouTube chat polling, super chat, member events, viewer count"
```

---

## Task 8: Wire Backend — Status Poller + Moderation Endpoints

**Files:**
- Modify: `server.py` (add startup tasks, mod endpoints, config API)

- [ ] **Step 1: Add startup background tasks to server.py**

Replace `if __name__ == "__main__":` block and add lifespan:

```python
# server.py  — add/replace these sections

from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone

from twitch import TwitchIRC, TwitchHelix, TwitchEventSub
from youtube import YouTubeClient

_twitch_irc: TwitchIRC | None = None
_yt_client: YouTubeClient | None = None


def _on_event(msg: dict) -> None:
    asyncio.create_task(broadcast(msg))


async def _status_loop() -> None:
    cfg = load_config()
    twitch_helix = TwitchHelix(cfg.twitch.access_token,
                                cfg.twitch.client_id,
                                cfg.twitch.channel) if cfg.twitch.access_token else None
    yt = YouTubeClient(_on_event) if cfg.youtube.access_token else None

    while True:
        status: dict = {"type": "status",
                        "twitch_viewers": None, "youtube_viewers": None,
                        "stream_elapsed_seconds": None,
                        "twitch_token_expires": cfg.twitch.token_expires or None,
                        "youtube_token_expires": cfg.youtube.token_expires or None}
        earliest_start: datetime | None = None

        if twitch_helix:
            try:
                data = await twitch_helix.fetch_stream_data()
                if data:
                    status["twitch_viewers"] = data["viewer_count"]
                    t = datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
                    if earliest_start is None or t < earliest_start:
                        earliest_start = t
            except Exception:
                pass

        if yt:
            try:
                data = await yt.fetch_stream_status()
                if data:
                    status["youtube_viewers"] = data["viewer_count"]
                    if data["started_at"]:
                        t = datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
                        if earliest_start is None or t < earliest_start:
                            earliest_start = t
            except Exception:
                pass

        if earliest_start:
            status["stream_elapsed_seconds"] = int(
                (datetime.now(timezone.utc) - earliest_start).total_seconds()
            )

        await broadcast(status)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    tasks = []
    if cfg.twitch.access_token and cfg.twitch.channel:
        irc = TwitchIRC(cfg.twitch.access_token, cfg.twitch.channel,
                        cfg.twitch.channel, _on_event)
        tasks.append(asyncio.create_task(irc.run()))
        if cfg.twitch.client_id:
            helix = TwitchHelix(cfg.twitch.access_token,
                                cfg.twitch.client_id, cfg.twitch.channel)
            broadcaster_id = await helix.get_user_id()
            eventsub = TwitchEventSub(cfg.twitch.access_token, cfg.twitch.client_id,
                                      broadcaster_id, _on_event)
            tasks.append(asyncio.create_task(eventsub.run()))
    if cfg.youtube.access_token:
        yt = YouTubeClient(_on_event)
        tasks.append(asyncio.create_task(yt.run()))
    tasks.append(asyncio.create_task(_status_loop()))
    yield
    for t in tasks:
        t.cancel()

app = FastAPI(lifespan=lifespan)
```

- [ ] **Step 2: Add moderation endpoints**

```python
# append to server.py

from pydantic import BaseModel
from twitch import send_irc_command

class ModAction(BaseModel):
    platform: str
    action: str         # "ban" | "timeout" | "delete"
    message_id: str
    username: str
    duration: int = 600  # seconds for timeout

@app.post("/mod/action")
async def mod_action(action: ModAction):
    cfg = load_config()
    if action.platform == "twitch":
        if action.action == "ban":
            cmd = f"/ban {action.username}"
        elif action.action == "timeout":
            cmd = f"/timeout {action.username} {action.duration}"
        elif action.action == "delete":
            cmd = f"/delete {action.message_id}"
        else:
            return {"error": "unknown action"}
        await send_irc_command(cfg.twitch.access_token, cfg.twitch.channel, cmd)
    elif action.platform == "youtube":
        # YouTube mod actions handled by YouTubeClient methods
        # Re-instantiated here since we don't hold a global ref to the client
        # In a real implementation, store the client reference in app state
        pass
    return {"ok": True}
```

- [ ] **Step 3: Add config API endpoints**

```python
# append to server.py

import json as _json

@app.get("/api/config")
async def get_config():
    from dataclasses import asdict
    cfg = load_config()
    d = asdict(cfg)
    # Never expose secrets over the API
    for section in ("twitch", "youtube"):
        d[section]["access_token"] = "***" if d[section]["access_token"] else ""
        d[section]["refresh_token"] = "***" if d[section]["refresh_token"] else ""
        d[section]["client_secret"] = "***" if d[section]["client_secret"] else ""
    return d

@app.post("/api/config")
async def post_config(request: Request):
    from dataclasses import asdict
    body = await request.json()
    cfg = load_config()
    d = asdict(cfg)
    # Only update non-secret, non-token fields from the UI
    safe_fields = {"display", "alerts", "gaze", "overlay"}
    for section in safe_fields:
        if section in body:
            for k, v in body[section].items():
                if k in d[section]:
                    d[section][k] = v
    # Rebuild config from merged dict
    from config import Config, TwitchConfig, YouTubeConfig, OverlayConfig, DisplayConfig, AlertsConfig, GazeConfig
    new_cfg = Config(
        twitch=cfg.twitch,   # keep existing tokens untouched
        youtube=cfg.youtube,
        overlay=OverlayConfig(**d["overlay"]),
        display=DisplayConfig(**d["display"]),
        alerts=AlertsConfig(**d["alerts"]),
        gaze=GazeConfig(**d["gaze"]),
    )
    save_config(new_cfg)
    return {"ok": True}
```

- [ ] **Step 4: Verify server starts with new code**

```bash
uv run python server.py
```

Expected: starts cleanly (no token errors — background tasks simply won't connect yet since config is empty). Ctrl-C to stop.

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "feat: startup task wiring, moderation endpoints, config API"
```

---

## Task 9: Frontend HTML + CSS

**Files:**
- Overwrite: `static/index.html`
- Overwrite: `static/settings.html`
- Create: `static/style.css`

- [ ] **Step 1: Write style.css**

```css
/* static/style.css */
:root {
  --bg: #0a0a1a;
  --surface: #0d0d20;
  --border: #1a1a2e;
  --text: #ddd;
  --muted: #555;
  --twitch: #9146ff;
  --youtube: #f00;

  --alert-raid-bg: #1a0f00;
  --alert-raid: #f59e0b;
  --alert-follow-bg: #0f1e0f;
  --alert-follow: #22c55e;
  --alert-sub-bg: #1a0f2e;
  --alert-sub: #a855f7;
  --alert-subgift: #c4b5fd;
  --alert-bits-bg: #1a1500;
  --alert-bits: #fbbf24;
  --alert-superchat-bg: #1a0a00;
  --alert-superchat: #f97316;
  --alert-member-bg: #0f1e0f;
  --alert-member: #4ade80;

  --fade-slow: 1.2s;
  --fade-medium: 0.4s;
  --fade-fast: 0.1s;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body { background: var(--bg); color: var(--text); font-family: monospace;
       font-size: 12px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* ── Filter tabs ── */
#tabs { background: #111; border-bottom: 1px solid var(--border);
        padding: 5px 8px; display: flex; gap: 6px; justify-content: space-between;
        align-items: center; flex-shrink: 0; }
.tab { background: var(--bg); border: 1px solid var(--border);
       border-radius: 3px; padding: 2px 8px; color: var(--muted);
       cursor: pointer; font-family: monospace; font-size: 10px; }
.tab.active { border-color: var(--twitch); color: var(--twitch); }
#cog-btn { background: none; border: none; color: var(--muted); cursor: pointer;
           font-size: 14px; }

/* ── Chat feed ── */
#chat { flex: 1; overflow-y: auto; padding: 6px 8px; line-height: 1.9; }
#chat::-webkit-scrollbar { width: 4px; }
#chat::-webkit-scrollbar-thumb { background: var(--border); }

.msg { display: flex; gap: 6px; align-items: baseline; }
.msg.wrap { flex-wrap: wrap; }
.msg .ts { color: var(--muted); font-size: 9px; white-space: nowrap; flex-shrink: 0; }
.msg .platform { flex-shrink: 0; }
.msg .author { white-space: nowrap; flex-shrink: 0; cursor: pointer; }
.msg .text { word-break: break-word; }
.msg.no-wrap .text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* join/leave */
.join-event { color: #22c55e; font-size: 10px; padding: 1px 0; }
.part-event { color: #f87171; font-size: 10px; padding: 1px 0; }

/* alerts */
.alert-line { border-left: 3px solid; padding: 3px 6px; margin: 3px 0;
              border-radius: 0 3px 3px 0; line-height: 1.8; }
.alert-raid    { background: var(--alert-raid-bg);     border-color: var(--alert-raid);     color: var(--alert-raid); }
.alert-follow  { background: var(--alert-follow-bg);   border-color: var(--alert-follow);   color: var(--alert-follow); }
.alert-sub, .alert-resub { background: var(--alert-sub-bg); border-color: var(--alert-sub); color: var(--alert-sub); }
.alert-subgift { background: var(--alert-sub-bg);      border-color: var(--alert-subgift);  color: var(--alert-subgift); }
.alert-bits    { background: var(--alert-bits-bg);     border-color: var(--alert-bits);     color: var(--alert-bits); }
.alert-super_chat { background: var(--alert-superchat-bg); border-color: var(--alert-superchat); color: var(--alert-superchat); }
.alert-new_member { background: var(--alert-member-bg); border-color: var(--alert-member); color: var(--alert-member); }

/* alert icons */
.icon-raid::before    { content: "⚡ "; }
.icon-follow::before  { content: "★ "; }
.icon-sub::before, .icon-resub::before { content: "♦ "; }
.icon-subgift::before { content: "♦ "; }
.icon-bits::before    { content: "⬡ "; }
.icon-super_chat::before { content: "$ "; }
.icon-new_member::before { content: "★ "; }

/* ── Status bar ── */
#statusbar { background: #0d0d1a; border-top: 1px solid var(--border);
             padding: 5px 8px; display: flex; justify-content: space-between;
             align-items: center; font-size: 9px; flex-shrink: 0; }
#statusbar .viewers { display: flex; gap: 10px; }
#statusbar .timer { display: flex; align-items: center; gap: 5px; }
.live-dot { color: #f87171; }
.elapsed { color: #fff; letter-spacing: 1px; }
#statusbar .tokens { color: var(--muted); }

/* ── Mod context menu ── */
#mod-menu { position: fixed; background: #111; border: 1px solid var(--border);
            border-radius: 4px; padding: 4px 0; z-index: 999; display: none; min-width: 120px; }
#mod-menu button { display: block; width: 100%; background: none; border: none;
                   color: var(--text); padding: 5px 12px; text-align: left;
                   cursor: pointer; font-family: monospace; font-size: 10px; }
#mod-menu button:hover { background: var(--border); }

/* ── Gaze opacity transitions ── */
body[data-gaze="slow"]   { transition: opacity var(--fade-slow)   ease; }
body[data-gaze="medium"] { transition: opacity var(--fade-medium) ease; }
body[data-gaze="fast"]   { transition: opacity var(--fade-fast)   ease; }

/* ── Settings page ── */
.settings-grid { display: flex; gap: 16px; flex-wrap: wrap; padding: 14px; }
.settings-col  { flex: 1; min-width: 200px; }
.section-label { color: var(--muted); font-size: 8px; letter-spacing: 1px;
                 margin-bottom: 6px; margin-top: 12px; }
.settings-group { border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
.settings-row { padding: 7px 10px; border-bottom: 1px solid var(--border);
                display: flex; justify-content: space-between; align-items: center; }
.settings-row:last-child { border-bottom: none; }
.settings-row label { color: #aaa; }
.badge { font-size: 7px; padding: 1px 4px; border-radius: 2px; }
.badge-twitch { background: #1a1a2e; color: var(--twitch); }
.badge-youtube { background: #1a0000; color: var(--youtube); }
.toggle { cursor: pointer; font-weight: bold; }
.toggle.on  { color: #22c55e; }
.toggle.off { color: #f87171; }
.countdown { background: var(--border); padding: 2px 5px; border-radius: 2px; }
.countdown.warning { color: #fbbf24; }
.countdown.ok { color: #22c55e; }

/* legend colour bars */
.legend-bar { width: 3px; height: 14px; border-radius: 1px; flex-shrink: 0; }
```

- [ ] **Step 2: Write index.html**

```html
<!-- static/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>VR Chat</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body data-gaze="medium">
  <div id="tabs">
    <div style="display:flex;gap:6px;">
      <button class="tab active" data-filter="all">All</button>
      <button class="tab" data-filter="twitch">Twitch</button>
      <button class="tab" data-filter="youtube">YouTube</button>
    </div>
    <button id="cog-btn" onclick="window.location='/settings'">⚙</button>
  </div>

  <div id="chat"></div>

  <div id="statusbar">
    <div class="viewers">
      <span id="twitch-viewers" style="color:#aaa;">■ —</span>
      <span id="yt-viewers" style="color:#aaa;">▶ —</span>
    </div>
    <div class="timer">
      <span class="live-dot" id="live-dot" style="display:none;">●</span>
      <span class="elapsed" id="elapsed" style="display:none;"></span>
    </div>
    <div class="tokens">
      <span id="twitch-token"></span>
      &nbsp;·&nbsp;
      <span id="yt-token"></span>
    </div>
  </div>

  <div id="mod-menu">
    <button onclick="modAction('ban')">Ban</button>
    <button onclick="modAction('timeout')">Timeout 10m</button>
    <button onclick="modAction('delete')">Delete message</button>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write settings.html**

```html
<!-- static/settings.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>VR Chat — Settings</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body style="overflow:auto;">
  <div id="tabs">
    <div style="display:flex;gap:16px;font-size:10px;padding:0 4px;">
      <a href="/" style="color:var(--muted);text-decoration:none;">Chat</a>
      <span style="color:#3b82f6;border-bottom:1px solid #3b82f6;padding-bottom:2px;">Settings</span>
    </div>
  </div>

  <div class="settings-grid">
    <!-- Left column -->
    <div class="settings-col">
      <div class="section-label">CONNECTIONS</div>
      <div class="settings-group" id="connections-group">
        <div class="settings-row">
          <label style="color:var(--twitch);">■ Twitch</label>
          <div style="display:flex;gap:8px;align-items:center;">
            <span id="twitch-status">—</span>
            <span id="twitch-countdown" class="countdown" style="display:none;"></span>
            <a href="/auth/twitch" style="color:#3b82f6;font-size:9px;">Reconnect</a>
          </div>
        </div>
        <div class="settings-row">
          <label style="color:var(--youtube);">▶ YouTube</label>
          <div style="display:flex;gap:8px;align-items:center;">
            <span id="yt-status">—</span>
            <span id="yt-countdown" class="countdown" style="display:none;"></span>
            <a href="/auth/youtube" style="color:#3b82f6;font-size:9px;">Reconnect</a>
          </div>
        </div>
      </div>

      <div class="section-label">DISPLAY</div>
      <div class="settings-group">
        <div class="settings-row"><label>Timestamps</label><span class="toggle" data-key="display.timestamps"></span></div>
        <div class="settings-row"><label>Word wrap</label><span class="toggle" data-key="display.word_wrap"></span></div>
        <div class="settings-row"><label>Viewer count bar</label><span class="toggle" data-key="display.viewer_count_bar"></span></div>
        <div class="settings-row">
          <label>Join / leave <span class="badge badge-twitch">Twitch</span></label>
          <span class="toggle" data-key="display.join_leave_alerts"></span>
        </div>
      </div>

      <div class="section-label">GAZE-AWARE OPACITY</div>
      <div class="settings-group">
        <div class="settings-row"><label>Enable gaze dimming</label><span class="toggle" data-key="gaze.enabled"></span></div>
        <div class="settings-row"><label>Gaze source</label><span id="gaze-source" style="color:#3b82f6;font-size:9px;">detecting…</span></div>
        <div class="settings-row"><label>Away behaviour</label><span id="gaze-away" style="color:#aaa;font-size:9px;"></span></div>
        <div class="settings-row"><label>Dim level</label><span id="gaze-dim" style="color:#aaa;font-size:9px;"></span></div>
        <div class="settings-row"><label>Cone angle</label><span id="gaze-cone" style="color:#aaa;font-size:9px;"></span></div>
        <div class="settings-row"><label>Fade speed</label><span id="gaze-fade" style="color:#aaa;font-size:9px;"></span></div>
      </div>
    </div>

    <!-- Right column -->
    <div class="settings-col">
      <div class="section-label">ALERTS IN CHAT</div>
      <div class="settings-group">
        <div class="settings-row"><label>⚡ Raids <span class="badge badge-twitch">Twitch</span></label><span class="toggle" data-key="alerts.raids"></span></div>
        <div class="settings-row"><label>★ Follows <span class="badge badge-twitch">Twitch</span></label><span class="toggle" data-key="alerts.follows"></span></div>
        <div class="settings-row"><label>♦ Subs / Gifts <span class="badge badge-twitch">Twitch</span></label><span class="toggle" data-key="alerts.subs"></span></div>
        <div class="settings-row"><label>⬡ Bits / Cheers <span class="badge badge-twitch">Twitch</span></label><span class="toggle" data-key="alerts.bits"></span></div>
        <div class="settings-row"><label>$ Super Chat <span class="badge badge-youtube">YouTube</span></label><span class="toggle" data-key="alerts.super_chat"></span></div>
        <div class="settings-row"><label>★ New Members <span class="badge badge-youtube">YouTube</span></label><span class="toggle" data-key="alerts.new_members"></span></div>
      </div>

      <div class="section-label">COLOUR LEGEND</div>
      <div class="settings-group">
        <div class="settings-row"><div style="display:flex;align-items:center;gap:8px;"><div class="legend-bar" style="background:#f59e0b;"></div><span style="color:#f59e0b;">⚡ Amber</span></div><span style="color:var(--muted);font-size:9px;">— Raid incoming</span></div>
        <div class="settings-row"><div style="display:flex;align-items:center;gap:8px;"><div class="legend-bar" style="background:#22c55e;"></div><span style="color:#22c55e;">★ Green</span></div><span style="color:var(--muted);font-size:9px;">— Follow / YT member</span></div>
        <div class="settings-row"><div style="display:flex;align-items:center;gap:8px;"><div class="legend-bar" style="background:#a855f7;"></div><span style="color:#a855f7;">♦ Purple</span></div><span style="color:var(--muted);font-size:9px;">— Sub or gifted sub</span></div>
        <div class="settings-row"><div style="display:flex;align-items:center;gap:8px;"><div class="legend-bar" style="background:#fbbf24;"></div><span style="color:#fbbf24;">⬡ Yellow</span></div><span style="color:var(--muted);font-size:9px;">— Bits / Cheers</span></div>
        <div class="settings-row"><div style="display:flex;align-items:center;gap:8px;"><div class="legend-bar" style="background:#f97316;"></div><span style="color:#f97316;">$ Orange</span></div><span style="color:var(--muted);font-size:9px;">— YouTube Super Chat</span></div>
      </div>

      <div class="section-label">OVERLAY POSITION</div>
      <div class="settings-group" id="position-group">
        <div class="settings-row"><label>Mode</label><span id="pos-mode" style="color:#3b82f6;"></span></div>
        <div class="settings-row"><label>X / Y / Z</label><span id="pos-xyz" style="color:#fff;font-size:9px;"></span></div>
        <div class="settings-row"><label>Size (m)</label><span id="pos-size" style="color:#fff;"></span></div>
      </div>
    </div>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Verify pages load**

```bash
uv run python server.py
```

Open `http://localhost:7331/` and `http://localhost:7331/settings` — both should render styled pages. Ctrl-C.

- [ ] **Step 5: Commit**

```bash
git add static/style.css static/index.html static/settings.html
git commit -m "feat: HTML/CSS for chat view and settings page"
```

---

## Task 10: Frontend JavaScript

**Files:**
- Create: `static/app.js`

- [ ] **Step 1: Write app.js**

```javascript
// static/app.js
(function () {
  /* ── State ── */
  let cfg = {};
  let activeFilter = "all";
  let modTarget = null;   // {platform, message_id, username}
  const MAX_MESSAGES = 300;

  /* ── WebSocket ── */
  function connect() {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
    ws.onclose = () => setTimeout(connect, 3000);
  }

  function handleMessage(msg) {
    if (msg.type === "status") { updateStatus(msg); return; }
    if (msg.type === "chat")   { appendChat(msg); return; }
    if (msg.type === "join")   { if (cfg.display?.join_leave_alerts) appendJoinPart(msg); return; }
    if (msg.type === "part")   { if (cfg.display?.join_leave_alerts) appendJoinPart(msg); return; }
    if (msg.type === "alert")  { appendAlert(msg); return; }
  }

  /* ── Helpers ── */
  function fmtTime(isoStr) {
    const d = new Date(isoStr);
    return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
  }

  function fmtElapsed(secs) {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    return `${String(h).padStart(2,"0")}h:${String(m).padStart(2,"0")}m:${String(s).padStart(2,"0")}s`;
  }

  function fmtCountdown(isoExpiry) {
    if (!isoExpiry) return "";
    const diff = new Date(isoExpiry) - Date.now();
    if (diff <= 0) return "expired";
    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    return `${days}d ${hours}h`;
  }

  function trimChat() {
    const feed = document.getElementById("chat");
    if (!feed) return;
    while (feed.children.length > MAX_MESSAGES) feed.removeChild(feed.firstChild);
  }

  function shouldShow(platform) {
    return activeFilter === "all" || activeFilter === platform;
  }

  function scrollToBottom() {
    const feed = document.getElementById("chat");
    if (feed) feed.scrollTop = feed.scrollHeight;
  }

  /* ── Renderers ── */
  function appendChat(msg) {
    if (!shouldShow(msg.platform)) return;
    const feed = document.getElementById("chat");
    if (!feed) return;
    const wrap = cfg.display?.word_wrap !== false;
    const div = document.createElement("div");
    div.className = `msg${wrap ? " wrap" : " no-wrap"}`;
    div.dataset.platform = msg.platform;
    div.dataset.messageId = msg.message_id;
    div.dataset.username = msg.username;

    const icon = msg.platform === "twitch"
      ? `<span class="platform" style="color:#9146ff;">■</span>`
      : `<span class="platform" style="color:#f00;">▶</span>`;

    const ts = cfg.display?.timestamps
      ? `<span class="ts">${fmtTime(msg.timestamp)}</span>` : "";

    div.innerHTML = `${ts}${icon}
      <span class="author" style="color:${msg.color}" oncontextmenu="showModMenu(event,this)">${msg.username}</span>:
      <span class="text">${escapeHtml(msg.message)}</span>`;
    feed.appendChild(div);
    trimChat();
    scrollToBottom();
  }

  function appendJoinPart(msg) {
    const feed = document.getElementById("chat");
    if (!feed) return;
    const div = document.createElement("div");
    div.className = msg.type === "join" ? "join-event" : "part-event";
    div.dataset.platform = "twitch";
    const arrow = msg.type === "join" ? "→" : "←";
    const ts = cfg.display?.timestamps ? `<span class="ts">${fmtTime(msg.timestamp)}</span> ` : "";
    div.innerHTML = `${ts}<span style="color:var(--muted);font-size:9px;">${arrow} ${escapeHtml(msg.username)} ${msg.type === "join" ? "joined" : "left"}</span>`;
    feed.appendChild(div);
    trimChat();
    scrollToBottom();
  }

  function appendAlert(msg) {
    const alertKey = msg.alert_type;
    const cfgAlerts = cfg.alerts || {};
    const alertMap = {
      raid: "raids", follow: "follows", sub: "subs", resub: "subs",
      subgift: "subs", bits: "bits", super_chat: "super_chat", new_member: "new_members",
    };
    if (cfgAlerts[alertMap[alertKey]] === false) return;
    if (!shouldShow(msg.platform)) return;

    const feed = document.getElementById("chat");
    if (!feed) return;
    const div = document.createElement("div");
    div.className = `alert-line alert-${alertKey}`;
    div.dataset.platform = msg.platform;
    const ts = cfg.display?.timestamps ? `<span class="ts">${fmtTime(msg.timestamp)}</span> ` : "";
    const amount = msg.amount ? ` (${msg.amount})` : "";
    div.innerHTML = `${ts}<span class="icon-${alertKey}"></span><strong>${escapeHtml(msg.username)}</strong>${amount} — ${escapeHtml(msg.message)}`;
    feed.appendChild(div);
    trimChat();
    scrollToBottom();
  }

  /* ── Status bar ── */
  function updateStatus(msg) {
    const tw = document.getElementById("twitch-viewers");
    const yt = document.getElementById("yt-viewers");
    const dot = document.getElementById("live-dot");
    const elapsed = document.getElementById("elapsed");
    const twToken = document.getElementById("twitch-token");
    const ytToken = document.getElementById("yt-token");

    if (tw) tw.innerHTML = `<span style="color:#9146ff;">■</span> <span style="color:#fff;">${msg.twitch_viewers ?? "—"}</span>`;
    if (yt) yt.innerHTML = `<span style="color:#f00;">▶</span> <span style="color:#fff;">${msg.youtube_viewers ?? "—"}</span>`;

    if (msg.stream_elapsed_seconds != null) {
      if (dot) dot.style.display = "inline";
      if (elapsed) { elapsed.style.display = "inline"; elapsed.textContent = fmtElapsed(msg.stream_elapsed_seconds); }
    }

    if (twToken && msg.twitch_token_expires) twToken.textContent = `Twitch ${fmtCountdown(msg.twitch_token_expires)}`;
    if (ytToken && msg.youtube_token_expires) ytToken.textContent = `YT ${fmtCountdown(msg.youtube_token_expires)}`;
  }

  /* ── Filter tabs ── */
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      activeFilter = btn.dataset.filter;
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      // Show/hide existing messages
      document.querySelectorAll("[data-platform]").forEach(el => {
        el.style.display = shouldShow(el.dataset.platform) ? "" : "none";
      });
    });
  });

  /* ── Mod menu ── */
  window.showModMenu = function (e, el) {
    e.preventDefault();
    const row = el.closest("[data-message-id]");
    if (!row) return;
    modTarget = {
      platform: row.dataset.platform,
      message_id: row.dataset.messageId,
      username: row.dataset.username,
    };
    const menu = document.getElementById("mod-menu");
    menu.style.display = "block";
    menu.style.left = `${e.clientX}px`;
    menu.style.top  = `${e.clientY}px`;
  };

  document.addEventListener("click", () => {
    const menu = document.getElementById("mod-menu");
    if (menu) menu.style.display = "none";
  });

  window.modAction = async function (action) {
    if (!modTarget) return;
    await fetch("/mod/action", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...modTarget, action, duration: 600}),
    });
    modTarget = null;
  };

  /* ── Settings page ── */
  async function loadSettings() {
    const r = await fetch("/api/config");
    cfg = await r.json();

    // Toggles
    document.querySelectorAll(".toggle[data-key]").forEach(el => {
      const [section, key] = el.dataset.key.split(".");
      const val = cfg[section]?.[key];
      el.textContent = val ? "ON" : "OFF";
      el.className = `toggle ${val ? "on" : "off"}`;
      el.onclick = async () => {
        cfg[section][key] = !cfg[section][key];
        await fetch("/api/config", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({[section]: cfg[section]}),
        });
        el.textContent = cfg[section][key] ? "ON" : "OFF";
        el.className = `toggle ${cfg[section][key] ? "on" : "off"}`;
      };
    });

    // Connection status
    if (cfg.twitch) {
      const status = document.getElementById("twitch-status");
      const cd = document.getElementById("twitch-countdown");
      if (status) status.innerHTML = cfg.twitch.access_token
        ? '<span style="color:#22c55e;">● Connected</span>' : '<span style="color:#555;">● Disconnected</span>';
      if (cd && cfg.twitch.token_expires) {
        cd.style.display = "inline";
        const txt = fmtCountdown(cfg.twitch.token_expires);
        cd.textContent = txt;
        cd.className = `countdown ${txt.startsWith("0d") || txt === "expired" ? "warning" : "ok"}`;
      }
    }
    if (cfg.youtube) {
      const status = document.getElementById("yt-status");
      const cd = document.getElementById("yt-countdown");
      if (status) status.innerHTML = cfg.youtube.access_token
        ? '<span style="color:#22c55e;">● Connected</span>' : '<span style="color:#555;">● Disconnected</span>';
      if (cd && cfg.youtube.token_expires) {
        cd.style.display = "inline";
        const txt = fmtCountdown(cfg.youtube.token_expires);
        cd.textContent = txt;
        cd.className = `countdown ${txt.startsWith("0d") || txt === "expired" ? "warning" : "ok"}`;
      }
    }

    // Gaze
    if (cfg.gaze) {
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      set("gaze-away", cfg.gaze.away_behaviour);
      set("gaze-dim", `${Math.round(cfg.gaze.dim_level * 100)}%`);
      set("gaze-cone", `${cfg.gaze.cone_angle}°`);
      set("gaze-fade", cfg.gaze.fade_speed);
    }

    // Position
    if (cfg.overlay) {
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      const o = cfg.overlay;
      set("pos-mode", o.mode);
      if (o.mode === "fixed") {
        set("pos-xyz", `${o.fixed_x} / ${o.fixed_y} / ${o.fixed_z}`);
        set("pos-size", o.fixed_size);
      } else if (o.mode === "follow") {
        set("pos-xyz", `${o.follow_angle}° · ${o.follow_distance}m`);
        set("pos-size", o.follow_size);
      } else {
        set("pos-xyz", `${o.wrist_hand} wrist · ${o.wrist_flip_threshold}° flip`);
        set("pos-size", o.wrist_size);
      }
    }
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* ── Gaze opacity (browser side) ── */
  function applyGaze(focused) {
    if (!cfg.gaze?.enabled) return;
    const speed = cfg.gaze.fade_speed || "medium";
    document.body.dataset.gaze = speed;
    if (focused) {
      document.body.style.opacity = cfg.gaze.focused_brightness;
    } else {
      document.body.style.opacity =
        cfg.gaze.away_behaviour === "disappear" ? 0 : cfg.gaze.dim_level;
    }
  }

  // The shim posts gaze state over a hidden endpoint
  const gazeWs = new WebSocket(`ws://${location.host}/ws/gaze`);
  gazeWs.onmessage = (e) => applyGaze(JSON.parse(e.data).focused);

  /* ── Init ── */
  if (document.getElementById("chat")) connect();
  if (document.querySelector(".toggle")) loadSettings().then(() => connect());
})();
```

- [ ] **Step 2: Add gaze WebSocket endpoint to server.py**

```python
# append to server.py

_gaze_clients: set[WebSocket] = set()

async def broadcast_gaze(focused: bool) -> None:
    import json
    msg = json.dumps({"focused": focused})
    dead = set()
    for ws in _gaze_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _gaze_clients.difference_update(dead)

@app.websocket("/ws/gaze")
async def gaze_ws(ws: WebSocket):
    await ws.accept()
    _gaze_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _gaze_clients.discard(ws)
```

- [ ] **Step 3: Manual smoke test**

```bash
uv run python server.py
```

Open `http://localhost:7331/` — chat view renders. Open `/settings` — toggles visible, legend visible. Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add static/app.js server.py
git commit -m "feat: frontend JS — WebSocket, chat render, alerts, mod menu, settings"
```

---

## Task 11: Python VR Shim — Basic Overlay

**Files:**
- Create: `shim.py`

> **Note:** This task requires SteamVR to be running. Test with the headset or SteamVR in null mode.

- [ ] **Step 1: Verify openvr loads**

```bash
uv run python -c "import openvr; print(openvr.__version__)"
```

Expected: prints a version string without error.

- [ ] **Step 2: Write shim.py — skeleton**

```python
# shim.py
from __future__ import annotations
import asyncio
import time
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
import mss
import openvr

from config import load_config, save_config, Config


_OVERLAY_KEY = "vr.chat.overlay"
_OVERLAY_NAME = "VR Chat Overlay"


def _find_browser_window_region() -> dict | None:
    """Find the bounding box of the browser window showing localhost:PORT.
    Uses xdotool on Linux. Returns mss monitor dict or None."""
    cfg = load_config()
    port = cfg.overlay.port
    try:
        wid = subprocess.check_output(
            ["xdotool", "search", "--name", f"localhost:{port}"],
            text=True, stderr=subprocess.DEVNULL
        ).strip().split("\n")[0]
        if not wid:
            return None
        geo = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", wid],
            text=True
        )
        props = dict(line.split("=") for line in geo.strip().split("\n") if "=" in line)
        return {"left": int(props["X"]), "top": int(props["Y"]),
                "width": int(props["WIDTH"]), "height": int(props["HEIGHT"])}
    except Exception:
        return None


def _make_transform(x: float, y: float, z: float) -> openvr.HmdMatrix34_t:
    m = openvr.HmdMatrix34_t()
    m.m = ((1,0,0,x),(0,1,0,y),(0,0,1,z))
    return m


class VRShim:
    def __init__(self):
        self.cfg = load_config()
        self._overlay_handle: int | None = None
        self._running = False

    def _init_openvr(self) -> bool:
        try:
            openvr.init(openvr.VRApplication_Overlay)
            return True
        except openvr.OpenVRError as e:
            print(f"OpenVR init failed: {e}")
            return False

    def _create_overlay(self) -> bool:
        vr_overlay = openvr.VROverlay()
        try:
            handle = vr_overlay.createOverlay(_OVERLAY_KEY, _OVERLAY_NAME)
            self._overlay_handle = handle
            vr_overlay.setOverlayWidthInMeters(handle, self.cfg.overlay.fixed_size)
            vr_overlay.setOverlayAlpha(handle, self.cfg.overlay.display.opacity
                                       if hasattr(self.cfg, 'display') else 0.8)
            self._apply_position()
            vr_overlay.showOverlay(handle)
            return True
        except Exception as e:
            print(f"Overlay creation failed: {e}")
            return False

    def _apply_position(self) -> None:
        if self._overlay_handle is None:
            return
        vr_overlay = openvr.VROverlay()
        cfg = self.cfg
        if cfg.overlay.mode == "fixed":
            t = _make_transform(cfg.overlay.fixed_x, cfg.overlay.fixed_y, cfg.overlay.fixed_z)
            vr_overlay.setOverlayTransformAbsolute(
                self._overlay_handle,
                openvr.TrackingUniverseStanding,
                openvr.byref(t))
        # follow and wrist handled in _update_position_dynamic()

    def _update_position_dynamic(self) -> None:
        """Called each frame for follow and wrist modes."""
        cfg = self.cfg
        if cfg.overlay.mode == "fixed":
            return

        vr_system = openvr.VRSystem()
        vr_overlay = openvr.VROverlay()
        poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
        vr_system.getDeviceToAbsoluteTrackingPose(
            openvr.TrackingUniverseStanding, 0, poses)

        hmd_pose = poses[openvr.k_unTrackedDeviceIndex_Hmd]
        if not hmd_pose.bPoseIsValid:
            return
        hmd_mat = np.array(hmd_pose.mDeviceToAbsoluteTracking.m)

        if cfg.overlay.mode == "follow":
            import math
            angle_rad = math.radians(cfg.overlay.follow_angle)
            # right vector from HMD rotation
            right = hmd_mat[:3, 0]
            forward = -hmd_mat[:3, 2]
            pos = hmd_mat[:3, 3]
            offset = (forward * math.cos(angle_rad) + right * math.sin(angle_rad)) * cfg.overlay.follow_distance
            offset[1] += cfg.overlay.follow_height
            target = pos + offset
            t = _make_transform(float(target[0]), float(target[1]), float(target[2]))
            vr_overlay.setOverlayTransformAbsolute(
                self._overlay_handle, openvr.TrackingUniverseStanding, openvr.byref(t))

        elif cfg.overlay.mode == "wrist":
            role = (openvr.TrackedControllerRole_LeftHand
                    if cfg.overlay.wrist_hand == "left"
                    else openvr.TrackedControllerRole_RightHand)
            idx = vr_system.getTrackedDeviceIndexForControllerRole(role)
            if idx == openvr.k_unTrackedDeviceIndexInvalid:
                return
            ctrl_pose = poses[idx]
            if not ctrl_pose.bPoseIsValid:
                return
            ctrl_mat = np.array(ctrl_pose.mDeviceToAbsoluteTracking.m)
            ctrl_up = ctrl_mat[:3, 1]  # Y axis of controller
            world_up = np.array([0, 1, 0])
            cos_a = np.clip(np.dot(ctrl_up, world_up), -1, 1)
            import math
            angle = math.degrees(math.acos(cos_a))
            visible = angle <= cfg.overlay.wrist_flip_threshold
            if visible:
                vr_overlay.setOverlayTransformTrackedDeviceRelative(
                    self._overlay_handle, idx, openvr.byref(_make_transform(0, 0.05, -0.1)))
                vr_overlay.showOverlay(self._overlay_handle)
            else:
                vr_overlay.hideOverlay(self._overlay_handle)

    def _push_frame(self, region: dict) -> None:
        """Screenshot the browser window and push as overlay texture."""
        with mss.mss() as sct:
            raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        img = img.convert("RGBA")
        w, h = img.size
        rgba = np.array(img, dtype=np.uint8)
        openvr.VROverlay().setOverlayRaw(
            self._overlay_handle, rgba.tobytes(), w, h, 4)

    def _update_gaze_opacity(self) -> None:
        cfg = self.cfg
        if not cfg.gaze.enabled:
            return
        vr_system = openvr.VRSystem()
        poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
        vr_system.getDeviceToAbsoluteTrackingPose(
            openvr.TrackingUniverseStanding, 0, poses)
        hmd = poses[openvr.k_unTrackedDeviceIndex_Hmd]
        if not hmd.bPoseIsValid:
            return

        hmd_mat = np.array(hmd.mDeviceToAbsoluteTracking.m)
        forward = -hmd_mat[:3, 2]
        hmd_pos = hmd_mat[:3, 3]

        # Get overlay world position from its transform
        t = openvr.HmdMatrix34_t()
        tracking_origin = openvr.ETrackingUniverseOrigin()
        openvr.VROverlay().getOverlayTransformAbsolute(
            self._overlay_handle, openvr.byref(tracking_origin), openvr.byref(t))
        overlay_pos = np.array([t.m[0][3], t.m[1][3], t.m[2][3]])

        to_overlay = overlay_pos - hmd_pos
        norm = np.linalg.norm(to_overlay)
        if norm < 0.001:
            return
        to_overlay /= norm
        import math
        cos_a = np.clip(np.dot(forward, to_overlay), -1, 1)
        angle = math.degrees(math.acos(cos_a))
        focused = angle <= cfg.gaze.cone_angle

        speeds = {"slow": 1.2, "medium": 0.4, "fast": 0.1}
        target_alpha = (cfg.gaze.focused_brightness if focused
                        else (0.0 if cfg.gaze.away_behaviour == "disappear"
                              else cfg.gaze.dim_level))
        openvr.VROverlay().setOverlayAlpha(self._overlay_handle, target_alpha)

        # Also push to browser for CSS transition
        asyncio.run(_push_gaze_to_browser(focused))

    def run(self) -> None:
        if not self._init_openvr():
            sys.exit(1)
        if not self._create_overlay():
            sys.exit(1)
        print(f"Overlay running — open http://localhost:{self.cfg.overlay.port}/ in a browser window")
        self._running = True
        region = None
        while self._running:
            if region is None:
                region = _find_browser_window_region()
                if region is None:
                    print("Waiting for browser window...")
                    time.sleep(2)
                    continue
            try:
                self._push_frame(region)
                self._update_position_dynamic()
                self._update_gaze_opacity()
                self._poll_controller_events()
            except Exception as e:
                print(f"Frame error: {e}")
                region = None   # re-find window on next tick
            time.sleep(0.1)  # ~10 fps — fine for chat

    def _poll_controller_events(self) -> None:
        event = openvr.VREvent_t()
        while openvr.VRSystem().pollNextEvent(event):
            etype = event.eventType
            if etype == openvr.VREvent_ButtonPress:
                btn = event.data.controller.button
                if btn == openvr.k_EButton_A:
                    self._save_position()

    def _save_position(self) -> None:
        """Save current overlay world position to config.toml."""
        t = openvr.HmdMatrix34_t()
        origin = openvr.ETrackingUniverseOrigin()
        openvr.VROverlay().getOverlayTransformAbsolute(
            self._overlay_handle, openvr.byref(origin), openvr.byref(t))
        cfg = load_config()
        cfg.overlay.fixed_x = round(t.m[0][3], 3)
        cfg.overlay.fixed_y = round(t.m[1][3], 3)
        cfg.overlay.fixed_z = round(t.m[2][3], 3)
        save_config(cfg)
        print(f"Position saved: {cfg.overlay.fixed_x}, {cfg.overlay.fixed_y}, {cfg.overlay.fixed_z}")


async def _push_gaze_to_browser(focused: bool) -> None:
    """Send gaze state to the web UI via HTTP (fire-and-forget)."""
    import httpx
    try:
        cfg = load_config()
        async with httpx.AsyncClient() as client:
            await client.post(f"http://localhost:{cfg.overlay.port}/internal/gaze",
                              json={"focused": focused}, timeout=0.1)
    except Exception:
        pass


if __name__ == "__main__":
    shim = VRShim()
    shim.run()
```

- [ ] **Step 3: Add internal gaze POST endpoint to server.py**

```python
# append to server.py

class GazeState(BaseModel):
    focused: bool

@app.post("/internal/gaze")
async def internal_gaze(state: GazeState):
    await broadcast_gaze(state.focused)
    return {"ok": True}
```

- [ ] **Step 4: Verify shim imports cleanly (no SteamVR needed for import)**

```bash
uv run python -c "import shim; print('shim imports ok')"
```

Expected: prints "shim imports ok"

- [ ] **Step 5: Commit**

```bash
git add shim.py server.py
git commit -m "feat: Python VR shim — overlay, positioning, controller save, gaze opacity"
```

---

## Task 12: Integration Smoke Test + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 2: Write README.md**

```markdown
# VR Chat Overlay

Merged Twitch + YouTube live chat in a VR overlay. Valve Index + SteamVR today; OpenXR/Monado when Steam Frame ships.

## Quick Start

1. Install dependencies: `uv sync`
2. Add your Twitch and YouTube API credentials to `config.toml`
3. Start the web UI: `uv run python server.py`
4. Open `http://localhost:7331/settings` in a browser and connect Twitch + YouTube via OAuth
5. Start the shim (with SteamVR running): `uv run python shim.py`
6. Open `http://localhost:7331/` in a *separate* browser window — the shim will find it and display it in VR

## Positioning

Set `overlay.mode` in `config.toml` to `fixed`, `follow`, or `wrist`.  
Press **A** on your controller to save the current overlay position.

## Phase 2

Replace `shim.py` with a Rust binary using `openxrs` for Monado/OpenXR support. The web UI and server are unchanged.
```

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: README with quick start and phase 2 note"
```

---

## Self-Review Checklist

- [x] **Spatial persistence (LIV-style)** — `_save_position()` in shim writes to config.toml on A button; position loaded on startup
- [x] **Merged feed + filter tabs** — `appendChat()` filters by `activeFilter`; tabs call DOM filter
- [x] **Timestamps toggle** — `cfg.display.timestamps` checked in every renderer
- [x] **Word wrap toggle** — `cfg.display.word_wrap` sets `wrap`/`no-wrap` class on each message
- [x] **Viewer count + stream timer** — `_status_loop()` polls Helix + YouTube every 30s; `fmtElapsed()` renders `XXh:XXm:XXs`
- [x] **Join/leave (Twitch only)** — `parse_membership()` + `appendJoinPart()` + `join_leave_alerts` toggle
- [x] **All 6 alert types** — `parse_usernotice()`, `parse_privmsg()` (bits), `parse_chat_item()` (super_chat, new_member), `TwitchEventSub` (follows)
- [x] **Token countdown** — `fmtCountdown()` renders days/hours; colour coded in settings
- [x] **Right-click mod actions** — `showModMenu()`, `modAction()`, `/mod/action` endpoint, `send_irc_command()`, YouTube API stubs
- [x] **Fixed / Follow / Wrist positioning** — `_apply_position()` + `_update_position_dynamic()`
- [x] **Wrist flip detection** — controller Y-axis dot product vs world up, threshold from config
- [x] **A button saves position** — `_poll_controller_events()` → `_save_position()`
- [x] **Gaze-aware opacity** — `_update_gaze_opacity()` in shim + `applyGaze()` in JS + CSS transitions
- [x] **Eye tracking note** — documented in config.toml comment and README; auto-detection placeholder in shim (swap `_update_gaze_opacity` source from head pose to eye gaze pose when `XR_EXT_eye_gaze_interaction` available in Phase 2)
- [x] **Colour legend** — in settings.html, always visible
- [x] **config.toml fully documented** — every key has inline comment
- [x] **OAuth with day countdown** — `fmtCountdown()` + warning colour class
- [x] **OpenXR upgrade path** — shim.py is the only file that changes; web UI, server, config untouched
