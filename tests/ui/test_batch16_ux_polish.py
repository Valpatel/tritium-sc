"""Batch 16 UX polish tests.

Verifies chat context display, status bar indicators, menu bar panel buttons,
and keyboard guide behavior.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch16_ux_polish.py -v -m ux
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
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Chat context display
# ============================================================


class TestChatContext:
    """Verify Amy chat context thought display."""

    def test_chat_overlay_exists(self, page):
        """Chat overlay element exists."""
        exists = page.evaluate("() => !!document.getElementById('chat-overlay')")
        assert exists, "chat-overlay not found"

    def test_chat_context_text_exists(self, page):
        """Chat context text element exists."""
        exists = page.evaluate("() => !!document.getElementById('chat-context-text')")
        assert exists, "chat-context-text not found"

    def test_chat_opens_with_c_key(self, page):
        """Pressing C opens the chat panel."""
        page.keyboard.press("c")
        page.wait_for_timeout(300)
        visible = page.evaluate("""() => {
            const overlay = document.getElementById('chat-overlay');
            return overlay ? !overlay.hidden : false;
        }""")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert visible, "Chat should open with C key"

    def test_chat_has_input_and_send(self, page):
        """Chat has input field and send button."""
        result = page.evaluate("""() => {
            return {
                input: !!document.getElementById('chat-input'),
                send: !!document.getElementById('chat-send'),
            };
        }""")
        assert result["input"], "Chat input not found"
        assert result["send"], "Chat send button not found"

    def test_chat_context_updates_from_store(self, page):
        """Chat context text updates when amy.lastThought changes."""
        text = page.evaluate("""() => {
            window.TritiumStore.set('amy.lastThought', 'Test thought from store');
            return document.getElementById('chat-context-text')?.textContent || '';
        }""")
        assert text == "Test thought from store", f"Expected test thought, got: {text}"

    def test_chat_context_has_timestamp(self, page):
        """Chat context text has data-updated attribute after thought set."""
        has_attr = page.evaluate("""() => {
            window.TritiumStore.set('amy.lastThought', 'Timestamped thought');
            return !!document.getElementById('chat-context-text')?.dataset.updated;
        }""")
        assert has_attr, "chat-context-text should have data-updated attribute"


# ============================================================
# Status bar indicators
# ============================================================


class TestStatusBar:
    """Verify status bar dynamic indicators."""

    def test_status_bar_exists(self, page):
        """Status bar element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-bar')")
        assert exists, "status-bar not found"

    def test_status_fps_element(self, page):
        """FPS counter element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-fps')")
        assert exists, "status-fps not found"

    def test_status_fps_updates(self, page):
        """FPS counter shows a numeric value after rendering."""
        page.wait_for_timeout(2000)  # let rendering loop run
        text = page.evaluate("() => document.getElementById('status-fps')?.textContent || ''")
        assert "FPS" in text, f"FPS counter should show FPS, got: {text}"

    def test_status_alive_counter(self, page):
        """Alive counter shows friendly count."""
        text = page.evaluate("() => document.getElementById('status-alive')?.textContent || ''")
        assert "alive" in text.lower(), f"Expected alive count, got: {text}"

    def test_status_threats_counter(self, page):
        """Threats counter exists."""
        text = page.evaluate("() => document.getElementById('status-threats')?.textContent || ''")
        assert "threat" in text.lower(), f"Expected threats count, got: {text}"

    def test_status_ws_indicator(self, page):
        """WebSocket status shows OK or --."""
        text = page.evaluate("() => document.getElementById('status-ws')?.textContent || ''")
        assert "WS" in text, f"Expected WS status, got: {text}"

    def test_status_audio_indicator(self, page):
        """Audio indicator exists."""
        text = page.evaluate("() => document.getElementById('status-audio')?.textContent || ''")
        assert text in ("AUDIO", "MUTED"), f"Expected AUDIO or MUTED, got: {text}"

    def test_status_mode_indicator_exists(self, page):
        """Mode indicator element exists (hidden by default)."""
        result = page.evaluate("""() => {
            const el = document.getElementById('status-mode');
            return el ? { exists: true, hidden: el.style.display === 'none' || el.hidden } : { exists: false };
        }""")
        assert result["exists"], "status-mode not found"
        assert result["hidden"], "status-mode should be hidden by default"

    def test_status_mode_shows_on_placement(self, page):
        """Mode indicator shows PLACEMENT when entering placement mode."""
        result = page.evaluate("""() => {
            window.EventBus.emit('map:placementMode', { type: 'turret' });
            const el = document.getElementById('status-mode');
            const text = el ? el.textContent : '';
            const visible = el ? el.style.display !== 'none' : false;
            // Clean up
            window.EventBus.emit('map:cancelPlacement');
            return { text, visible };
        }""")
        assert result["visible"], "status-mode should be visible during placement"
        assert "PLACEMENT" in result["text"], f"Expected PLACEMENT, got: {result['text']}"

    def test_status_panels_counter(self, page):
        """Panel counter element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-panels')")
        assert exists, "status-panels not found"

    def test_status_coords_display(self, page):
        """Coordinates display exists."""
        exists = page.evaluate("() => !!document.getElementById('status-coords')")
        assert exists, "status-coords not found"

    def test_status_highlight_css(self, page):
        """status-highlight class applies cyan color."""
        color = page.evaluate("""() => {
            const el = document.createElement('span');
            el.className = 'status-highlight';
            document.body.appendChild(el);
            const c = getComputedStyle(el).color;
            el.remove();
            return c;
        }""")
        assert "0" in color and "240" in color and "255" in color, \
            f"status-highlight should be cyan, got {color}"


# ============================================================
# Menu bar panel buttons
# ============================================================


class TestMenuBarButtons:
    """Verify menu bar panel quick-toggle buttons."""

    def test_command_bar_exists(self, page):
        """Command bar container exists."""
        exists = page.evaluate("() => !!document.querySelector('.command-bar')")
        assert exists, "command-bar not found"

    def test_panel_buttons_exist(self, page):
        """Panel toggle buttons exist in command bar."""
        count = page.evaluate("() => document.querySelectorAll('.command-bar-btn[data-panel]').length")
        assert count >= 5, f"Expected at least 5 panel buttons, got {count}"

    def test_panel_button_has_title(self, page):
        """Panel buttons have tooltip titles with keyboard shortcuts."""
        result = page.evaluate("""() => {
            const btns = document.querySelectorAll('.command-bar-btn[data-panel]');
            let withTitle = 0;
            for (const btn of btns) {
                if (btn.title && btn.title.includes('(')) withTitle++;
            }
            return { total: btns.length, withTitle };
        }""")
        assert result["withTitle"] > 0, "Panel buttons should have tooltip titles with shortcuts"

    def test_panel_button_active_on_open(self, page):
        """Panel button gets active class when panel opens."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                // Press 1 to open Amy panel
                const btn = document.querySelector('.command-bar-btn[data-panel="amy"]');
                const wasBefore = btn ? btn.classList.contains('active') : null;
                window.EventBus.emit('panel:opened', { id: 'amy' });
                setTimeout(() => {
                    const isAfter = btn ? btn.classList.contains('active') : null;
                    resolve({ wasBefore, isAfter });
                }, 100);
            });
        }""")
        assert result["isAfter"] is True, "Button should be active after panel opens"

    def test_badge_css_exists(self, page):
        """command-bar-badge CSS class renders correctly."""
        result = page.evaluate("""() => {
            const el = document.createElement('span');
            el.className = 'command-bar-badge';
            el.textContent = '3';
            document.body.appendChild(el);
            const style = getComputedStyle(el);
            const bg = style.backgroundColor;
            el.remove();
            return bg;
        }""")
        # Should be magenta background
        assert "255" in result and "42" in result, f"Badge should have magenta bg, got {result}"


# ============================================================
# Keyboard guide
# ============================================================


class TestKeyboardGuide:
    """Verify keyboard guide overlay behavior."""

    def test_keyboard_guide_exists(self, page):
        """Keyboard guide element exists in DOM."""
        exists = page.evaluate("() => !!document.getElementById('keyboard-guide')")
        assert exists, "keyboard-guide not found"

    def test_help_overlay_opens_with_question_mark(self, page):
        """Pressing ? opens help overlay."""
        page.keyboard.press("?")
        page.wait_for_timeout(300)
        visible = page.evaluate("""() => {
            const help = document.getElementById('help-overlay');
            return help ? !help.hidden : false;
        }""")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert visible, "Help overlay should open with ? key"

    def test_slide_in_keyframes_exist(self, page):
        """kg-slideIn animation keyframes exist."""
        has_rule = page.evaluate("""() => {
            for (const sheet of document.styleSheets) {
                try {
                    for (const rule of sheet.cssRules) {
                        if (rule.type === CSSRule.KEYFRAMES_RULE && rule.name === 'kg-slideIn') {
                            return true;
                        }
                    }
                } catch (_) {}
            }
            return false;
        }""")
        assert has_rule, "kg-slideIn @keyframes not found"

    def test_status_key_hover_style(self, page):
        """Status key ? has hover styling."""
        # Verify the CSS rule exists
        has_rule = page.evaluate("""() => {
            for (const sheet of document.styleSheets) {
                try {
                    for (const rule of sheet.cssRules) {
                        if (rule.selectorText && rule.selectorText.includes('status-key') &&
                            rule.selectorText.includes('hover')) {
                            return true;
                        }
                    }
                } catch (_) {}
            }
            return false;
        }""")
        assert has_rule, "status-key:hover CSS rule not found"
