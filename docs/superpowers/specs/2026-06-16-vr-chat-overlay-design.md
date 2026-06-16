# VR Chat Overlay — Design Spec
**Date:** 2026-06-16  
**Status:** Approved for implementation planning

---

## Overview

A VR overlay that shows Twitch and YouTube live chat in a single window, floating in the user's play space. Built as a web app (FastAPI) with a Python OpenVR shim for Phase 1, swappable to a Rust OpenXR shim in Phase 2 when Steam Frame ships.

---

## Target Hardware

**Primary:** Valve Index (SteamVR, Lighthouse tracking)  
**Phase 1 compatible:** HTC Vive/Pro, Pimax (SteamVR mode), Quest via Air Link/Link, WMR via SteamVR  
**Phase 2 compatible (OpenXR):** All of the above + Quest native, Pico 4/Pro, PSVR2 PC mode, Monado/Linux, Steam Frame

---

## Architecture

Three components, all talking through `config.toml`:

### 1. FastAPI Web UI (`server.py`)
- Serves the chat interface at `localhost:PORT`
- Connects to Twitch IRC/WebSocket and YouTube Live Chat API
- Forwards events to the browser via WebSocket
- Handles OAuth flows for both platforms
- Exposes a `/settings` page for full configuration
- Executes mod actions (Twitch IRC commands, YouTube API calls)

### 2. Python OpenVR Shim (`shim.py`)
- Creates an OpenVR overlay window pointing at `localhost:PORT`
- Reads position/mode from `config.toml` on startup
- Handles controller input (grab, reposition, save, cog toggle)
- Calculates head-gaze (or reads OpenXR eye gaze if available) for opacity
- Writes updated position back to `config.toml` on save
- **Swappable:** replace with Rust binary in Phase 2, no other changes needed

### 3. `config.toml`
- Single source of truth for all persistent state
- Every key has an inline comment explaining its purpose
- Sections: `[twitch]`, `[youtube]`, `[overlay]`, `[display]`, `[alerts]`, `[gaze]`
- Human-editable without documentation; safe defaults for all keys

---

## Config Structure

```toml
# VR Chat Overlay — configuration file
# Edit any value here; changes take effect on next app start.

[twitch]
channel = "yourchannel"          # Your Twitch channel name
access_token = ""                # Set automatically via OAuth — do not edit
token_expires = ""               # ISO timestamp; shown as countdown in UI

[youtube]
stream_id = "auto"               # "auto" polls the YouTube API every 60s for your active live stream; paste a specific stream ID to pin it
access_token = ""                # Set automatically via OAuth — do not edit
token_expires = ""               # ISO timestamp; shown as countdown in UI

[overlay]
mode = "fixed"                   # "fixed" | "follow" | "wrist"

# Fixed mode — world-space anchor point
fixed_x = 0.0
fixed_y = 1.4
fixed_z = -1.2
fixed_rot_x = 0.0
fixed_rot_y = 0.0
fixed_rot_z = 0.0
fixed_size = 0.6                 # Width in meters

# Follow mode — offset from player head
follow_angle = 30.0              # Degrees to the right of forward
follow_distance = 1.2            # Meters from head
follow_height = -0.2             # Vertical offset in meters
follow_size = 0.6

# Wrist dock mode
wrist_hand = "left"              # "left" | "right"
wrist_flip_threshold = 45.0      # Degrees — wrist angle that shows the overlay
wrist_size = 0.3

[display]
opacity = 0.8                    # Overall overlay opacity (0.0–1.0)
timestamps = true                # Show message timestamps
viewer_count_bar = true          # Show viewer count in status bar
join_leave_alerts = true         # Show join/leave events in chat (Twitch only)
default_filter = "all"           # "all" | "twitch" | "youtube"

[alerts]
# Each alert type can be toggled independently
raids = true                     # Twitch only
follows = true                   # Twitch only
subs = true                      # Twitch only (includes resubs and gifted)
bits = true                      # Twitch only
super_chat = true                # YouTube only
new_members = true               # YouTube only (channel memberships)

[gaze]
enabled = true                   # Brighten on gaze, dim when looking away
# Gaze source is auto-detected: eye tracking if available, head-gaze fallback
focused_brightness = 1.0         # Brightness when looking at overlay (0.0–1.0)
away_behaviour = "dim"           # "dim" | "disappear"
dim_level = 0.3                  # Brightness when looking away (0.0–1.0)
cone_angle = 35.0                # Degrees — how directly you must face it to trigger
fade_speed = "medium"            # "slow" | "medium" | "fast"
```

---

## Chat Display

- **Single merged feed** showing Twitch and YouTube messages chronologically
- **Filter tabs** at top: All / Twitch / YouTube
- **Platform indicator** on each message: `■` (purple) for Twitch, `▶` (red) for YouTube
- **Timestamps** — toggleable, shown in muted colour before each message
- **Right-click a message** → mod action menu (ban / timeout / delete)

### Join / Leave Notifications (Twitch only)
Appear inline in the chat feed, muted green for join, muted red for leave:
```
12:03  → xX_Gamer joined
12:06  ← OldViewer left
```

### Event Alerts (inline, colour-coded)
Appear as highlighted lines with a left border flash:

| Colour | Icon | Event | Platform |
|--------|------|-------|----------|
| Amber | ⚡ | Raid | Twitch |
| Green | ★ | Follow | Twitch |
| Purple | ♦ | Sub / Resub / Gifted sub | Twitch |
| Yellow | ⬡ | Bits / Cheer | Twitch |
| Orange | $ | Super Chat | YouTube |
| Green | ★ | New Member | YouTube |

Each alert type independently toggleable in the cog and web UI.

### Status Bar (bottom of overlay)
```
■ Twitch  1,204 viewers    ▶ YouTube  847 viewers    Twitch 2d 14h · YT 6d 3h
```
Shows live viewer counts (polled every ~30s) and token expiry countdowns.

---

## Colour Legend
Displayed on the web UI settings page so users never have to guess:

- **Amber ⚡** — Raid incoming
- **Green ★** — Follow / YouTube member
- **Purple ♦** — Sub or gifted sub
- **Yellow ⬡** — Bits / Cheers
- **Orange $** — YouTube Super Chat

---

## Positioning Modes

### Fixed
Overlay anchored at a world-space position. Position saved to `config.toml` via A button or web UI. Best for seated/stationary games (Elite: Dangerous).

### Follow
Overlay drifts with the player, maintaining a constant offset from head direction. Angle, distance, and height offset configurable. Best for room-scale/walking games.

### Wrist Dock
Overlay attached to left or right controller. Detects wrist flip via controller rotation (configurable threshold). Overlay appears when palm faces the user, hides when wrist is down. Smaller default size (0.3m). Works in any game.

**Switching modes:** Available in the cog quick settings and web UI. Each mode remembers its own position/size independently.

---

## Controller Interactions

| Input | Action |
|-------|--------|
| Trigger (hold) on overlay edge | Grab and drag to reposition |
| A button | Save current position to config.toml |
| Trigger on message | Open mod action menu |
| B button or cog icon | Toggle quick settings panel |

---

## Gaze-Aware Opacity

The overlay brightens when the user looks at it and dims (or disappears) when they look away.

**Gaze source — auto-detected at startup:**
- Eye tracking (`XR_EXT_eye_gaze_interaction`) if headset supports it (Quest Pro, Pico 4 Pro, PSVR2, Varjo, Tobii Eye Tracker 5)
- Head-gaze fallback for all other headsets (Index, standard Quest, Vive, etc.) — uses HMD forward direction within a configurable cone angle

Gaze source shown in the web UI settings panel. No manual configuration needed.

**Controls:** enabled/disabled, focused brightness, away behaviour (dim or disappear), dim level, cone angle, fade speed.

---

## Authentication

OAuth browser flow for both platforms:
1. User clicks "Connect Twitch" or "Connect YouTube" in web UI settings
2. Browser opens the platform's OAuth consent page
3. Token saved to `config.toml` on success
4. **Day countdown timer** shown in status bar and settings page per platform
5. **Manual renewal only** — user clicks Reconnect when timer gets low

---

## Web UI Pages

### `/` — Chat view
Full chat feed with filter tabs, status bar, and cog link.

### `/settings` — Settings page
Two-column layout:
- **Left:** Connections (OAuth status + countdown + Reconnect), Channels, Display toggles
- **Right:** Alert toggles, Colour legend, Overlay position (per mode)

---

## Moderation

**Twitch:** IRC commands (`/ban`, `/timeout`, `/delete`) sent via the existing IRC connection.  
**YouTube:** YouTube Live Chat API (`liveChatMessages.delete`, `liveChatBans.insert`).  
**Trigger:** Right-click (or controller trigger) on any chat message → context menu with available actions.

---

## Phase 2 — Rust Shim

When Steam Frame / Monado/OpenXR support is needed:
- Replace `shim.py` with a Rust binary using `openxrs` crate
- Binary reads the same `config.toml`, opens the same `localhost:PORT` URL
- Web UI, FastAPI backend, auth, moderation — untouched
- Eye tracking auto-detection moves to the Rust shim via `XR_EXT_eye_gaze_interaction`

---

## Out of Scope (Phase 1)

- Bot configuration / bot management UI (web UI links to external tools)
- Sound/audio alerts for events
- Chat input / sending messages from the overlay
- Clip creation or stream management
- Android / standalone headset support (Phase 2)
