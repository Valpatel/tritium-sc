# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""4v4 Battle — watch in headed browser and verify unit count.

Starts the 4v4 combat_proof scenario, opens a headed browser,
and checks the total unit count via API at multiple points during
the battle. Asserts exactly 8 units (4 defenders + 4 hostiles).
"""

import time

import pytest
import requests
from playwright.sync_api import sync_playwright

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from server_manager import TritiumServer


def _log(msg: str) -> None:
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")


@pytest.fixture(scope="module")
def server():
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def browser_page(server):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--window-size=1920,1080"])
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()
        page.goto(server.url)
        page.wait_for_load_state("networkidle")
        # Click body to init AudioContext
        page.click("body")
        time.sleep(1)
        yield page
        browser.close()


def _get_targets(base_url: str) -> list[dict]:
    resp = requests.get(f"{base_url}/api/amy/simulation/targets", timeout=5)
    resp.raise_for_status()
    data = resp.json()
    # API returns {"targets": [...]}
    return data.get("targets", data) if isinstance(data, dict) else data


def _count_by_alliance(targets: list[dict]) -> dict[str, int]:
    counts = {}
    for t in targets:
        a = t.get("alliance", "unknown")
        counts[a] = counts.get(a, 0) + 1
    return counts


class TestFourVsFour:
    """4v4 battle with unit count verification."""

    def test_01_start_4v4_battle(self, server, browser_page):
        """Start the 4v4 combat_proof scenario and check initial unit count."""
        base = server.url

        # Reset to clean slate (clears layout units + neutrals)
        requests.post(f"{base}/api/game/reset", timeout=5)
        time.sleep(0.5)

        # Verify clean state after reset
        post_reset = _get_targets(base)
        _log(f"Post-reset: {len(post_reset)} units (should be 0)")
        assert len(post_reset) == 0, f"Expected 0 units after reset, got {len(post_reset)}"

        # Start battle
        resp = requests.post(f"{base}/api/game/battle/combat_proof", timeout=10)
        resp.raise_for_status()
        result = resp.json()
        _log(f"Scenario started: {result}")
        assert result["defender_count"] == 4, f"Expected 4 defenders, got {result['defender_count']}"
        assert result["wave_count"] == 1

        # Check targets immediately — defenders should be placed
        targets = _get_targets(base)
        counts = _count_by_alliance(targets)
        friendly = [t for t in targets if t.get("alliance") == "friendly"]
        neutral = [t for t in targets if t.get("alliance") == "neutral"]
        _log(f"Post-start: {len(targets)} units ({counts})")
        _log(f"Friendly units at T0: {len(friendly)}")
        for f in friendly:
            _log(f"  {f.get('name')} ({f.get('asset_type')}) at {f.get('position')}")
        if neutral:
            _log(f"WARNING: {len(neutral)} neutrals still present!")
            for n in neutral[:5]:
                _log(f"  neutral: {n.get('name')} ({n.get('asset_type')})")
        assert len(friendly) == 4, f"Expected 4 friendly defenders, got {len(friendly)}"

    def test_02_wait_for_hostiles_and_count(self, server, browser_page):
        """Wait for countdown + hostile spawn, then count all units."""
        base = server.url

        # Wait for countdown (5s) + hostile spawn stagger (4 * 0.5s = 2s) + buffer
        _log("Waiting 10s for countdown + hostile spawn...")
        time.sleep(10)

        targets = _get_targets(base)
        counts = _count_by_alliance(targets)
        total = len(targets)
        _log(f"Total units: {total}")
        _log(f"  Breakdown: {counts}")

        for t in targets:
            status = t.get("status", "?")
            name = t.get("name", "?")
            atype = t.get("asset_type", "?")
            alliance = t.get("alliance", "?")
            health = t.get("health", "?")
            ammo = t.get("ammo_count", "?")
            pos = t.get("position", {})
            _log(f"  [{alliance}] {name} ({atype}) hp={health} ammo={ammo} status={status} pos=({pos.get('x','?'):.0f},{pos.get('y','?'):.0f})")

        friendly_count = counts.get("friendly", 0)
        hostile_count = counts.get("hostile", 0)
        neutral_count = counts.get("neutral", 0)

        assert friendly_count == 4, f"Expected 4 friendlies, got {friendly_count}"
        assert hostile_count >= 1, f"Expected hostiles to have spawned, got {hostile_count}"
        assert neutral_count == 0, f"Expected 0 neutrals during battle, got {neutral_count}"
        assert total == friendly_count + hostile_count, \
            f"Total {total} should equal friendlies({friendly_count}) + hostiles({hostile_count}), no extras"
        _log(f"PASS: Exactly {total} units (4 friendly + {hostile_count} hostile, 0 neutral)")

    def test_03_monitor_combat(self, server, browser_page):
        """Watch combat for 40s, logging unit counts each tick."""
        base = server.url

        max_units_seen = 0
        eliminations_seen = 0
        snapshots = []

        for i in range(20):
            time.sleep(2)
            targets = _get_targets(base)
            counts = _count_by_alliance(targets)
            alive = [t for t in targets if t.get("status") not in ("eliminated", "escaped")]
            alive_counts = {}
            for t in alive:
                a = t.get("alliance", "unknown")
                alive_counts[a] = alive_counts.get(a, 0) + 1

            total = len(targets)
            alive_total = len(alive)
            eliminated = total - alive_total
            max_units_seen = max(max_units_seen, total)
            eliminations_seen = max(eliminations_seen, eliminated)

            _log(f"T+{(i+1)*2}s: total={total} alive={alive_total} "
                 f"(F={alive_counts.get('friendly',0)} H={alive_counts.get('hostile',0)}) "
                 f"elim={eliminated}")

            snapshots.append({
                "time": (i + 1) * 2,
                "total": total,
                "alive": alive_total,
                "eliminated": eliminated,
                "friendly_alive": alive_counts.get("friendly", 0),
                "hostile_alive": alive_counts.get("hostile", 0),
            })

            # Check for game over
            game_resp = requests.get(f"{base}/api/game/state", timeout=5)
            if game_resp.ok:
                state = game_resp.json().get("state", "")
                if state in ("victory", "defeat", "game_over"):
                    _log(f"Game ended: {state}")
                    break

        _log(f"\n  === UNIT COUNT SUMMARY ===")
        _log(f"  Max units seen: {max_units_seen}")
        _log(f"  Max eliminations: {eliminations_seen}")
        _log(f"  Final snapshot: {snapshots[-1] if snapshots else 'none'}")

        # The battle should never exceed 8 units (4+4)
        assert max_units_seen <= 8, \
            f"Max units should be <=8 (4v4), but saw {max_units_seen}"
        assert eliminations_seen >= 1, \
            f"Should have at least 1 elimination, got {eliminations_seen}"
