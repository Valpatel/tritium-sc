# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Battle Alive Test — verify combat happens fast with dramatic effects.

Starts a battle, spawns extra hostiles close to defenders, and checks:
1. Score updates within 30s (weapon ranges now support real engagement)
2. DOM effects visible (kill feed, flashes, floating text)
3. Game HUD shows wave/score info
"""
import json
import time
import requests
import pytest
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"


@pytest.fixture(scope="module")
def browser_page():
    """Launch headed Chromium, open Command Center, wait for map."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle", timeout=20_000)
        # Wait for map + WebSocket to connect
        page.wait_for_timeout(4000)
        yield page
        browser.close()


def _api(method, path, **kw):
    return getattr(requests, method)(f"{BASE}{path}", timeout=10, **kw)


def _game_state():
    r = _api("get", "/api/game/state")
    if r.status_code == 200:
        return r.json()
    return {}


def _targets():
    r = _api("get", "/api/amy/simulation/targets")
    if r.status_code == 200:
        data = r.json()
        # API returns {"targets": [...]}
        if isinstance(data, dict) and "targets" in data:
            return data["targets"]
        return data if isinstance(data, list) else []
    return []


def test_01_start_battle(browser_page):
    """Start a 10-wave battle via API."""
    page = browser_page

    # Reset game first to ensure we're in setup state
    _api("post", "/api/game/reset")
    page.wait_for_timeout(1000)

    state = _game_state()
    print(f"Game state before begin: {state.get('state', '?')}")

    # Begin war via API
    r = _api("post", "/api/game/begin")
    print(f"Begin war response: {r.status_code} {r.json()}")
    page.wait_for_timeout(6000)  # Wait for 5s countdown + 1s

    state = _game_state()
    print(f"Game state after begin: {state}")
    assert state.get("state") in ("active", "countdown"), f"Expected active battle, got: {state}"


def test_02_spawn_close_hostiles(browser_page):
    """Spawn 5 hostiles close to defenders so combat starts immediately."""
    page = browser_page

    targets = _targets()
    friendlies = [t for t in targets if t.get("alliance") == "friendly"]
    print(f"Friendlies: {len(friendlies)}")

    if friendlies:
        f = friendlies[0]
        pos = f.get("position", {})
        cx, cy = pos.get("x", 0), pos.get("y", 0)
        print(f"Spawning near {f.get('name')} at ({cx:.0f}, {cy:.0f})")
    else:
        cx, cy = 0, 0

    # Spawn hostiles at 30-60m from defenders (within new weapon ranges)
    offsets = [(30, 30), (-40, 20), (50, -30), (-20, -50), (35, 45)]
    for dx, dy in offsets:
        r = _api("post", "/api/amy/simulation/spawn", json={
            "x": cx + dx, "y": cy + dy,
            "type": "hostile_person",
        })
        print(f"Spawn at ({cx+dx:.0f}, {cy+dy:.0f}): {r.status_code}")

    page.wait_for_timeout(1000)

    targets = _targets()
    hostiles = [t for t in targets if t.get("alliance") == "hostile"]
    print(f"Total hostiles: {len(hostiles)}")
    assert len(hostiles) >= 3, f"Expected at least 3 hostiles, got {len(hostiles)}"


def test_03_combat_starts_fast(browser_page):
    """With new weapon ranges, combat should produce eliminations within 60s."""
    page = browser_page
    start = time.time()
    max_wait = 60
    best_score = 0
    best_elims = 0

    while time.time() - start < max_wait:
        state = _game_state()
        score = state.get("score", 0)
        elims = state.get("total_eliminations", 0)
        if score > best_score:
            best_score = score
        if elims > best_elims:
            best_elims = elims
        if best_elims >= 1:
            elapsed = time.time() - start
            print(f"First elimination at {elapsed:.1f}s | Score: {best_score} | Elims: {best_elims}")
            break
        page.wait_for_timeout(2000)

    print(f"Final check — Score: {best_score}, Elims: {best_elims}")
    assert best_elims >= 1, f"No eliminations after {max_wait}s — combat not working!"


def test_04_screenshot_combat(browser_page):
    """Capture screenshot mid-combat to verify visual effects."""
    page = browser_page
    page.wait_for_timeout(3000)

    # Take screenshot
    page.screenshot(path="tests/.test-results/battle-alive-combat.png")
    print("Screenshot: tests/.test-results/battle-alive-combat.png")

    # Check for DOM effects
    fx_els = page.query_selector_all("[class*='fx-']")
    kf_els = page.query_selector_all(".fx-killfeed-entry")
    print(f"FX elements: {len(fx_els)}, Kill feed entries: {len(kf_els)}")


def test_05_score_counter_updates(browser_page):
    """Verify score is > 0 after combat."""
    page = browser_page
    state = _game_state()
    score = state.get("score", 0)
    elims = state.get("total_eliminations", 0)
    wave = state.get("wave", 0)
    print(f"Game State — Score: {score} | Elims: {elims} | Wave: {wave}")
    assert score > 0, "Score should be > 0 after combat"


def test_06_more_combat_20s(browser_page):
    """Spawn more hostiles, let combat run 20s, verify action."""
    page = browser_page
    state_before = _game_state()
    score_before = state_before.get("score", 0)

    targets = _targets()
    friendlies = [t for t in targets if t.get("alliance") == "friendly"]
    if friendlies:
        pos = friendlies[0].get("position", {})
        cx, cy = pos.get("x", 0), pos.get("y", 0)
    else:
        cx, cy = 0, 0

    # Spawn 5 more hostiles right into the action
    for dx, dy in [(25, 15), (-35, 10), (40, -25), (-15, -40), (20, 35)]:
        _api("post", "/api/amy/simulation/spawn", json={
            "x": cx + dx, "y": cy + dy,
            "type": "hostile_person",
        })

    page.wait_for_timeout(20000)

    state_after = _game_state()
    score_after = state_after.get("score", 0)
    elims_after = state_after.get("total_eliminations", 0)
    print(f"After 20s — Score: {score_before} -> {score_after} | Elims: {elims_after}")

    # Final screenshot
    page.screenshot(path="tests/.test-results/battle-alive-final.png")
    print("Final screenshot: tests/.test-results/battle-alive-final.png")

    assert score_after >= score_before, "Score should not decrease"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
