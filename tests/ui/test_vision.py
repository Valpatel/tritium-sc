#!/usr/bin/env python3
"""TRITIUM-SC Comprehensive UI Audit Suite.

Sweeps every view at mobile/tablet/desktop resolutions using multiple local
vision models sequentially to produce a detailed report of UI quality,
responsive design issues, and element inventory.

Architecture:
  1. Take ALL screenshots upfront (fast, ~5s each)
  2. Run each model pass across all screenshots, one model at a time
  3. Explicitly unload each model before loading the next
  4. Generate combined markdown + JSON report

This design runs models one-at-a-time to stay within GPU memory.  On a GB10
with 128 GB unified memory, even the 72B model fits — we just need patience.

Model tiers:
  standard  — llava:7b (vision) + glm-ocr:latest (OCR)
  deep      — + qwen2.5vl (auto-sized: 3b/7b/32b based on RAM)
  ultra     — + qwen2.5vl:72b  (needs ~50 GB, expect slow)

Usage:
    python3 tests/ui/test_vision.py                       # Standard audit
    python3 tests/ui/test_vision.py --deep                # Add deep vision pass
    python3 tests/ui/test_vision.py --ultra               # Add 72B ultra pass
    python3 tests/ui/test_vision.py --view war            # Single view
    python3 tests/ui/test_vision.py --resolution desktop  # Single resolution
    python3 tests/ui/test_vision.py --quick               # Desktop only, llava only
    python3 tests/ui/test_vision.py --setup               # Download models and exit
    python3 tests/ui/test_vision.py --list                # List views and exit

Requires:
    - Node.js with Playwright (tests/e2e/node_modules/playwright/)
    - Ollama running locally
    - opencv-python-headless, numpy, requests

See docs/UI-VIEWS.md for the design-intent spec that these prompts derive from.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
E2E_DIR = PROJECT_ROOT / "tests" / "e2e"
NODE_MODULES = E2E_DIR / "node_modules"

# Minimum non-black pixel ratio to consider a screenshot non-blank
MIN_CONTENT_RATIO = 0.05

# ---------------------------------------------------------------------------
# Resolution profiles
# ---------------------------------------------------------------------------

RESOLUTIONS = {
    "mobile":  {"width": 375,  "height": 812,  "scale": 2, "label": "Mobile (375x812 @2x)"},
    "tablet":  {"width": 768,  "height": 1024, "scale": 1, "label": "Tablet (768x1024)"},
    "desktop": {"width": 1920, "height": 1080, "scale": 1, "label": "Desktop (1920x1080)"},
}

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

# qwen2.5vl sizes: 3b=3.2GB, 7b=6GB, 32b=21GB, 72b=49GB
QWEN_VL_SIZES = {
    "small":  "qwen2.5vl:3b",   # 3.2 GB — runs on anything
    "medium": "qwen2.5vl:7b",   # 6.0 GB — good default
    "large":  "qwen2.5vl:32b",  # 21  GB — needs 32+ GB
    "ultra":  "qwen2.5vl:72b",  # 49  GB — needs 64+ GB
}


def get_system_memory_gb() -> float:
    """Get total system memory in GB from /proc/meminfo."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return 0.0


def pick_deep_model() -> str:
    """Choose the best qwen2.5vl size for this system's memory."""
    mem = get_system_memory_gb()
    if mem >= 96:
        return QWEN_VL_SIZES["large"]   # 32b on 96+ GB
    if mem >= 32:
        return QWEN_VL_SIZES["medium"]  # 7b on 32+ GB
    return QWEN_VL_SIZES["small"]       # 3b on anything


# ---------------------------------------------------------------------------
# View definitions — keyboard shortcut + settle time + detailed audit prompts
#
# Each audit_prompt is derived from docs/UI-VIEWS.md.  When the UI changes,
# update UI-VIEWS.md FIRST, then update the prompt here to match.
# See docs/UI-VIEWS.md § "Prompt Engineering Methodology" for the template.
# ---------------------------------------------------------------------------

VIEWS = {
    "grid": {
        "shortcut": "g",
        "settle_ms": 2500,
        "label": "Camera Grid",
        "description": "Grid of camera feed thumbnails — the main surveillance view",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Camera Grid View:\n"
            "This view SHOULD show a CSS Grid of camera feed tiles. The default layout is 2x2 "
            "(4 tiles). Each tile SHOULD have:\n"
            "- A 16:9 aspect-ratio video feed image (or dark placeholder if no camera)\n"
            "- A gradient overlay at the bottom with the channel name (e.g. 'CH01 - Front Camera') "
            "in CYAN (#00f0ff) uppercase monospace text (0.75rem)\n"
            "- A green (#05ffa1) status indicator showing 'LIVE' or a timestamp (0.625rem)\n"
            "- On hover: cyan border glow. When selected: magenta border glow\n\n"
            "The grid container SHOULD have 8px gaps between tiles, 16px padding. "
            "Background is near-black (#0a0a0f). Tiles have dark (#12121a) backgrounds "
            "with subtle cyan borders (rgba(0,240,255,0.2)).\n\n"
            "At the top of the page there SHOULD be a view-controls toolbar with view "
            "switching buttons (GRID, PLAYER, ZONES, etc.) and a grid size dropdown "
            "selector (1x1, 2x2, 3x3).\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which described elements are actually visible?\n"
            "2. MISSING: Which described elements are NOT visible or cannot be found?\n"
            "3. WRONG: Which elements look different from the spec (wrong color, wrong "
            "   position, wrong size, wrong text)?\n"
            "4. BROKEN: Any overlapping elements, truncated text, clipped content, "
            "   overflow issues, or rendering glitches?\n"
            "5. EXTRA: Any unexpected elements not in the spec?\n\n"
            "Be precise about locations (top-left, center, bottom-right, etc.)."
        ),
    },
    "player": {
        "shortcut": "p",
        "settle_ms": 2500,
        "label": "Video Player",
        "description": "Video playback view with timeline and channel selector",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Video Player View:\n"
            "This view SHOULD show a video playback interface with these elements:\n"
            "- MAIN AREA: A large HTML5 video player with native controls, filling most "
            "  of the screen. If no video is loaded, it should show a dark empty area.\n"
            "- CONTROLS BAR: Below the video, a horizontal strip containing:\n"
            "  - Play/Pause button (triangle/pause icon)\n"
            "  - 'DETECTIONS' toggle button (cyan button style)\n"
            "  - Current time and duration labels (HH:MM:SS format)\n"
            "- TIMELINE: A clickable progress bar below controls, with detection event "
            "  markers shown as colored dots/lines on the timeline\n"
            "- An annotation overlay canvas for drawing YOLO bounding boxes\n\n"
            "The color scheme is cyberpunk dark: near-black background (#0a0a0f), "
            "cyan (#00f0ff) for primary UI elements, magenta (#ff2a6d) for highlights, "
            "monospace font (JetBrains Mono).\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which described elements are actually visible?\n"
            "2. MISSING: Which described elements are NOT visible?\n"
            "3. WRONG: Elements that look different from spec?\n"
            "4. BROKEN: Overlapping, truncated, clipped, or glitched elements?\n"
            "5. EXTRA: Any unexpected elements?\n\n"
            "Be precise about locations and sizes."
        ),
    },
    "3d": {
        "shortcut": "d",
        "settle_ms": 4000,
        "label": "3D Camera Grid",
        "description": "Three.js 3D visualization of camera positions and property layout",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — 3D Camera Grid View:\n"
            "This view SHOULD show a full-screen Three.js WebGL canvas with:\n"
            "- A 3D scene with camera position markers and a property layout grid\n"
            "- An overlay label '3D CAMERA GRID' in cyan text (top-left corner, panel style)\n"
            "- OrbitControls: click-drag to orbit, scroll to zoom, right-drag to pan\n"
            "- Camera objects positioned in 3D space representing physical camera locations\n"
            "- The background should be dark/space-like (Three.js default or custom)\n\n"
            "The canvas takes the full view-content area. The overlay is absolutely "
            "positioned above the canvas.\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Is the 3D canvas rendering (not blank)? Is the overlay visible?\n"
            "2. MISSING: Is the scene empty? Are camera markers missing?\n"
            "3. WRONG: Does the 3D scene look corrupted or incorrect?\n"
            "4. BROKEN: Is the canvas covering the overlay? Any rendering artifacts?\n"
            "5. EXTRA: Any unexpected UI elements over the canvas?"
        ),
    },
    "zones": {
        "shortcut": "z",
        "settle_ms": 2500,
        "label": "Zone Manager",
        "description": "Zone definition and alerting configuration view",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Zone Manager View:\n"
            "This view SHOULD show a 2-column layout:\n\n"
            "LEFT PANEL (300px wide, scrollable):\n"
            "- Header: 'MONITORING ZONES' in cyan text\n"
            "- A '+ DRAW' button for creating new zones\n"
            "- A list of zone items, each showing: zone name (colored by type), "
            "  type badge (activity/entry_exit/tripwire), event count, last event time\n"
            "- Zone type colors: activity=cyan, entry_exit=green, tripwire=magenta\n\n"
            "RIGHT PANEL (fills remaining space):\n"
            "- A canvas area for drawing/viewing zone polygons\n"
            "- If no camera selected: placeholder text 'SELECT A CAMERA' with a pin icon\n"
            "- If camera selected: camera feed background with drawn zone polygons\n\n"
            "BOTTOM PANEL (max 200px):\n"
            "- Header: 'ZONE EVENTS' in magenta text with event count\n"
            "- Scrollable list of zone events with timestamps and target types\n\n"
            "Background: near-black (#0a0a0f). Panels have dark backgrounds with "
            "cyan borders. Text in monospace.\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which described elements are actually visible?\n"
            "2. MISSING: Which described elements are NOT visible?\n"
            "3. WRONG: Elements that look different from spec?\n"
            "4. BROKEN: Overlapping, truncated, clipped, or glitched elements?\n"
            "5. LAYOUT: Does the 2-column layout hold at this resolution, "
            "   or do panels stack/collapse?"
        ),
    },
    "targets": {
        "shortcut": "t",
        "settle_ms": 2500,
        "label": "Target Tracker",
        "description": "Real-time target tracking with unified tracker display",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Target Tracker View:\n"
            "This view SHOULD show a vertically-stacked layout:\n\n"
            "TOP: Filter & Type Tabs\n"
            "- Two toggle buttons: 'PEOPLE' and 'VEHICLES' (with icons)\n"
            "- Channel filter dropdown and date filter\n"
            "- 'REFRESH' button\n"
            "- Target count display\n\n"
            "MIDDLE: Target Gallery\n"
            "- A CSS Grid of target cards, auto-filling columns (min 180px each)\n"
            "- Each card SHOULD have: square thumbnail image, channel label (cyan), "
            "  confidence percentage, timestamp\n"
            "- If no targets: empty state with magnifying glass icon, "
            "  'NO TARGETS FOUND' text, and hint to run AI analysis\n\n"
            "BOTTOM (conditional): Target Detail Panel\n"
            "- Shows when a target is clicked: 200x200 image, target title (cyan), "
            "  metadata, LABEL/FIND SIMILAR/CLOSE buttons\n\n"
            "Color scheme: dark background, cyan for primary text and people, "
            "magenta/yellow for vehicles, monospace font.\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which described elements are actually visible?\n"
            "2. MISSING: Which described elements are NOT visible?\n"
            "3. WRONG: Elements that look different from spec?\n"
            "4. BROKEN: Overlapping, truncated, clipped, or glitched elements?\n"
            "5. DATA: Is the gallery populated with target cards, or showing empty state?"
        ),
    },
    "assets": {
        "shortcut": "a",
        "settle_ms": 3000,
        "label": "Asset Manager",
        "description": "Operational assets with tactical map, camera feeds, and task assignment",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Asset Manager View:\n"
            "This is a complex 2-column layout:\n\n"
            "LEFT PANEL (350px, scrollable):\n"
            "- Header: 'OPERATIONAL ASSETS' in cyan bold, with '+ REGISTER' button\n"
            "- Asset cards, each showing: type icon (car/helicopter/satellite emoji), "
            "  asset name (cyan), status badge (colored: active=green, tasked=yellow, "
            "  offline=gray), asset ID (monospace muted), battery icon + percentage, "
            "  current task type (yellow)\n"
            "- Summary at bottom: Total count (cyan), Active count (green), "
            "  Offline count (magenta)\n\n"
            "RIGHT PANEL:\n"
            "- STAT BOXES (4-column grid): BATTERY, ORDNANCE, POSITION, HEADING\n"
            "  Each box has a label and large value\n"
            "- 2-column sub-grid:\n"
            "  - Left: 'ONBOARD CAMERA' feed (img or fallback text)\n"
            "  - Right: 'TACTICAL MAP' canvas showing:\n"
            "    - Grid lines (30px, dark cyan)\n"
            "    - Property outline (cyan rectangle, center)\n"
            "    - Asset markers: friendly=green circles, hostile=magenta diamonds, "
            "      unknown=yellow squares\n"
            "    - Waypoint paths (dashed cyan), dispatch arrows (magenta dashed)\n"
            "    - Battery bars (green-to-red gradient)\n"
            "    - Home marker (dashed cyan square + 'HOME' label)\n"
            "- TASK ASSIGNMENT section:\n"
            "  - Header: 'TASK ASSIGNMENT' in magenta\n"
            "  - 8 task buttons in a grid: PATROL, TRACK, ENGAGE, LOITER, "
            "    INVESTIGATE, RECALL, REARM, CANCEL\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which described elements are actually visible?\n"
            "2. MISSING: Which described elements are NOT visible?\n"
            "3. WRONG: Elements that look different from spec?\n"
            "4. BROKEN: Overlapping, truncated, clipped, or glitched elements?\n"
            "5. MAP: Does the tactical map show unit markers? Are they distinguishable?"
        ),
    },
    "analytics": {
        "shortcut": "n",
        "settle_ms": 2500,
        "label": "Analytics",
        "description": "Detection analytics, charts, and statistics dashboard",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Analytics Dashboard:\n"
            "This view SHOULD show a scrollable dashboard with these sections:\n\n"
            "HEADER:\n"
            "- Title: 'DETECTION ANALYTICS' in cyan (h2)\n"
            "- Period selector dropdown: '7 Days', '14 Days', '30 Days'\n"
            "- 'REFRESH' button\n\n"
            "STATS ROW (4-column grid of stat boxes):\n"
            "- 'TOTAL DETECTIONS' — large cyan number\n"
            "- 'PEOPLE DETECTED' — large magenta number\n"
            "- 'VEHICLES DETECTED' — large yellow number\n"
            "- 'PEAK HOUR' — large green text\n\n"
            "CHARTS (2-column grid):\n"
            "- Left: 'Daily Detections' — stacked bar chart (magenta=people, yellow=vehicles)\n"
            "- Right: 'Hourly Distribution' — 24-bar chart in cyan\n\n"
            "RECENT TARGETS:\n"
            "- Header: 'RECENT TARGETS (TODAY)' in magenta, with 'VIEW ALL' link\n"
            "- Gallery grid of target thumbnails (100px min columns)\n\n"
            "CHANNEL BREAKDOWN:\n"
            "- Per-channel stat boxes: channel name (cyan), count, progress bar\n\n"
            "Note: If no detection data exists, numbers may show '0' and charts may "
            "be empty, which is expected.\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which described sections are actually visible?\n"
            "2. MISSING: Which sections are NOT visible?\n"
            "3. WRONG: Elements that look different from spec?\n"
            "4. BROKEN: Overlapping, truncated, or clipped elements?\n"
            "5. DATA: Are stats populated or all zeros? Are charts rendered or empty?"
        ),
    },
    "amy": {
        "shortcut": "y",
        "settle_ms": 4000,
        "label": "Amy AI Commander",
        "description": "AI Commander dashboard with video feed, thoughts, chat, sensorium",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Amy AI Commander Dashboard:\n"
            "This is a dense multi-panel interface arranged in rows:\n\n"
            "TOP-LEFT: PRIMARY OPTICS\n"
            "- Panel header: 'PRIMARY OPTICS' in cyan\n"
            "- Tab buttons: 'LIVE' and 'GALLERY'\n"
            "- Video node label (e.g. 'BCC950' or '--')\n"
            "- Either an MJPEG video feed image, or placeholder: circle icon + "
            "  'NO CAMERA CONNECTED' + 'Waiting for sensor node...'\n\n"
            "TOP-RIGHT: COMMANDER STATUS\n"
            "- Panel header: 'COMMANDER STATUS'\n"
            "- State badge (colored by state: idle/thinking/speaking)\n"
            "- 6 stat boxes: STATE, MOOD, THINKING (ACTIVE/SUPPRESSED), "
            "  NODES (count), PAN (degrees), TILT (degrees)\n"
            "- 'SENSOR NODES' section with node list\n"
            "- 'COMMANDS' section with 6 buttons: SCAN, OBSERVE, ATTEND, IDLE, "
            "  AUTO-CHAT, NOD\n\n"
            "BOTTOM-LEFT: INNER THOUGHTS\n"
            "- Panel header: 'INNER THOUGHTS' with count\n"
            "- Scrollable stream of thought entries, each with:\n"
            "  time (24h format), type label (uppercase), text content\n"
            "- Thought types color-coded: thought, speech, observation, action, deep_look\n\n"
            "BOTTOM-RIGHT: SENSORIUM + CHAT\n"
            "- 'SENSORIUM' header, people count, narrative text\n"
            "- 'TALK TO AMY' header\n"
            "- Chat log with messages (Amy=left, User=right)\n"
            "- Input field: 'Say something to Amy...' placeholder + SEND button\n\n"
            "BATTLESPACE section:\n"
            "- 'BATTLESPACE' header, target summary count\n"
            "- 'SPAWN HOSTILE' button (magenta border) and "
            "  'SPAWN FRIENDLY' button (green border)\n"
            "- Target list with alliance colors, names, positions, battery %\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which panels/sections are actually visible?\n"
            "2. MISSING: Which panels are NOT visible or seem collapsed?\n"
            "3. WRONG: Elements that look different from spec?\n"
            "4. BROKEN: Overlapping panels, text overflow, clipped content?\n"
            "5. SIZING: Do all panels fit on screen, or do some get pushed off?"
        ),
    },
    "scenarios": {
        "shortcut": "s",
        "settle_ms": 3000,
        "label": "Scenarios",
        "description": "Synthetic scenario testing dashboard with live video, scoring, and TTS",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — Scenarios Dashboard:\n"
            "This view is a 2x2 panel layout for testing Amy behavioral scenarios.\n\n"
            "TOP-LEFT: SCENARIO LIBRARY\n"
            "- Panel header: 'SCENARIO LIBRARY' with a cache badge and count\n"
            "- Scrollable list of scenario items, each showing scenario name and metadata\n"
            "- Loading text: 'Loading scenarios...' when list is empty\n\n"
            "TOP-RIGHT: SYNTHETIC CAMERA\n"
            "- Panel header: 'SYNTHETIC CAMERA' with a run badge ('IDLE' by default)\n"
            "- Video container: MJPEG feed image (or overlay: circle icon + 'NO FEED' + "
            "  'Select a scenario and click RUN')\n"
            "- Speech bubble overlay for Amy's TTS output\n"
            "- Run controls area below video\n\n"
            "BOTTOM-LEFT: LIVE FEED\n"
            "- Panel header: 'LIVE FEED' with action count (e.g. '0 actions')\n"
            "- Voice selector dropdown and TTS toggle checkbox\n"
            "- Timeline area: 'Run a scenario to see live events...' when idle\n\n"
            "BOTTOM-RIGHT: EVALUATION\n"
            "- Panel header: 'EVALUATION'\n"
            "- Score grid: SCORE, MATCHED, DETECTION, LATENCY (all '--' when idle)\n"
            "- Star rating buttons (5 stars) for human rating (hidden until run completes)\n"
            "- Score details area\n\n"
            "Color scheme: dark cyberpunk (near-black bg, cyan headers, panel borders).\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which panels are visible?\n"
            "2. MISSING: Which panels are NOT visible?\n"
            "3. WRONG: Elements that differ from spec?\n"
            "4. BROKEN: Overlapping panels, truncated text, layout issues?\n"
            "5. STATE: Is the view showing idle state (no active scenario run)?"
        ),
    },
    "war": {
        "shortcut": "w",
        "settle_ms": 5000,
        "label": "War Room",
        "description": "3D tactical war room with neighborhood map, HUD, and game controls",
        "audit_prompt": (
            "You are a UI auditor comparing a screenshot against its design specification.\n\n"
            "DESIGN INTENT — War Room (Full-Screen RTS Game View):\n"
            "The War Room SHOULD fill the entire viewport with a 3D scene + HUD overlays:\n\n"
            "BACKGROUND: Full-screen Three.js WebGL canvas showing:\n"
            "- A 3D ground plane with satellite imagery tiles (0.7 opacity)\n"
            "- A grid overlay (cyan lines, 5-unit spacing)\n"
            "- Unit markers: friendly=green circles, hostile=red diamonds, "
            "  neutral=blue circles, unknown=yellow squares\n"
            "- Zone polygons, weapon range circles, dispatch arrows (magenta dashed)\n\n"
            "HUD OVERLAYS (HTML positioned absolute over canvas, z-index 10):\n\n"
            "TOP-LEFT: Address Bar\n"
            "- Input field: 'Enter address to load satellite map...'\n"
            "- 'GEOCODE' button\n"
            "- Status feedback text (green on success, red on error)\n\n"
            "TOP-CENTER: Mode Selector\n"
            "- Two buttons: 'SIM' (active by default, cyan) and 'LIVE'\n"
            "- Mode indicator text below: 'SIM MODE' or 'LIVE MODE'\n\n"
            "CENTER: BEGIN WAR Button (visible in setup state)\n"
            "- Large cyan-bordered button with 'BEGIN WAR' text\n"
            "- Should be clearly clickable, not obscured by the 3D canvas\n\n"
            "RIGHT (280px): Amy Status Panel\n"
            "- Header: 'AMY STATUS' in cyan\n"
            "- Mood display, state display\n"
            "- Scrollable thoughts list (max 200px height)\n\n"
            "BOTTOM-RIGHT (300px): Alert Log\n"
            "- Header: 'ALERTS' in magenta\n"
            "- Scrollable entries with timestamps and color-coded types:\n"
            "  hostile_detected, zone_violation, friendly_destroyed, target_elimination\n\n"
            "BOTTOM-LEFT: Minimap (150x150)\n"
            "- Miniature version of main map with unit dots\n"
            "- Dark background with cyan border\n\n"
            "GAME HUD (visible during active game):\n"
            "- Score display (top-center): Score, Kills, Accuracy, Wave Progress\n"
            "- Kill feed (right-aligned): recent elimination messages\n"
            "- Countdown overlay and wave banner (during transitions)\n\n"
            "COMPARE against this spec and report:\n"
            "1. PRESENT: Which HUD elements are actually visible?\n"
            "2. MISSING: Which HUD elements are NOT visible?\n"
            "3. 3D SCENE: Does the canvas show a 3D rendered scene (not blank/black)?\n"
            "4. Z-INDEX: Are HUD panels readable ABOVE the 3D canvas, or hidden behind it?\n"
            "5. BROKEN: Any overlapping HUD panels, text hard to read against the "
            "   3D background, buttons not accessible?\n"
            "6. GAME STATE: Is it in setup mode (BEGIN WAR visible) or active mode "
            "   (score/wave visible)?"
        ),
    },
}

# OCR prompt — same for every screenshot
OCR_PROMPT = (
    "Extract ALL visible text from this screenshot. "
    "Organize by location (top, left, center, right, bottom). "
    "Include: button labels, panel headers, status text, numbers, "
    "tooltips, placeholder text, timestamps, and any other readable text. "
    "Note any text that appears truncated, cut off, or overlapping."
)

# Deep vision prompt template — filled per-view
DEEP_PROMPT_TEMPLATE = (
    "You are a senior UI/UX auditor reviewing a screenshot of '{view_label}' "
    "at {res_label} resolution. Focus SPECIFICALLY on:\n\n"
    "1. RESPONSIVE ISSUES: Elements that don't adapt well to this screen size\n"
    "2. OVERLAPPING: Any UI elements that overlap, clip, or obscure each other\n"
    "3. READABILITY: Text too small, low contrast, truncated, or hard to read\n"
    "4. ACCESSIBILITY: Touch targets too small, controls too close together\n"
    "5. VISUAL BUGS: Misaligned elements, broken borders, rendering glitches\n"
    "6. EMPTY SPACE: Panels that seem empty when they should have content\n\n"
    "For each issue found, describe it precisely with location and severity "
    "(critical/major/minor). If the UI looks good, say so and explain why.\n\n"
    "Be thorough — examine every corner of the screenshot."
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModelResult:
    """Result of a single model pass on a single screenshot."""
    model: str = ""
    role: str = ""           # "vision", "ocr", "deep", "ultra"
    response: str = ""
    elapsed: float = 0.0
    error: bool = False


@dataclass
class ScreenshotAudit:
    """Complete audit of one view at one resolution."""
    view: str = ""
    resolution: str = ""
    resolution_label: str = ""
    width: int = 0
    height: int = 0
    screenshot_path: str = ""
    # OpenCV metrics
    content_ratio: float = 0.0
    edge_density: float = 0.0
    avg_brightness: float = 0.0
    color_variance: float = 0.0
    is_blank: bool = True
    # Model results (populated in separate passes)
    model_results: list[ModelResult] = field(default_factory=list)
    # Issues detected (from algorithmic + model analysis)
    issues: list[str] = field(default_factory=list)
    # Error
    error: str = ""


@dataclass
class AuditReport:
    """Complete audit report."""
    timestamp: str = ""
    url: str = ""
    models_used: list[str] = field(default_factory=list)
    total_time: float = 0.0
    results: list[ScreenshotAudit] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Ollama model management
# ---------------------------------------------------------------------------

def ollama_request(endpoint: str, payload: dict, timeout: int = 600) -> dict:
    """Make a request to the Ollama API."""
    import requests
    resp = requests.post(
        f"{OLLAMA_URL}{endpoint}",
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def get_available_models() -> list[str]:
    """Get list of models available in Ollama."""
    import requests
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []


def unload_model(model: str) -> None:
    """Explicitly unload a model from GPU memory."""
    import requests
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=30,
        )
        print(f"    [UNLOAD] {model}")
    except Exception:
        pass  # Best effort


def pull_model(model: str) -> bool:
    """Pull a model via Ollama CLI. Returns True on success."""
    print(f"  Pulling {model}...")
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=False,
            timeout=3600,  # 1 hour max for large models
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  ERROR pulling {model}: {e}")
        return False


def ensure_models(models: list[str], auto_pull: bool = True) -> list[str]:
    """Check which models are available, optionally pull missing ones.

    Returns list of models that are ready to use.
    """
    available = get_available_models()
    ready = []
    for m in models:
        if m in available:
            ready.append(m)
            print(f"  [OK] {m}")
        elif auto_pull:
            print(f"  [MISSING] {m} — pulling...")
            if pull_model(m):
                ready.append(m)
                print(f"  [OK] {m} — pulled successfully")
            else:
                print(f"  [FAIL] {m} — could not pull")
        else:
            print(f"  [MISSING] {m} — skipping (use --setup to pull)")
    return ready


# ---------------------------------------------------------------------------
# Playwright screenshot
# ---------------------------------------------------------------------------

def _build_screenshot_script(
    url: str,
    view: str,
    output_path: str,
    width: int,
    height: int,
    scale: int,
    wait_ms: int = 3000,
    extra_js: str = "",
) -> str:
    """Generate a Node.js script that uses Playwright to screenshot a view."""
    shortcut = VIEWS.get(view, {}).get("shortcut", "")
    key_press = f'await page.keyboard.press("{shortcut}");' if shortcut else ""

    return textwrap.dedent(f"""\
        const {{ chromium }} = require('playwright');

        (async () => {{
            const browser = await chromium.launch({{
                headless: true,
                args: ['--disable-gpu', '--no-sandbox'],
            }});
            const context = await browser.newContext({{
                viewport: {{ width: {width}, height: {height} }},
                deviceScaleFactor: {scale},
            }});
            const page = await context.newPage();

            // Suppress dialog boxes
            page.on('dialog', async dialog => await dialog.dismiss());

            // Navigate
            await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: 30000 }});

            // Wait for initial render
            await page.waitForTimeout(1500);

            // Switch to requested view via keyboard shortcut
            {key_press}

            // Let the view settle
            await page.waitForTimeout({wait_ms});

            {extra_js}

            // Screenshot
            await page.screenshot({{ path: '{output_path}', fullPage: false }});

            await browser.close();
            process.exit(0);
        }})().catch(err => {{
            console.error(err.message);
            process.exit(1);
        }});
    """)


def take_screenshot(
    url: str,
    view: str,
    output_path: str,
    width: int = 1920,
    height: int = 1080,
    scale: int = 1,
    wait_ms: int = 3000,
    extra_js: str = "",
    timeout: int = 60,
) -> bool:
    """Take a screenshot via Playwright subprocess. Returns True on success."""
    script = _build_screenshot_script(url, view, output_path, width, height, scale, wait_ms, extra_js)
    script_file = Path(tempfile.mktemp(suffix=".js", prefix="pw_audit_"))
    script_file.write_text(script)

    env = os.environ.copy()
    env["NODE_PATH"] = str(NODE_MODULES)

    try:
        result = subprocess.run(
            ["node", str(script_file)],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        if result.returncode != 0:
            print(f"      [PLAYWRIGHT ERROR] {result.stderr.strip()[:300]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"      [PLAYWRIGHT TIMEOUT] {timeout}s")
        return False
    finally:
        script_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# OpenCV analysis
# ---------------------------------------------------------------------------

def analyze_image(image_path: str) -> dict:
    """Run OpenCV analysis on a screenshot.

    Returns dict with content_ratio, edge_density, avg_brightness, color_variance.
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"content_ratio": 0.0, "edge_density": 0.0,
                "avg_brightness": 0.0, "color_variance": 0.0}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    total = h * w

    # Content ratio: pixels brighter than threshold 12
    _, mask = cv2.threshold(gray, 12, 255, cv2.THRESH_BINARY)
    content_ratio = cv2.countNonZero(mask) / total if total > 0 else 0.0

    # Edge density: Canny edges as fraction of total pixels
    edges = cv2.Canny(gray, 50, 150)
    edge_density = cv2.countNonZero(edges) / total if total > 0 else 0.0

    # Average brightness
    avg_brightness = float(np.mean(gray))

    # Color variance: std of each channel, then mean
    stds = [float(np.std(img[:, :, c])) for c in range(3)]
    color_variance = float(np.mean(stds))

    return {
        "content_ratio": content_ratio,
        "edge_density": edge_density,
        "avg_brightness": avg_brightness,
        "color_variance": color_variance,
    }


# ---------------------------------------------------------------------------
# Ollama vision queries
# ---------------------------------------------------------------------------

def query_ollama_vision(
    image_path: str,
    prompt: str,
    model: str = "llava:7b",
    timeout: int = 600,
    max_tokens: int = 2048,
) -> tuple[str, float]:
    """Send an image to an Ollama vision model.

    Returns (response_text, elapsed_seconds).
    """
    import requests

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    t0 = time.time()
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.1},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        elapsed = time.time() - t0
        return resp.json().get("response", ""), elapsed
    except Exception as e:
        elapsed = time.time() - t0
        return f"[OLLAMA ERROR] {e}", elapsed


# ---------------------------------------------------------------------------
# Issue extraction from model responses
# ---------------------------------------------------------------------------

def extract_vision_issues(response: str, audit: ScreenshotAudit) -> None:
    """Parse vision model response for issue-like language."""
    lower = response.lower()

    issue_indicators = [
        ("overlap", "OVERLAP: Vision model detected overlapping elements"),
        ("truncat", "TRUNCATION: Vision model detected truncated text or elements"),
        ("cut off", "CLIPPING: Vision model detected elements cut off"),
        ("too small", "SIZE: Vision model noted elements too small"),
        ("hard to read", "READABILITY: Vision model noted hard-to-read content"),
        ("not visible", "MISSING: Vision model noted elements not visible"),
        ("missing", "MISSING: Vision model noted missing expected elements"),
        ("broken", "BROKEN: Vision model detected broken elements"),
        ("misalign", "ALIGNMENT: Vision model detected misaligned elements"),
        ("overflow", "OVERFLOW: Vision model detected content overflow"),
        ("glitch", "GLITCH: Vision model detected visual glitches"),
        ("empty", "EMPTY: Vision model noted empty areas that may need content"),
        ("cannot confirm", "UNCERTAIN: Vision model couldn't confirm expected elements"),
        ("no clear indication", "UNCERTAIN: Vision model couldn't find expected elements"),
        ("not clearly visible", "VISIBILITY: Elements not clearly visible"),
    ]

    for keyword, issue_msg in issue_indicators:
        if keyword in lower and issue_msg not in audit.issues:
            audit.issues.append(issue_msg)


# ---------------------------------------------------------------------------
# Phase 1: Take all screenshots
# ---------------------------------------------------------------------------

def take_all_screenshots(
    url: str,
    views: list[str],
    resolutions: list[str],
    output_dir: Path,
) -> list[ScreenshotAudit]:
    """Take screenshots for every view x resolution combination.

    Returns list of ScreenshotAudit with screenshot_path and OpenCV metrics.
    """
    audits = []
    total = len(views) * len(resolutions)
    num = 0

    for view in views:
        view_cfg = VIEWS[view]
        for res_key in resolutions:
            num += 1
            res = RESOLUTIONS[res_key]

            audit = ScreenshotAudit(
                view=view,
                resolution=res_key,
                resolution_label=res["label"],
                width=res["width"],
                height=res["height"],
            )

            ts = datetime.now().strftime("%H%M%S")
            ss_name = f"{view}_{res_key}_{ts}.png"
            ss_path = str(output_dir / ss_name)
            audit.screenshot_path = ss_path

            print(f"  [{num}/{total}] {view_cfg['label']} @ {res['label']}...", end=" ", flush=True)

            extra_js = ""
            if view in ("war", "3d"):
                extra_js = "await page.waitForTimeout(2000);"

            if not take_screenshot(
                url, view, ss_path,
                width=res["width"], height=res["height"], scale=res["scale"],
                wait_ms=view_cfg["settle_ms"], extra_js=extra_js, timeout=60,
            ):
                audit.error = "Playwright screenshot failed"
                print("FAIL")
                audits.append(audit)
                continue

            # OpenCV analysis
            metrics = analyze_image(ss_path)
            audit.content_ratio = metrics["content_ratio"]
            audit.edge_density = metrics["edge_density"]
            audit.avg_brightness = metrics["avg_brightness"]
            audit.color_variance = metrics["color_variance"]
            audit.is_blank = audit.content_ratio < MIN_CONTENT_RATIO

            if audit.is_blank:
                audit.error = f"Screenshot blank (content: {audit.content_ratio:.1%})"
                audit.issues.append(f"BLANK: View renders as mostly black ({audit.content_ratio:.1%} content)")
                print(f"BLANK ({audit.content_ratio:.1%})")
            else:
                # Algorithmic issue detection
                if audit.avg_brightness < 15:
                    audit.issues.append("VERY DARK: Average brightness below 15")
                if audit.edge_density < 0.005:
                    audit.issues.append("LOW DETAIL: Very few edges — possible blank render")
                if audit.edge_density > 0.15:
                    audit.issues.append("HIGH NOISE: Unusually high edge density")
                print(f"OK ({audit.content_ratio:.0%})")

            audits.append(audit)

    return audits


# ---------------------------------------------------------------------------
# Phase 2+: Run a model pass across all screenshots
# ---------------------------------------------------------------------------

def _resolution_context(resolution: str, label: str) -> str:
    """Build resolution-specific addendum for audit prompts."""
    base = (
        f"\n\nIMPORTANT CONTEXT: This screenshot was taken at {label} resolution. "
        "Pay special attention to whether elements are appropriately sized, readable, "
        "and accessible at this screen size. "
    )
    if resolution == "mobile":
        return base + (
            "For mobile: check that touch targets are at least 44px, text is readable "
            "without zooming, panels stack vertically, nothing overflows horizontally."
        )
    if resolution == "tablet":
        return base + (
            "For tablet: check that layout adapts between mobile and desktop, panels "
            "don't have excessive whitespace, multi-column layouts work."
        )
    return base + (
        "For desktop: check that panels fill available space, no excessive empty areas, "
        "multi-panel layouts display properly, all UI elements are visible."
    )


def run_model_pass(
    audits: list[ScreenshotAudit],
    model: str,
    role: str,
    timeout_per: int = 300,
    max_tokens: int = 2048,
) -> None:
    """Run a single model across all non-blank screenshots.

    Adds a ModelResult to each audit's model_results list.
    """
    eligible = [a for a in audits if not a.is_blank and not a.error]
    total = len(eligible)

    print(f"\n{'='*70}")
    print(f"  MODEL PASS: {model} ({role}) — {total} screenshots")
    print(f"{'='*70}")

    for i, audit in enumerate(eligible, 1):
        view_cfg = VIEWS.get(audit.view, {})

        # Build the prompt based on role
        if role == "ocr":
            prompt = OCR_PROMPT
        elif role == "vision":
            prompt = view_cfg.get("audit_prompt", "Describe what you see in detail.")
            prompt += _resolution_context(audit.resolution, audit.resolution_label)
        elif role in ("deep", "ultra"):
            prompt = DEEP_PROMPT_TEMPLATE.format(
                view_label=view_cfg.get("label", audit.view),
                res_label=audit.resolution_label,
            )
        else:
            prompt = "Describe this UI screenshot in detail."

        print(f"  [{i}/{total}] {audit.view}@{audit.resolution}...", end=" ", flush=True)

        response, elapsed = query_ollama_vision(
            audit.screenshot_path, prompt, model,
            timeout=timeout_per, max_tokens=max_tokens,
        )

        mr = ModelResult(
            model=model,
            role=role,
            response=response,
            elapsed=elapsed,
            error=response.startswith("[OLLAMA ERROR]"),
        )
        audit.model_results.append(mr)

        if mr.error:
            print(f"ERROR ({elapsed:.1f}s)")
        else:
            print(f"OK ({elapsed:.1f}s, {len(response)} chars)")
            # Extract issues from vision/deep responses
            if role in ("vision", "deep", "ultra"):
                extract_vision_issues(response, audit)

    # Unload model after pass
    unload_model(model)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(report: AuditReport, output_dir: Path) -> None:
    """Generate comprehensive markdown and JSON reports."""
    _generate_json_report(report, output_dir)
    _generate_markdown_report(report, output_dir)


def _generate_json_report(report: AuditReport, output_dir: Path) -> None:
    """Write JSON report for machine consumption."""
    data = {
        "timestamp": report.timestamp,
        "url": report.url,
        "models_used": report.models_used,
        "total_time_seconds": round(report.total_time, 1),
        "total_audits": len(report.results),
        "blank_count": sum(1 for r in report.results if r.is_blank),
        "issue_count": sum(len(r.issues) for r in report.results),
        "results": [],
    }
    for r in report.results:
        entry = {
            "view": r.view,
            "resolution": r.resolution,
            "resolution_label": r.resolution_label,
            "width": r.width,
            "height": r.height,
            "screenshot": r.screenshot_path,
            "content_ratio": round(r.content_ratio, 4),
            "edge_density": round(r.edge_density, 4),
            "avg_brightness": round(r.avg_brightness, 1),
            "color_variance": round(r.color_variance, 1),
            "is_blank": r.is_blank,
            "issues": r.issues,
            "error": r.error,
            "model_results": [],
        }
        for mr in r.model_results:
            entry["model_results"].append({
                "model": mr.model,
                "role": mr.role,
                "response": mr.response,
                "elapsed": round(mr.elapsed, 2),
                "error": mr.error,
            })
        data["results"].append(entry)

    path = output_dir / "audit_report.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"  JSON report: {path}")


def _generate_markdown_report(report: AuditReport, output_dir: Path) -> None:
    """Write detailed markdown report for human review."""
    lines = []
    w = lines.append

    # --- Header ---
    w("# TRITIUM-SC UI Audit Report")
    w("")
    w(f"**Date:** {report.timestamp}  ")
    w(f"**Server:** {report.url}  ")
    w(f"**Models:** {', '.join(report.models_used)}  ")
    w(f"**Total Time:** {report.total_time / 60:.1f} minutes  ")
    w(f"**Views Audited:** {len(set(r.view for r in report.results))}  ")
    w(f"**Resolutions Tested:** {len(set(r.resolution for r in report.results))}  ")
    w(f"**Total Screenshots:** {len(report.results)}  ")
    w("")

    # --- Executive Summary ---
    w("## Executive Summary")
    w("")

    total = len(report.results)
    blanks = sum(1 for r in report.results if r.is_blank)
    errors = sum(1 for r in report.results if r.error)
    all_issues = []
    for r in report.results:
        for iss in r.issues:
            all_issues.append((r.view, r.resolution, iss))

    w(f"- **{total} screenshots** analyzed across {len(set(r.view for r in report.results))} views "
      f"and {len(set(r.resolution for r in report.results))} resolutions")
    if blanks:
        w(f"- **{blanks} blank screenshots** detected (views not rendering)")
    if errors:
        w(f"- **{errors} errors** during testing")
    w(f"- **{len(all_issues)} potential issues** flagged")
    w("")

    # Issue summary by category
    if all_issues:
        w("### Issues by Category")
        w("")
        categories: dict[str, list[tuple[str, str]]] = {}
        for view, res, issue in all_issues:
            cat = issue.split(":")[0] if ":" in issue else "OTHER"
            categories.setdefault(cat, []).append((view, res))

        for cat in sorted(categories.keys()):
            items = categories[cat]
            w(f"- **{cat}** ({len(items)}): " +
              ", ".join(f"{v}@{r}" for v, r in items))
        w("")

    # --- Content Ratio Heatmap ---
    w("## Content Coverage Matrix")
    w("")
    w("Content ratio by view and resolution (higher = more visible content):")
    w("")

    res_keys = sorted(set(r.resolution for r in report.results),
                      key=lambda x: RESOLUTIONS.get(x, {}).get("width", 0))
    view_keys = sorted(set(r.view for r in report.results),
                       key=lambda x: list(VIEWS.keys()).index(x) if x in VIEWS else 99)

    header = "| View | " + " | ".join(RESOLUTIONS.get(rk, {}).get("label", rk) for rk in res_keys) + " |"
    sep = "|------|" + "|".join("------" for _ in res_keys) + "|"
    w(header)
    w(sep)

    for vk in view_keys:
        cells = []
        for rk in res_keys:
            matching = [r for r in report.results if r.view == vk and r.resolution == rk]
            if matching:
                r = matching[0]
                val = f"{r.content_ratio:.0%}"
                if r.is_blank:
                    val = f"**BLANK** ({r.content_ratio:.0%})"
                cells.append(val)
            else:
                cells.append("--")
        w(f"| {vk:12s} | " + " | ".join(cells) + " |")
    w("")

    # --- Edge Density Matrix ---
    w("## Edge Density Matrix")
    w("")
    w("Edge density indicates UI complexity. "
      "Very low (<0.005) = blank.  Very high (>0.15) = noise.")
    w("")

    w(header)
    w(sep)
    for vk in view_keys:
        cells = []
        for rk in res_keys:
            matching = [r for r in report.results if r.view == vk and r.resolution == rk]
            if matching:
                cells.append(f"{matching[0].edge_density:.3f}")
            else:
                cells.append("--")
        w(f"| {vk:12s} | " + " | ".join(cells) + " |")
    w("")

    # --- Per-View Detail Sections ---
    w("---")
    w("")
    w("# Detailed View Analysis")
    w("")

    for view_name in view_keys:
        view_cfg = VIEWS.get(view_name, {})
        view_label = view_cfg.get("label", view_name)

        w(f"## {view_label} ({view_name})")
        w("")
        w(f"> {view_cfg.get('description', '')}")
        w("")

        view_results = [r for r in report.results if r.view == view_name]

        for r in sorted(view_results, key=lambda x: RESOLUTIONS.get(x.resolution, {}).get("width", 0)):
            w(f"### {r.resolution_label}")
            w("")

            if r.error:
                w(f"**ERROR:** {r.error}")
                w("")
                continue

            w(f"**Screenshot:** `{Path(r.screenshot_path).name}`  ")
            w(f"**Content:** {r.content_ratio:.1%} | "
              f"**Edges:** {r.edge_density:.3f} | "
              f"**Brightness:** {r.avg_brightness:.0f} | "
              f"**Color Var:** {r.color_variance:.1f}")
            w("")

            # Issues
            if r.issues:
                w("**Issues Detected:**")
                for iss in r.issues:
                    w(f"- {iss}")
                w("")

            # Model results by role
            for mr in r.model_results:
                if mr.error:
                    w(f"**{mr.role.upper()} ({mr.model}):** ERROR ({mr.elapsed:.1f}s)")
                    w("")
                    continue

                w(f"**{mr.role.upper()} Analysis** ({mr.model}, {mr.elapsed:.1f}s):")
                w("")
                resp_text = mr.response.strip()
                if mr.role == "ocr":
                    w("```")
                    if len(resp_text) > 2000:
                        resp_text = resp_text[:2000] + "\n... (truncated)"
                    w(resp_text)
                    w("```")
                else:
                    for line in resp_text.split("\n"):
                        w(f"> {line}")
                w("")

            w("---")
            w("")

    # --- Cross-Resolution Comparison ---
    w("# Cross-Resolution Comparison")
    w("")

    for view_name in view_keys:
        view_cfg = VIEWS.get(view_name, {})
        view_results = [r for r in report.results if r.view == view_name and not r.is_blank]

        if len(view_results) < 2:
            continue

        w(f"### {view_cfg.get('label', view_name)}")
        w("")

        ratios = {r.resolution: r.content_ratio for r in view_results}
        if ratios:
            w(f"- Content coverage: " +
              ", ".join(f"{k}={v:.0%}" for k, v in sorted(ratios.items())))

        edges = {r.resolution: r.edge_density for r in view_results}
        if edges:
            w(f"- Edge density: " +
              ", ".join(f"{k}={v:.3f}" for k, v in sorted(edges.items())))

        if "mobile" in ratios and "desktop" in ratios:
            diff = abs(ratios["desktop"] - ratios["mobile"])
            if diff > 0.3:
                w(f"- **WARNING**: Large content difference between mobile and desktop "
                  f"({diff:.0%}) — may indicate layout issues")

        w("")

    # --- Timing Summary ---
    w("## Timing Summary")
    w("")

    # Aggregate by role
    role_times: dict[str, float] = {}
    for r in report.results:
        for mr in r.model_results:
            key = f"{mr.role} ({mr.model})"
            role_times[key] = role_times.get(key, 0) + mr.elapsed

    w("| Phase | Time |")
    w("|-------|------|")
    for key, t in role_times.items():
        w(f"| {key} | {t:.0f}s ({t/60:.1f}m) |")
    w(f"| **Total** | **{report.total_time:.0f}s ({report.total_time/60:.1f}m)** |")
    w("")

    # Write file
    md_path = output_dir / "audit_report.md"
    md_path.write_text("\n".join(lines))
    print(f"  Markdown report: {md_path}")


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def preflight(url: str) -> list[str]:
    """Check prerequisites. Returns list of warnings."""
    import requests
    warnings = []

    # Server
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            warnings.append(f"Server at {url} returned {r.status_code}")
    except Exception as e:
        warnings.append(f"Cannot reach server at {url}: {e}")

    # Ollama
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code != 200:
            warnings.append(f"Ollama at {OLLAMA_URL} returned {r.status_code}")
    except Exception as e:
        warnings.append(f"Cannot reach Ollama: {e}")

    # Playwright
    env = os.environ.copy()
    env["NODE_PATH"] = str(NODE_MODULES)
    try:
        result = subprocess.run(
            ["node", "-e", 'require("playwright"); console.log("OK")'],
            capture_output=True, text=True, timeout=10, env=env,
        )
        if result.returncode != 0:
            warnings.append(f"Playwright: {result.stderr.strip()[:200]}")
    except Exception as e:
        warnings.append(f"Node/Playwright: {e}")

    return warnings


# ---------------------------------------------------------------------------
# Setup mode
# ---------------------------------------------------------------------------

def setup_models(tier: str = "standard") -> None:
    """Download all models needed for a given tier.

    Tier choices:
      standard — llava:7b + glm-ocr:latest
      deep     — + best qwen2.5vl for this system
      ultra    — + qwen2.5vl:72b
    """
    mem_gb = get_system_memory_gb()
    print(f"  System memory: {mem_gb:.0f} GB")
    print(f"  Tier: {tier}")
    print()

    models = ["llava:7b", "glm-ocr:latest"]

    if tier in ("deep", "ultra"):
        deep = pick_deep_model()
        if deep not in models:
            models.append(deep)
        print(f"  Auto-selected deep model: {deep} (based on {mem_gb:.0f} GB RAM)")

    if tier == "ultra":
        if mem_gb >= 64:
            if "qwen2.5vl:72b" not in models:
                models.append("qwen2.5vl:72b")
        else:
            print(f"  WARNING: Ultra tier needs 64+ GB, you have {mem_gb:.0f} GB. "
                  f"Skipping qwen2.5vl:72b.")

    print(f"\n  Models to ensure: {', '.join(models)}\n")
    ready = ensure_models(models, auto_pull=True)
    print(f"\n  Ready: {len(ready)}/{len(models)} models")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_audit(
    url: str,
    views: list[str],
    resolutions: list[str],
    models_config: dict,
    output_dir: Path,
) -> AuditReport:
    """Run the full UI audit.

    models_config keys:
      vision:  str — primary vision model (e.g. llava:7b)
      ocr:     str — OCR model (e.g. glm-ocr:latest)
      deep:    Optional[str] — deep analysis model
      ultra:   Optional[str] — ultra analysis model
    """
    report = AuditReport(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        url=url,
    )

    t0 = time.time()

    # Phase 1: Take all screenshots
    total_screenshots = len(views) * len(resolutions)
    print(f"\n{'='*70}")
    print(f"  PHASE 1: SCREENSHOTS ({total_screenshots} combinations)")
    print(f"{'='*70}\n")

    audits = take_all_screenshots(url, views, resolutions, output_dir)
    report.results = audits

    non_blank = sum(1 for a in audits if not a.is_blank and not a.error)
    print(f"\n  Screenshots: {len(audits)} taken, {non_blank} non-blank")

    # Phase 2: Vision model pass
    vision_model = models_config.get("vision")
    if vision_model:
        report.models_used.append(vision_model)
        run_model_pass(audits, vision_model, "vision", timeout_per=300, max_tokens=2048)

    # Phase 3: OCR pass
    ocr_model = models_config.get("ocr")
    if ocr_model:
        report.models_used.append(ocr_model)
        run_model_pass(audits, ocr_model, "ocr", timeout_per=120, max_tokens=2048)

    # Phase 4: Deep model pass (optional)
    deep_model = models_config.get("deep")
    if deep_model:
        report.models_used.append(deep_model)
        run_model_pass(audits, deep_model, "deep", timeout_per=600, max_tokens=3072)

    # Phase 5: Ultra model pass (optional)
    ultra_model = models_config.get("ultra")
    if ultra_model:
        report.models_used.append(ultra_model)
        run_model_pass(audits, ultra_model, "ultra", timeout_per=1200, max_tokens=4096)

    report.total_time = time.time() - t0
    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TRITIUM-SC Comprehensive UI Audit Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python3 tests/ui/test_vision.py                       # Standard: llava + OCR
              python3 tests/ui/test_vision.py --deep                # + auto-sized qwen2.5vl
              python3 tests/ui/test_vision.py --ultra               # + qwen2.5vl:72b (slow!)
              python3 tests/ui/test_vision.py --view war            # Single view, all resolutions
              python3 tests/ui/test_vision.py --resolution desktop  # All views, desktop only
              python3 tests/ui/test_vision.py --quick               # Desktop only, llava only
              python3 tests/ui/test_vision.py --setup               # Download standard models
              python3 tests/ui/test_vision.py --setup --ultra       # Download all incl. 72B
              python3 tests/ui/test_vision.py --list                # List available views

            Model tiers (all run sequentially, one at a time):
              standard  llava:7b (vision) + glm-ocr:latest (OCR)
              deep      + qwen2.5vl:3b/7b/32b (auto-sized for your RAM)
              ultra     + qwen2.5vl:72b (49 GB download, needs 64+ GB RAM)

            See docs/UI-VIEWS.md for the design-intent spec behind each view's prompt.
        """),
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Server URL")
    parser.add_argument("--vision-model", default="llava:7b", help="Primary vision model")
    parser.add_argument("--ocr-model", default="glm-ocr:latest", help="OCR model")
    parser.add_argument("--deep", action="store_true",
                        help="Add a deep analysis pass (qwen2.5vl, auto-sized)")
    parser.add_argument("--deep-model", default=None,
                        help="Override deep model (default: auto-sized qwen2.5vl)")
    parser.add_argument("--ultra", action="store_true",
                        help="Add ultra analysis pass (qwen2.5vl:72b)")
    parser.add_argument("--view", default=None,
                        help="Audit a single view (e.g., war, amy, assets)")
    parser.add_argument("--resolution", default=None,
                        help="Single resolution: mobile, tablet, desktop")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: desktop only, vision model only, no OCR")
    parser.add_argument("--output", default="/tmp/tritium-ui-audit",
                        help="Output directory for screenshots and reports")
    parser.add_argument("--list", action="store_true",
                        help="List available views and resolutions")
    parser.add_argument("--setup", action="store_true",
                        help="Download required models and exit")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip preflight checks")
    parser.add_argument("--no-pull", action="store_true",
                        help="Don't auto-pull missing models")

    args = parser.parse_args()

    # --- List mode ---
    if args.list:
        print("Available views:")
        for name, cfg in VIEWS.items():
            print(f"  {name:12s}  [{cfg['shortcut']}]  {cfg['label']:20s}  {cfg['description']}")
        print(f"\nResolutions:")
        for name, cfg in RESOLUTIONS.items():
            print(f"  {name:8s}  {cfg['label']}")
        print(f"\nSystem memory: {get_system_memory_gb():.0f} GB")
        print(f"Auto deep model: {pick_deep_model()}")
        print(f"\nOllama models available:")
        for m in get_available_models():
            print(f"  {m}")
        return 0

    # --- Setup mode ---
    if args.setup:
        tier = "ultra" if args.ultra else ("deep" if args.deep else "standard")
        print(f"{'='*70}")
        print(f"  MODEL SETUP — tier: {tier}")
        print(f"{'='*70}\n")
        setup_models(tier)
        return 0

    # --- Determine views and resolutions ---
    if args.view:
        if args.view not in VIEWS:
            print(f"Unknown view: {args.view}. Available: {', '.join(VIEWS.keys())}")
            return 1
        views = [args.view]
    else:
        views = list(VIEWS.keys())

    if args.quick:
        resolutions = ["desktop"]
    elif args.resolution:
        if args.resolution not in RESOLUTIONS:
            print(f"Unknown resolution: {args.resolution}. Available: {', '.join(RESOLUTIONS.keys())}")
            return 1
        resolutions = [args.resolution]
    else:
        resolutions = list(RESOLUTIONS.keys())

    # --- Build models config ---
    models_config: dict[str, Optional[str]] = {
        "vision": args.vision_model,
        "ocr": None if args.quick else args.ocr_model,
        "deep": None,
        "ultra": None,
    }

    if args.deep or args.ultra:
        models_config["deep"] = args.deep_model or pick_deep_model()

    if args.ultra:
        models_config["ultra"] = "qwen2.5vl:72b"

    # Collect all models to verify
    needed_models = [m for m in models_config.values() if m]

    # Output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_combos = len(views) * len(resolutions)
    model_passes = sum(1 for m in models_config.values() if m)
    est_seconds = total_combos * 5  # screenshots
    est_seconds += total_combos * 30 * model_passes  # model passes
    if models_config.get("ultra"):
        est_seconds += total_combos * 120  # ultra is slow

    mem_gb = get_system_memory_gb()

    print("=" * 70)
    print("  TRITIUM-SC UI AUDIT SUITE")
    print("=" * 70)
    print(f"  Server:       {args.url}")
    print(f"  System RAM:   {mem_gb:.0f} GB")
    print(f"  Views:        {', '.join(views)} ({len(views)})")
    print(f"  Resolutions:  {', '.join(resolutions)} ({len(resolutions)})")
    print(f"  Screenshots:  {total_combos}")
    print(f"  Model passes: {model_passes}")
    for role, model in models_config.items():
        if model:
            print(f"    {role:8s} → {model}")
    print(f"  Est. Time:    ~{est_seconds // 60} minutes")
    print(f"  Output:       {output_dir}")
    print("=" * 70)
    print()

    # --- Preflight ---
    if not args.skip_preflight:
        print("Preflight checks...")
        warnings = preflight(args.url)
        if warnings:
            for w in warnings:
                print(f"  WARNING: {w}")
        else:
            print("  All checks passed.")
        print()

    # --- Verify models ---
    print("Checking models...")
    ready = ensure_models(needed_models, auto_pull=not args.no_pull)

    # Remove unavailable models from config
    for role in list(models_config.keys()):
        model = models_config[role]
        if model and model not in ready:
            print(f"  WARNING: {model} unavailable, disabling {role} pass")
            models_config[role] = None

    if not models_config.get("vision"):
        print("ERROR: No vision model available. Run --setup first.")
        return 1

    print()

    # --- Run audit ---
    report = run_audit(args.url, views, resolutions, models_config, output_dir)

    # --- Generate reports ---
    print(f"\n{'='*70}")
    print("  GENERATING REPORTS")
    print(f"{'='*70}")
    generate_report(report, output_dir)

    # --- Print summary ---
    print(f"\n{'='*70}")
    print("  AUDIT COMPLETE")
    print(f"{'='*70}")
    total_issues = sum(len(r.issues) for r in report.results)
    blanks = sum(1 for r in report.results if r.is_blank)
    print(f"  Duration:    {report.total_time / 60:.1f} minutes")
    print(f"  Screenshots: {len(report.results)}")
    if blanks:
        print(f"  Blanks:      {blanks}")
    print(f"  Issues:      {total_issues}")
    print(f"  Models used: {', '.join(report.models_used)}")
    print(f"  Reports:     {output_dir}/audit_report.md")
    print(f"               {output_dir}/audit_report.json")

    return 1 if blanks > 0 else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
