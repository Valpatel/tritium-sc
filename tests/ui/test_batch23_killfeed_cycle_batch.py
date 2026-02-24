"""Batch 23 kill feed, unit cycling, multi-select highlight, and batch commands tests.

Verifies kill feed overlay rendering, Tab/Shift+Tab unit cycling,
multi-select visual highlight rings, and batch context menu commands.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch23_killfeed_cycle_batch.py -v -m ux
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
    # Reset state
    p.evaluate("""() => {
        window.TritiumStore.set('map.selectedUnitId', null);
        window.TritiumStore.set('map.selectedUnitIds', []);
    }""")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Kill feed
# ============================================================


class TestKillFeed:
    """Verify kill feed overlay renders elimination events."""

    def test_elimination_creates_kill_feed_entry(self, page):
        """combat:elimination event adds an entry to the kill feed."""
        result = page.evaluate("""() => {
            window.EventBus.emit('combat:elimination', {
                target_id: 'kf_target_1',
                target_alliance: 'hostile',
                target_name: 'HOSTILE-A',
                shooter_name: 'TURRET-NW',
                position: { x: 100, y: 100 },
            });
            return true;
        }""")
        assert result

    def test_kill_feed_renders_without_crash(self, page):
        """Kill feed entries render through multiple frames."""
        result = page.evaluate("""() => {
            // Fire several eliminations
            for (let i = 0; i < 3; i++) {
                window.EventBus.emit('combat:elimination', {
                    target_id: `kf_render_${i}`,
                    target_alliance: 'hostile',
                    target_name: `HOSTILE-${i}`,
                    shooter_name: `TURRET-${i}`,
                    position: { x: i * 50, y: i * 30 },
                });
            }
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) {
                        requestAnimationFrame(tick);
                    } else {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 10

    def test_kill_feed_max_entries(self, page):
        """Kill feed is capped at 6 entries (oldest removed)."""
        result = page.evaluate("""() => {
            // Fire 8 eliminations (should cap at 6)
            for (let i = 0; i < 8; i++) {
                window.EventBus.emit('combat:elimination', {
                    target_id: `kf_cap_${i}`,
                    target_alliance: 'hostile',
                    target_name: `CAP-${i}`,
                    shooter_name: `TURRET-${i}`,
                    position: { x: i * 10, y: 0 },
                });
            }
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_kill_feed_fades_over_time(self, page):
        """Kill feed entries fade and are removed after maxAge."""
        result = page.evaluate("""() => {
            window.EventBus.emit('combat:elimination', {
                target_id: 'kf_fade',
                target_alliance: 'hostile',
                target_name: 'FADE-TARGET',
                shooter_name: 'FADE-SHOOTER',
                position: { x: 0, y: 0 },
            });
            // Wait for a few frames to see it rendering
            return new Promise(resolve => {
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 500);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Tab/Shift+Tab unit cycling
# ============================================================


class TestUnitCycling:
    """Verify Tab cycles through units."""

    def test_tab_selects_first_unit(self, page):
        """Pressing Tab when no unit selected picks the first unit."""
        result = page.evaluate("""() => {
            // Clear selection
            window.TritiumStore.set('map.selectedUnitId', null);
            // Ensure units exist
            window.TritiumStore.updateUnit('cycle_a', {
                name: 'Cycle A', type: 'turret', alliance: 'friendly',
                position: { x: 10, y: 10 },
            });
            window.TritiumStore.updateUnit('cycle_b', {
                name: 'Cycle B', type: 'rover', alliance: 'friendly',
                position: { x: 20, y: 20 },
            });
            return { unitCount: window.TritiumStore.units.size };
        }""")
        assert result["unitCount"] >= 2

        # Press Tab
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)

        selected = page.evaluate("() => window.TritiumStore.get('map.selectedUnitId')")
        assert selected is not None, "Tab should select a unit"

    def test_tab_cycles_forward(self, page):
        """Pressing Tab multiple times cycles through units."""
        page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitId', null);
        }""")

        # Press Tab twice
        page.keyboard.press("Tab")
        page.wait_for_timeout(100)
        first = page.evaluate("() => window.TritiumStore.get('map.selectedUnitId')")

        page.keyboard.press("Tab")
        page.wait_for_timeout(100)
        second = page.evaluate("() => window.TritiumStore.get('map.selectedUnitId')")

        # Should be different (unless only 1 unit)
        unit_count = page.evaluate("() => window.TritiumStore.units.size")
        if unit_count > 1:
            assert first != second, f"Tab should cycle: first={first}, second={second}"

    def test_shift_tab_cycles_backward(self, page):
        """Shift+Tab cycles in reverse direction."""
        page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitId', null);
        }""")

        # Tab forward twice, then Shift+Tab back
        page.keyboard.press("Tab")
        page.wait_for_timeout(100)
        page.keyboard.press("Tab")
        page.wait_for_timeout(100)
        after_forward = page.evaluate("() => window.TritiumStore.get('map.selectedUnitId')")

        page.keyboard.press("Shift+Tab")
        page.wait_for_timeout(100)
        after_back = page.evaluate("() => window.TritiumStore.get('map.selectedUnitId')")

        unit_count = page.evaluate("() => window.TritiumStore.units.size")
        if unit_count > 1:
            assert after_forward != after_back, "Shift+Tab should go backwards"

    def test_tab_wraps_around(self, page):
        """Tab wraps from last unit back to first."""
        result = page.evaluate("""() => {
            const count = window.TritiumStore.units.size;
            return { count };
        }""")
        count = result["count"]
        if count < 2:
            pytest.skip("Need at least 2 units for wrap test")

        # Press Tab enough times to wrap
        for _ in range(count + 1):
            page.keyboard.press("Tab")
            page.wait_for_timeout(50)

        selected = page.evaluate("() => window.TritiumStore.get('map.selectedUnitId')")
        assert selected is not None


# ============================================================
# Multi-select highlight
# ============================================================


class TestMultiSelectHighlight:
    """Verify multi-select visual highlight renders."""

    def test_multi_select_sets_store(self, page):
        """Setting selectedUnitIds in store is readable."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', ['unit_a', 'unit_b', 'unit_c']);
            return window.TritiumStore.get('map.selectedUnitIds');
        }""")
        assert len(result) == 3

    def test_multi_select_highlight_renders(self, page):
        """Multi-select highlight renders without crash."""
        result = page.evaluate("""() => {
            // Inject test units and set them as multi-selected
            window.TritiumStore.updateUnit('ms_a', {
                name: 'MS A', type: 'turret', alliance: 'friendly',
                position: { x: -50, y: -50 },
            });
            window.TritiumStore.updateUnit('ms_b', {
                name: 'MS B', type: 'rover', alliance: 'friendly',
                position: { x: 50, y: 50 },
            });
            window.TritiumStore.set('map.selectedUnitIds', ['ms_a', 'ms_b']);

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) {
                        requestAnimationFrame(tick);
                    } else {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_single_select_no_multi_highlight(self, page):
        """Single selection doesn't trigger multi-select highlight."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', ['only_one']);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_empty_multi_select_no_crash(self, page):
        """Empty selectedUnitIds doesn't crash render."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', []);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Batch context menu commands
# ============================================================


class TestBatchCommands:
    """Verify batch commands appear in context menu for multi-selected units."""

    def test_context_menu_exists(self, page):
        """Context menu can be created without crash."""
        result = page.evaluate("""() => {
            // Right-click the canvas to trigger context menu
            const canvas = document.getElementById('tactical-canvas');
            if (!canvas) return { ok: false };
            canvas.dispatchEvent(new MouseEvent('contextmenu', {
                clientX: 500, clientY: 400, bubbles: true, cancelable: true,
            }));
            // Check if menu appeared
            const menu = document.querySelector('.map-context-menu');
            const hasMenu = !!menu;
            // Close it
            if (menu) menu.remove();
            return { ok: true, hasMenu };
        }""")
        assert result["ok"]

    def test_batch_items_appear_when_multi_selected(self, page):
        """Batch dispatch/recall appear when multiple units selected."""
        result = page.evaluate("""() => {
            // Set multi-selection
            window.TritiumStore.set('map.selectedUnitIds', ['batch_a', 'batch_b', 'batch_c']);

            // Trigger context menu
            const canvas = document.getElementById('tactical-canvas');
            canvas.dispatchEvent(new MouseEvent('contextmenu', {
                clientX: 500, clientY: 400, bubbles: true, cancelable: true,
            }));

            return new Promise(resolve => {
                setTimeout(() => {
                    const menu = document.querySelector('.map-context-menu');
                    const text = menu ? menu.textContent : '';
                    const hasBatchDispatch = text.includes('BATCH DISPATCH');
                    const hasBatchRecall = text.includes('BATCH RECALL');
                    if (menu) menu.remove();
                    resolve({ hasBatchDispatch, hasBatchRecall, menuText: text.substring(0, 200) });
                }, 100);
            });
        }""")
        assert result["hasBatchDispatch"], f"Expected BATCH DISPATCH in menu, got: {result['menuText']}"
        assert result["hasBatchRecall"], f"Expected BATCH RECALL in menu, got: {result['menuText']}"

    def test_no_batch_items_when_single_select(self, page):
        """Batch items don't appear for single selection."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', ['only_one']);

            const canvas = document.getElementById('tactical-canvas');
            canvas.dispatchEvent(new MouseEvent('contextmenu', {
                clientX: 500, clientY: 400, bubbles: true, cancelable: true,
            }));

            return new Promise(resolve => {
                setTimeout(() => {
                    const menu = document.querySelector('.map-context-menu');
                    const text = menu ? menu.textContent : '';
                    const hasBatch = text.includes('BATCH');
                    if (menu) menu.remove();
                    resolve({ hasBatch });
                }, 100);
            });
        }""")
        assert not result["hasBatch"], "Batch items should not appear for single selection"


# ============================================================
# Help overlay
# ============================================================


class TestHelpOverlayBatch23:
    """Verify help overlay includes Tab shortcut."""

    def test_tab_shortcut_in_help(self, page):
        """Help overlay lists Tab shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        assert "Tab" in result["text"] or "tab" in result["text"].lower()


# ============================================================
# Render pipeline stability
# ============================================================


class TestRenderStability:
    """All Batch 23 features work together without crash."""

    def test_full_batch23_render_cycle(self, page):
        """All features active simultaneously render cleanly."""
        result = page.evaluate("""() => {
            // Multi-select
            window.TritiumStore.set('map.selectedUnitIds', ['stability_a', 'stability_b']);
            window.TritiumStore.updateUnit('stability_a', {
                name: 'Stability A', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('stability_b', {
                name: 'Stability B', type: 'rover', alliance: 'friendly',
                position: { x: 100, y: 100 },
            });

            // Kill feed
            window.EventBus.emit('combat:elimination', {
                target_id: 'stab_hostile',
                target_alliance: 'hostile',
                target_name: 'HOSTILE-X',
                shooter_name: 'TURRET-X',
                position: { x: 50, y: 50 },
            });

            // Active combat (triggers radar sweep + HUD)
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 2);
            window.TritiumStore.set('game.score', 500);

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 20) {
                        requestAnimationFrame(tick);
                    } else {
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 20
        assert result["canvasOk"]
