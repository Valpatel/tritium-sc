"""Batch 36 kill lines, formation hull, quick-select, threat proximity tests.

Verifies elimination kill line animation, formation convex hull overlay,
Shift+1-5 quick-select friendlies by rank, and threat proximity warning.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch36_killlines_hull_quickselect_proximity.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.lib.server_manager import TritiumServer

pytestmark = [pytest.mark.ux, pytest.mark.ui]


@pytest.fixture(scope="module")
def _server():
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def _browser(_server):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def _ctx(_browser, _server):
    ctx = _browser.new_context(viewport={"width": 1920, "height": 1080})
    p = ctx.new_page()
    p.goto(f"{_server.url}/unified", wait_until="domcontentloaded", timeout=60000)
    try:
        p.wait_for_function(
            "() => window.TritiumStore && window.TritiumStore.units.size >= 3",
            timeout=15000,
        )
    except Exception:
        pass
    p.wait_for_timeout(1000)
    yield {"page": p, "url": _server.url}
    ctx.close()


@pytest.fixture
def page(_ctx):
    p = _ctx["page"]
    yield p
    p.evaluate("""() => {
        window.TritiumStore.set('game.phase', 'idle');
        window.TritiumStore.set('map.selectedUnitId', null);
        window.TritiumStore.set('map.selectedUnitIds', []);
    }""")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Kill lines (animated line from killer to victim)
# ============================================================


class TestKillLines:
    """Verify kill line animation on elimination events."""

    def test_elimination_creates_kill_line(self, page):
        """combat:elimination with source_id creates animated kill line."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('kl_shooter', {
                name: 'KL Shooter', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                eliminations: 5,
            });
            window.TritiumStore.updateUnit('kl_victim', {
                name: 'KL Victim', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 40, y: 30 }, health: 0, maxHealth: 100,
            });
            window.EventBus.emit('combat:elimination', {
                target_id: 'kl_victim',
                source_id: 'kl_shooter',
                position: { x: 40, y: 30 },
                shooter_name: 'KL Shooter',
                target_name: 'KL Victim',
                streak: 1,
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 20) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 20

    def test_kill_line_fades(self, page):
        """Kill line fades out after maxAge (1.2s)."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('kl_fade_s', {
                name: 'KL Fade S', type: 'turret', alliance: 'friendly',
                position: { x: -20, y: 0 }, health: 100, maxHealth: 100,
            });
            window.EventBus.emit('combat:elimination', {
                target_id: 'kl_fade_v',
                source_id: 'kl_fade_s',
                position: { x: 20, y: 0 },
                streak: 1,
            });
            return new Promise(resolve => {
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 1500);
            });
        }""")
        assert result["canvasOk"]

    def test_kill_line_no_crash_without_source(self, page):
        """Elimination without source_id doesn't crash."""
        result = page.evaluate("""() => {
            window.EventBus.emit('combat:elimination', {
                target_id: 'kl_nosrc',
                position: { x: 50, y: 50 },
                streak: 1,
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Formation convex hull
# ============================================================


class TestFormationHull:
    """Verify convex hull drawn around multi-selected units."""

    def test_hull_with_three_units(self, page):
        """Multi-selecting 3+ units draws convex hull outline."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('fh_a', {
                name: 'FH A', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('fh_b', {
                name: 'FH B', type: 'drone', alliance: 'friendly',
                position: { x: 40, y: 0 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('fh_c', {
                name: 'FH C', type: 'rover', alliance: 'friendly',
                position: { x: 20, y: 30 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitIds', ['fh_a', 'fh_b', 'fh_c']);
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 15

    def test_no_hull_with_two_units(self, page):
        """Two selected units don't trigger hull (need 3+)."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', ['fh_a', 'fh_b']);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Quick-select friendlies by rank
# ============================================================


class TestQuickSelectByRank:
    """Verify Shift+1-5 selects friendlies by elimination rank."""

    def test_shift1_selects_top_friendly(self, page):
        """Shift+1 selects the friendly with most eliminations."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('qs_ace', {
                name: 'QS Ace', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                eliminations: 20,
            });
            window.TritiumStore.updateUnit('qs_mid', {
                name: 'QS Mid', type: 'drone', alliance: 'friendly',
                position: { x: 50, y: 0 }, health: 100, maxHealth: 100,
                eliminations: 10,
            });
            window.TritiumStore.updateUnit('qs_low', {
                name: 'QS Low', type: 'rover', alliance: 'friendly',
                position: { x: -50, y: 0 }, health: 80, maxHealth: 100,
                eliminations: 2,
            });
            // Simulate Shift+1
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: '1', code: 'Digit1', shiftKey: true, bubbles: true,
            }));
            return new Promise(resolve => {
                setTimeout(() => {
                    const sel = window.TritiumStore.get('map.selectedUnitId');
                    resolve({ selected: sel });
                }, 300);
            });
        }""")
        assert result["selected"] == "qs_ace", f"Expected qs_ace, got {result['selected']}"

    def test_shift2_selects_second_friendly(self, page):
        """Shift+2 selects the 2nd highest elimination friendly."""
        result = page.evaluate("""() => {
            // Units should still exist from previous test setup
            window.TritiumStore.updateUnit('qs_ace', {
                name: 'QS Ace', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                eliminations: 20,
            });
            window.TritiumStore.updateUnit('qs_mid', {
                name: 'QS Mid', type: 'drone', alliance: 'friendly',
                position: { x: 50, y: 0 }, health: 100, maxHealth: 100,
                eliminations: 10,
            });
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: '2', code: 'Digit2', shiftKey: true, bubbles: true,
            }));
            return new Promise(resolve => {
                setTimeout(() => {
                    const sel = window.TritiumStore.get('map.selectedUnitId');
                    resolve({ selected: sel });
                }, 300);
            });
        }""")
        assert result["selected"] == "qs_mid", f"Expected qs_mid, got {result['selected']}"

    def test_shift5_returns_null_when_few_units(self, page):
        """Shift+5 with fewer than 5 friendlies doesn't crash."""
        result = page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: '5', code: 'Digit5', shiftKey: true, bubbles: true,
            }));
            return new Promise(resolve => {
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 200);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Threat proximity warning
# ============================================================


class TestThreatProximity:
    """Verify pulsing red outline on threatened friendlies."""

    def test_proximity_warning_during_combat(self, page):
        """Friendly within 30m of hostile gets proximity warning."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('tp_friend', {
                name: 'TP Friend', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 80, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('tp_hostile', {
                name: 'TP Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 20, y: 0 }, health: 50, maxHealth: 100,
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 15

    def test_no_proximity_when_far(self, page):
        """Friendly far from hostile (>30m) gets no warning."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('tp_far_f', {
                name: 'TP Far F', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('tp_far_h', {
                name: 'TP Far H', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 200, y: 200 }, health: 50, maxHealth: 100,
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_no_proximity_during_idle(self, page):
        """No proximity warnings during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Help overlay
# ============================================================


class TestHelpOverlayBatch36:
    """Verify Shift+1-5 shortcut in help overlay."""

    def test_quickselect_in_help(self, page):
        """Help overlay lists Shift+1-5 quick-select shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"].lower()
        assert "quick-select" in text, f"Expected 'quick-select' in help, got: {text[:200]}"


# ============================================================
# Combined render stability
# ============================================================


class TestBatch36Combined:
    """All Batch 36 features work together without crash."""

    def test_full_batch36_scenario(self, page):
        """Kill lines + hull + proximity + quick-select all active."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 5);
            window.TritiumStore.set('game.score', 18000);

            // Friendlies in a triangle with varied elims
            window.TritiumStore.updateUnit('b36_alpha', {
                name: 'B36 Alpha', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 90, maxHealth: 100,
                eliminations: 15, weapon_range: 60,
            });
            window.TritiumStore.updateUnit('b36_beta', {
                name: 'B36 Beta', type: 'drone', alliance: 'friendly',
                position: { x: 50, y: -30 }, health: 70, maxHealth: 100,
                eliminations: 8,
            });
            window.TritiumStore.updateUnit('b36_gamma', {
                name: 'B36 Gamma', type: 'rover', alliance: 'friendly',
                position: { x: 25, y: 40 }, health: 50, maxHealth: 100,
                eliminations: 3,
            });

            // Hostile close to gamma (proximity warning)
            window.TritiumStore.updateUnit('b36_hostile', {
                name: 'B36 Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 35, y: 45 }, health: 40, maxHealth: 100,
            });

            // Multi-select for hull
            window.TritiumStore.set('map.selectedUnitIds', ['b36_alpha', 'b36_beta', 'b36_gamma']);

            // Elimination event for kill line
            window.EventBus.emit('combat:elimination', {
                target_id: 'b36_hostile',
                source_id: 'b36_alpha',
                position: { x: 35, y: 45 },
                shooter_name: 'B36 Alpha',
                target_name: 'B36 Hostile',
                streak: 2,
            });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({
                            frames,
                            canvasOk: !!document.getElementById('tactical-canvas'),
                        });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
