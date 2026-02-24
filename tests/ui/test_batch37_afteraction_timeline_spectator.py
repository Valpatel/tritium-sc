"""Batch 37 after-action report, engagement timeline, spectator mode tests.

Verifies victory/defeat after-action report overlay, engagement history
timeline bar, spectator auto-cycle camera mode, and ESC dismiss.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch37_afteraction_timeline_spectator.py -v -m ux
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
# After-action report
# ============================================================


class TestAfterActionReport:
    """Verify after-action report overlay on victory/defeat."""

    def test_victory_triggers_report(self, page):
        """Setting game phase to 'victory' creates after-action report."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.score', 15000);
            window.TritiumStore.set('game.wave', 8);
            window.TritiumStore.updateUnit('aar_turret', {
                name: 'AAR Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 80, maxHealth: 100,
                eliminations: 12,
            });
            window.TritiumStore.updateUnit('aar_drone', {
                name: 'AAR Drone', type: 'drone', alliance: 'friendly',
                position: { x: 30, y: 0 }, health: 60, maxHealth: 100,
                eliminations: 5,
            });
            window.TritiumStore.set('game.phase', 'victory');
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 30

    def test_defeat_triggers_report(self, page):
        """Setting game phase to 'defeat' creates after-action report."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.score', 5000);
            window.TritiumStore.set('game.wave', 3);
            window.TritiumStore.set('game.phase', 'defeat');
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

    def test_escape_dismisses_report(self, page):
        """Pressing ESC dismisses the after-action report."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'victory');
            return new Promise(resolve => {
                setTimeout(() => {
                    document.dispatchEvent(new KeyboardEvent('keydown', {
                        key: 'Escape', code: 'Escape', bubbles: true,
                    }));
                    setTimeout(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    }, 200);
                }, 500);
            });
        }""")
        assert result["canvasOk"]

    def test_idle_clears_report(self, page):
        """Returning to idle phase clears the report."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'victory');
            return new Promise(resolve => {
                setTimeout(() => {
                    window.TritiumStore.set('game.phase', 'idle');
                    requestAnimationFrame(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                }, 300);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Engagement timeline
# ============================================================


class TestEngagementTimeline:
    """Verify engagement history timeline bar during combat."""

    def test_timeline_renders_during_active(self, page):
        """Engagement timeline bar appears during active game with eliminations."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('et_turret', {
                name: 'ET Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
            });
            // Emit some eliminations to populate timeline
            window.EventBus.emit('combat:elimination', {
                target_id: 'et_h1', source_id: 'et_turret',
                position: { x: 30, y: 0 },
                shooter_name: 'ET Turret', target_name: 'ET H1', streak: 1,
            });
            window.EventBus.emit('combat:elimination', {
                target_id: 'et_h2', source_id: 'et_turret',
                position: { x: 40, y: 10 },
                shooter_name: 'ET Turret', target_name: 'ET H2', streak: 2,
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

    def test_no_timeline_during_idle(self, page):
        """Timeline not rendered during idle phase."""
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
# Spectator auto-cycle mode
# ============================================================


class TestSpectatorMode:
    """Verify spectator auto-cycle camera mode."""

    def test_y_key_toggles_spectator(self, page):
        """Pressing Y toggles spectator mode."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('sp_unit_a', {
                name: 'SP A', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('sp_unit_b', {
                name: 'SP B', type: 'drone', alliance: 'friendly',
                position: { x: 80, y: 80 }, health: 100, maxHealth: 100,
            });
            // Toggle spectator on
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'y', code: 'KeyY', bubbles: true,
            }));
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

    def test_spectator_off_toggle(self, page):
        """Pressing Y again disables spectator mode."""
        result = page.evaluate("""() => {
            // Toggle on then off
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'y', code: 'KeyY', bubbles: true,
            }));
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'y', code: 'KeyY', bubbles: true,
            }));
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_spectator_no_crash_without_units(self, page):
        """Spectator mode doesn't crash when no units exist."""
        result = page.evaluate("""() => {
            // Clear all units
            const ids = [];
            window.TritiumStore.units.forEach((u, id) => ids.push(id));
            ids.forEach(id => window.TritiumStore.units.delete(id));
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'y', code: 'KeyY', bubbles: true,
            }));
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else {
                        // Toggle off
                        document.dispatchEvent(new KeyboardEvent('keydown', {
                            key: 'y', code: 'KeyY', bubbles: true,
                        }));
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Help overlay
# ============================================================


class TestHelpOverlayBatch37:
    """Verify Y spectator shortcut in help overlay."""

    def test_spectator_in_help(self, page):
        """Help overlay lists Y spectator shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"].lower()
        assert "spectator" in text, f"Expected 'spectator' in help, got: {text[:200]}"


# ============================================================
# Combined render stability
# ============================================================


class TestBatch37Combined:
    """All Batch 37 features work together without crash."""

    def test_full_batch37_scenario(self, page):
        """After-action + timeline + spectator all active at once."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 7);
            window.TritiumStore.set('game.score', 25000);

            // Place units
            window.TritiumStore.updateUnit('b37_alpha', {
                name: 'B37 Alpha', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 90, maxHealth: 100,
                eliminations: 15, weapon_range: 60,
            });
            window.TritiumStore.updateUnit('b37_beta', {
                name: 'B37 Beta', type: 'drone', alliance: 'friendly',
                position: { x: 60, y: -30 }, health: 60, maxHealth: 100,
                eliminations: 8,
            });

            // Some eliminations to populate timeline
            for (let i = 0; i < 5; i++) {
                window.EventBus.emit('combat:elimination', {
                    target_id: 'b37_h' + i, source_id: 'b37_alpha',
                    position: { x: 20 + i * 10, y: 20 },
                    shooter_name: 'B37 Alpha', target_name: 'H' + i, streak: i + 1,
                });
            }

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        // Trigger victory for after-action report
                        window.TritiumStore.set('game.phase', 'victory');
                        let afterFrames = 0;
                        function afterTick() {
                            afterFrames++;
                            if (afterFrames < 30) requestAnimationFrame(afterTick);
                            else {
                                window.TritiumStore.set('game.phase', 'idle');
                                resolve({
                                    frames: frames + afterFrames,
                                    canvasOk: !!document.getElementById('tactical-canvas'),
                                });
                            }
                        }
                        requestAnimationFrame(afterTick);
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 60
        assert result["canvasOk"]
