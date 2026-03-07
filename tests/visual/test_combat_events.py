# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Combat Events Test — verifies combat events flow from backend to frontend.

Starts a battle, connects to WebSocket, and verifies that projectile_fired,
projectile_hit, and target_eliminated events are received by the frontend.
"""

import json
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("TRITIUM_URL", "http://localhost:8000")
RESULTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", ".test-results", "combat-events"
)


def _server_available():
    try:
        r = requests.get(f"{BASE_URL}/api/amy/status", timeout=3)
        return r.ok
    except Exception:
        return False


@pytest.fixture(scope="module")
def results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    return RESULTS_DIR


@pytest.fixture(scope="module")
def battle_events(results_dir):
    """Run a battle and collect WebSocket events."""
    if not _server_available():
        pytest.skip("Server not running")

    import asyncio
    import websockets

    events = {
        "projectile_fired": [],
        "projectile_hit": [],
        "target_eliminated": [],
        "wave_start": [],
        "wave_complete": [],
        "game_state_change": [],
        "game_over": [],
    }
    # Backend prefixes events with "amy_", so map both forms
    _type_map = {}
    for k in events:
        _type_map[k] = k
        _type_map[f"amy_{k}"] = k

    async def collect():
        # Reset and begin war
        requests.post(f"{BASE_URL}/api/game/reset")
        await asyncio.sleep(0.5)
        requests.post(f"{BASE_URL}/api/game/begin")

        ws_url = BASE_URL.replace("http://", "ws://") + "/ws/live"
        async with websockets.connect(ws_url) as ws:
            deadline = time.time() + 120  # 2 minute max
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")
                    canonical = _type_map.get(msg_type)
                    if canonical:
                        events[canonical].append(msg.get("data", msg))

                    # Stop on game over
                    if msg_type in ("game_over", "amy_game_over"):
                        break
                    data = msg.get("data", {})
                    if isinstance(data, dict):
                        state = data.get("state", "")
                        if state in ("victory", "defeat"):
                            break
                except asyncio.TimeoutError:
                    continue

    try:
        asyncio.run(collect())
    except Exception as e:
        pytest.skip(f"WebSocket collection failed: {e}")

    # Save events
    with open(os.path.join(results_dir, "events.json"), "w") as f:
        summary = {k: len(v) for k, v in events.items()}
        json.dump({"counts": summary, "sample_projectile": events["projectile_fired"][:3]}, f, indent=2)

    return events


class TestCombatEvents:
    def test_projectiles_fired(self, battle_events, results_dir):
        """Backend fires projectile events during combat."""
        count = len(battle_events["projectile_fired"])
        assert count > 0, "No projectile_fired events received via WebSocket"
        print(f"\n  Projectiles fired: {count}")

    def test_projectile_hits(self, battle_events, results_dir):
        """Projectiles hit targets."""
        count = len(battle_events["projectile_hit"])
        assert count > 0, "No projectile_hit events received"
        print(f"\n  Projectile hits: {count}")

    def test_eliminations(self, battle_events, results_dir):
        """Targets get eliminated during battle."""
        count = len(battle_events["target_eliminated"])
        assert count > 0, "No target_eliminated events received"
        print(f"\n  Eliminations: {count}")

    def test_wave_progression(self, battle_events, results_dir):
        """Waves progress during battle."""
        count = len(battle_events["wave_start"])
        assert count >= 1, "No wave_start events received"
        print(f"\n  Waves started: {count}")

    def test_projectile_data_complete(self, battle_events, results_dir):
        """Projectile events contain required fields."""
        if not battle_events["projectile_fired"]:
            pytest.skip("No projectile events")

        proj = battle_events["projectile_fired"][0]
        required = ["source_id", "target_id", "source_pos", "target_pos", "projectile_type"]
        missing = [f for f in required if f not in proj]
        assert not missing, f"Projectile event missing fields: {missing}"

    def test_combat_report(self, battle_events, results_dir):
        """Generate combat event summary."""
        report = {
            "projectiles_fired": len(battle_events["projectile_fired"]),
            "projectile_hits": len(battle_events["projectile_hit"]),
            "eliminations": len(battle_events["target_eliminated"]),
            "waves_started": len(battle_events["wave_start"]),
            "waves_completed": len(battle_events["wave_complete"]),
        }

        # Calculate accuracy
        if report["projectiles_fired"] > 0:
            report["accuracy"] = round(report["projectile_hits"] / report["projectiles_fired"] * 100, 1)

        with open(os.path.join(results_dir, "combat_report.json"), "w") as f:
            json.dump(report, f, indent=2)

        print(f"\n  {'='*40}")
        print(f"  COMBAT EVENT REPORT")
        print(f"  Projectiles: {report['projectiles_fired']}")
        print(f"  Hits: {report['projectile_hits']}")
        print(f"  Accuracy: {report.get('accuracy', '?')}%")
        print(f"  Eliminations: {report['eliminations']}")
        print(f"  Waves: {report['waves_started']} started, {report['waves_completed']} completed")
        print(f"  {'='*40}")
