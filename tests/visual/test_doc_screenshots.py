# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Generate curated documentation screenshots for README and docs/.

Runs 6 battle scenarios with varied visual configurations (satellite,
roads, zoom, force composition) and uses burst-capture + OpenCV frame
scoring to pick the most action-packed frame from each scenario.

Usage:
    ./test.sh docs
    .venv/bin/python3 -m pytest tests/visual/test_doc_screenshots.py -v -s
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

from tests.combat_matrix.config_matrix import BattleConfig
from tests.combat_matrix.scenario_factory import write_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = PROJECT_ROOT / "docs" / "screenshots"
RESULTS_DIR = PROJECT_ROOT / "tests" / ".test-results" / "doc-screenshots"

# BGR colors matching the UI palette
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])   # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])      # #ff2a6d

DOC_SHOTS = [
    {
        "name": "command-center",
        "show_satellite": False,
        "show_roads": False,
        "zoom": None,
        "battle": None,
        "hide_panels": False,
        "caption": "Command Center -- tactical overview with panels and units",
    },
    {
        "name": "game-combat",
        "show_satellite": True,
        "show_roads": False,
        "zoom": "close",
        "battle": {
            "defenders": 4,
            "hostiles": 10,
            "mix": "mixed_ground",
            "map_bounds": 100.0,
        },
        "hide_panels": False,
        "caption": "Wave-based Nerf combat -- turrets engage hostile intruders",
    },
    {
        "name": "neighborhood-wide",
        "show_satellite": True,
        "show_roads": True,
        "zoom": "wide",
        "battle": None,
        "hide_panels": True,
        "caption": "Neighborhood overview -- satellite imagery at wide zoom",
    },
    {
        "name": "combat-close",
        "show_satellite": False,
        "show_roads": False,
        "zoom": "tight",
        "battle": {
            "defenders": 8,
            "hostiles": 8,
            "mix": "combined_arms",
            "map_bounds": 100.0,
        },
        "hide_panels": False,
        "caption": "Close-up combat -- combined arms engagement",
    },
    {
        "name": "combat-satellite",
        "show_satellite": True,
        "show_roads": True,
        "zoom": "medium",
        "battle": {
            "defenders": 4,
            "hostiles": 20,
            "mix": "all_turrets",
            "map_bounds": 100.0,
        },
        "hide_panels": False,
        "caption": "Turret defense -- satellite view with road overlay",
    },
    {
        "name": "combat-air",
        "show_satellite": False,
        "show_roads": False,
        "zoom": "medium",
        "battle": {
            "defenders": 4,
            "hostiles": 10,
            "mix": "air_support",
            "map_bounds": 100.0,
        },
        "hide_panels": False,
        "caption": "Air support -- drones and turrets in coordinated defense",
    },
]

# Defender mix type -> unit type cycle (matching config_matrix.DEFENDER_MIXES)
_MIXES = {
    "all_turrets": ["turret"],
    "all_mobile": ["rover", "drone"],
    "mixed_ground": ["turret", "rover", "tank", "apc"],
    "air_support": ["turret", "drone", "scout_drone", "drone"],
    "combined_arms": ["heavy_turret", "tank", "rover", "drone"],
}


def _count_color_pixels(
    img: np.ndarray, target_bgr: np.ndarray, tolerance: int = 50
) -> int:
    lower = np.clip(target_bgr.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(target_bgr.astype(int) + tolerance, 0, 255).astype(np.uint8)
    mask = cv2.inRange(img, lower, upper)
    return int(np.count_nonzero(mask))


def _score_combat_frame(img: np.ndarray) -> float:
    green = _count_color_pixels(img, FRIENDLY_GREEN_BGR, tolerance=50)
    red = _count_color_pixels(img, HOSTILE_RED_BGR, tolerance=60)
    return green + red * 2.0


def _get_targets(base_url: str) -> list[dict]:
    try:
        resp = requests.get(f"{base_url}/api/amy/simulation/targets", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("targets", [])
    except Exception:
        return []


def _make_battle_config(shot: dict) -> BattleConfig:
    battle = shot["battle"]
    mix_key = battle["mix"]
    count = battle["defenders"]
    cycle = _MIXES[mix_key]
    defender_types = [cycle[i % len(cycle)] for i in range(count)]
    config_id = f"doc_{shot['name']}"
    return BattleConfig(
        config_id=config_id,
        defender_count=count,
        defender_types=defender_types,
        hostile_count=battle["hostiles"],
        map_bounds=battle["map_bounds"],
    )


def _set_layers(page, show_satellite: bool, show_roads: bool) -> None:
    page.evaluate(f"""() => {{
        if (window.store) {{
            window.store.set('map.showSatellite', {str(show_satellite).lower()});
            window.store.set('map.showRoads', {str(show_roads).lower()});
        }}
        if (window.warState) {{
            window.warState.showSatellite = {str(show_satellite).lower()};
            window.warState.showRoads = {str(show_roads).lower()};
        }}
    }}""")


def _set_zoom(page, zoom_level: str | None, map_bounds: float = 100.0) -> None:
    if zoom_level is None:
        return
    zoom_map = {
        "wide": 0.3,
        "medium": 1.0,
        "close": max(1.0, 200.0 / map_bounds),
        "tight": max(2.0, 400.0 / map_bounds),
    }
    z = zoom_map.get(zoom_level, 1.0)
    page.evaluate(f"""() => {{
        if (window.warState && window.warState.cam) {{
            window.warState.cam.targetZoom = {z};
            window.warState.cam.zoom = {z};
            window.warState.cam.targetX = 0;
            window.warState.cam.targetY = 0;
            window.warState.cam.x = 0;
            window.warState.cam.y = 0;
        }}
    }}""")


def _hide_panels(page) -> None:
    page.evaluate("""() => {
        document.querySelectorAll('.panel').forEach(p => {
            p.style.display = 'none';
        });
    }""")


def _burst_capture(page, n: int = 10, interval_ms: int = 500) -> np.ndarray:
    """Capture n frames, return the one with the highest combat score."""
    best_score = -1.0
    best_img = None
    for _ in range(n):
        raw = page.screenshot()
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        score = _score_combat_frame(img)
        if score > best_score:
            best_score = score
            best_img = img
        page.wait_for_timeout(interval_ms)
    return best_img


def _save_jpg(img: np.ndarray, path: Path) -> None:
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])


def _generate_gallery(shots_info: list[dict]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for info in shots_info:
        rows.append(f"""
        <div class="shot">
            <img src="{info['path']}" alt="{info['name']}" loading="lazy">
            <div class="meta">
                <strong>{info['name']}.jpg</strong><br>
                {info['caption']}<br>
                {info['width']}x{info['height']} &mdash; {info['size_kb']}KB
            </div>
        </div>""")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>TRITIUM-SC Doc Screenshots</title>
<style>
  body {{
    background: #0a0a12; color: #e0e0e0; font-family: 'JetBrains Mono', monospace;
    margin: 0; padding: 20px;
  }}
  h1 {{ color: #00f0ff; border-bottom: 1px solid #00f0ff33; padding-bottom: 8px; }}
  .timestamp {{ color: #888; font-size: 0.85em; }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(580px, 1fr));
    gap: 16px; margin-top: 20px;
  }}
  .shot {{
    background: #12121f; border: 1px solid #00f0ff22; border-radius: 6px;
    overflow: hidden;
  }}
  .shot img {{ width: 100%; display: block; }}
  .meta {{ padding: 10px 14px; font-size: 0.85em; line-height: 1.5; }}
  .meta strong {{ color: #05ffa1; }}
</style>
</head>
<body>
<h1>TRITIUM-SC Doc Screenshots</h1>
<p class="timestamp">Generated: {now}</p>
<div class="grid">{''.join(rows)}
</div>
</body>
</html>"""

    gallery_path = RESULTS_DIR / "gallery.html"
    gallery_path.write_text(html)


def test_generate_doc_screenshots(tritium_server):
    """Generate 6 curated documentation screenshots."""
    from playwright.sync_api import sync_playwright

    base_url = tritium_server.url
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    shots_info = []

    try:
        for shot in DOC_SHOTS:
            name = shot["name"]
            print(f"\n--- {name} ---")

            # Reset game to clean state
            requests.post(f"{base_url}/api/game/reset", timeout=5)
            page.goto(f"{base_url}/", wait_until="networkidle")
            page.wait_for_timeout(2000)

            # Set layer visibility
            _set_layers(page, shot["show_satellite"], shot["show_roads"])

            if shot["hide_panels"]:
                _hide_panels(page)

            map_bounds = 100.0

            if shot["battle"] is not None:
                # Write scenario and start battle
                config = _make_battle_config(shot)
                map_bounds = config.map_bounds
                write_scenario(config)
                scenario_name = f"_matrix_doc_{name}"

                resp = requests.post(
                    f"{base_url}/api/game/battle/{scenario_name}",
                    timeout=10,
                )
                resp.raise_for_status()
                print(f"  Battle started: {resp.json().get('defender_count', '?')} defenders")

                # Wait for hostiles to appear (up to 20s)
                for tick in range(20):
                    time.sleep(1)
                    targets = _get_targets(base_url)
                    hostiles = [t for t in targets if t.get("alliance") == "hostile"]
                    if hostiles:
                        print(f"  Hostiles at t={tick}s: {len(hostiles)}")
                        break

                # Let combat develop
                page.wait_for_timeout(3000)

            # Set zoom after battle starts (so camera is in right position)
            _set_zoom(page, shot["zoom"], map_bounds)
            page.wait_for_timeout(1000)

            # Capture
            if shot["battle"] is not None:
                img = _burst_capture(page, n=10, interval_ms=500)
                print(f"  Burst score: {_score_combat_frame(img):.0f}")
            else:
                page.wait_for_timeout(2000)
                raw = page.screenshot()
                arr = np.frombuffer(raw, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            # Save as JPG
            jpg_path = DOCS_DIR / f"{name}.jpg"
            _save_jpg(img, jpg_path)
            size_kb = jpg_path.stat().st_size // 1024
            h, w = img.shape[:2]
            print(f"  Saved: {jpg_path} ({w}x{h}, {size_kb}KB)")

            shots_info.append({
                "name": name,
                "caption": shot["caption"],
                "path": str(jpg_path.resolve()),
                "width": w,
                "height": h,
                "size_kb": size_kb,
            })

            # Verify non-trivial image
            assert img is not None, f"Failed to capture {name}"
            assert w == 1920 and h == 1080, f"Wrong resolution for {name}: {w}x{h}"

            # Combat shots should have visible units
            if shot["battle"] is not None:
                score = _score_combat_frame(img)
                assert score > 0, f"No visible units in combat shot {name}"

        # Generate gallery report
        _generate_gallery(shots_info)
        print(f"\nGallery: {RESULTS_DIR / 'gallery.html'}")

        # Final summary
        print("\n" + "=" * 60)
        print("  DOC SCREENSHOTS COMPLETE")
        print("=" * 60)
        for info in shots_info:
            print(f"  {info['name']:25s} {info['width']}x{info['height']}  {info['size_kb']}KB")
        print("=" * 60)

    finally:
        browser.close()
        pw.stop()
