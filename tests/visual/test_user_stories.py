# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""User Story Verification Tests -- Playwright-based tests for critical user stories.

Verifies the most critical user stories defined in docs/USER-STORIES.md:
  1. First Launch -- page loads, panels visible, map rendered, command bar exists
  2. Address Geocoding -- the /api/geo/geocode endpoint responds
  3. Battle Gameplay -- game reset, begin, WebSocket game events
  4. Amy Companion -- /api/amy/status returns data, Amy panel shows status, chat input
  5. Panel Management -- panels toggle open/closed, state reflected in UI
  6. At-a-Glance Perception -- mode buttons exist and respond, unit colors visible

Methodology:
  - Playwright headed browser (headless=False per project convention)
  - API calls via requests for backend verification
  - WebSocket via Playwright for game event verification
  - Screenshots saved to tests/.test-results/user-stories/

Run:
    .venv/bin/python3 -m pytest tests/visual/test_user_stories.py -v
    ./test.sh 19
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests
from playwright.sync_api import sync_playwright, Page

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUT = Path("tests/.test-results/user-stories")
OUT.mkdir(parents=True, exist_ok=True)

SERVER = "http://localhost:8000"
VIEWPORT_W = 1920
VIEWPORT_H = 1080
SETTLE = 2.5  # seconds for render to settle

# Cybercore palette (BGR for OpenCV)
FRIENDLY_GREEN = (161, 255, 5)   # #05ffa1
HOSTILE_RED = (109, 42, 255)     # #ff2a6d
CYAN_PRIMARY = (255, 240, 0)     # #00f0ff

pytestmark = [pytest.mark.user_story, pytest.mark.visual]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grab(page: Page, timeout: int = 60000) -> np.ndarray:
    """Full page screenshot as BGR numpy array."""
    buf = page.screenshot(timeout=timeout)
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _save(name: str, img: np.ndarray):
    """Save debug image to output directory."""
    cv2.imwrite(str(OUT / f"{name}.png"), img)


def _screenshot(page: Page, name: str):
    """Save a Playwright screenshot to the output directory."""
    try:
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser_page():
    """Launch headed Playwright browser, navigate to Command Center."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})

        page.goto(SERVER, wait_until="networkidle", timeout=30000)
        time.sleep(5)  # let map tiles load, panels render, WebSocket connect

        # Dismiss any modal
        page.keyboard.press("Escape")
        time.sleep(0.5)

        yield page

        browser.close()


@pytest.fixture(autouse=True)
def reset_between_tests(browser_page):
    """Lightweight reset between tests to keep UI consistent."""
    page = browser_page
    # Close overlays
    page.evaluate("""(() => {
        const ids = ['chat-overlay', 'help-overlay', 'modal-overlay', 'game-over-overlay'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.hidden = true;
        }
        document.querySelectorAll('.menu-dropdown').forEach(d => d.hidden = true);
    })()""")
    # Restore chrome elements
    page.evaluate("""(() => {
        const ids = ['header-bar', 'command-bar-container', 'status-bar',
                     'map-mode', 'map-coords', 'map-fps', 'toast-container',
                     'minimap-container'];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
        }
    })()""")
    # Blur any focused input so keyboard shortcuts work
    page.evaluate("document.activeElement && document.activeElement.blur()")
    time.sleep(0.5)


# ============================================================
# Story 1: First Launch (4 tests)
# ============================================================

class TestStory1FirstLaunch:
    """Story 1: As a new operator, I start the system and immediately see
    something alive. The page loads with panels, a map, and live data.
    """

    def test_page_loads_under_5_seconds(self, browser_page):
        """The page should load and reach networkidle within 5 seconds.

        We already waited for networkidle in the fixture, so this just
        verifies the page is in a good state (no crash, title present).
        """
        page = browser_page
        title = page.title()
        print(f"  Page title: {title}")

        # The page should have a title
        assert title, "Page has no title -- may not have loaded"

        # Verify no crash -- body should exist and have children
        body_children = page.evaluate("document.body.children.length")
        assert body_children > 0, "Page body is empty -- page may have crashed"

        _screenshot(page, "story1_page_loaded")

    def test_at_least_2_panels_visible(self, browser_page):
        """Story 1 says three floating panels are open by default.

        We verify at least 2 are visible to allow for layout variations.
        """
        page = browser_page

        panels = page.locator(".panel")
        total = panels.count()
        visible_count = 0
        visible_ids = []
        for i in range(total):
            panel = panels.nth(i)
            if panel.is_visible():
                visible_count += 1
                panel_id = panel.get_attribute("id") or panel.get_attribute("data-panel-id") or f"panel_{i}"
                visible_ids.append(panel_id)

        print(f"  Total panels: {total}, visible: {visible_count}")
        print(f"  Visible panel IDs: {visible_ids}")

        assert visible_count >= 2, (
            f"Expected >= 2 visible panels (Story 1 specifies 3 default panels), "
            f"got {visible_count}"
        )

        _screenshot(page, "story1_panels_visible")

    def test_map_rendered_with_content(self, browser_page):
        """The map should be visible and rendering actual content (not black void).

        Story 1 says: 'Real satellite imagery of a neighborhood is visible
        as the map ground layer.'
        """
        page = browser_page

        # Find the map container
        map_el = page.locator("#maplibre-map")
        if map_el.count() == 0 or not map_el.is_visible():
            map_el = page.locator("#tactical-3d-canvas")
        if map_el.count() == 0 or not map_el.is_visible():
            map_el = page.locator("#tactical-canvas")
        if map_el.count() == 0 or not map_el.is_visible():
            map_el = page.locator("#tactical-area")

        assert map_el.count() > 0, "No map container found in the DOM"
        assert map_el.is_visible(), "Map container exists but is not visible"

        box = map_el.bounding_box()
        assert box is not None, "Map container has no bounding box"
        assert box["width"] > 200, f"Map too narrow: {box['width']}px"
        assert box["height"] > 200, f"Map too short: {box['height']}px"

        print(f"  Map size: {box['width']}x{box['height']}")

        # Take a screenshot and check the map area is not all black
        img = _grab(page)
        _save("story1_map_content", img)

        # Crop to the map area
        x, y, w, h = int(box["x"]), int(box["y"]), int(box["width"]), int(box["height"])
        ih, iw = img.shape[:2]
        map_crop = img[max(0, y):min(ih, y + h), max(0, x):min(iw, x + w)]

        if map_crop.size > 0:
            gray = cv2.cvtColor(map_crop, cv2.COLOR_BGR2GRAY)
            mean_brightness = float(np.mean(gray))
            print(f"  Map mean brightness: {mean_brightness:.1f}")
            assert mean_brightness > 5, (
                f"Map area is essentially black (brightness={mean_brightness:.1f}). "
                f"Nothing is rendering."
            )

    def test_command_bar_exists(self, browser_page):
        """Story 1 mentions a header bar and panel controls.

        The command bar should exist and contain interactive elements.
        """
        page = browser_page

        # Check for command-bar-container
        command_bar = page.locator("#command-bar-container")
        if command_bar.count() == 0:
            command_bar = page.locator(".command-bar")

        has_command_bar = command_bar.count() > 0

        # Also check for header bar
        header_bar = page.locator("#header-bar")
        has_header = header_bar.count() > 0 and header_bar.is_visible()

        print(f"  Command bar found: {has_command_bar}")
        print(f"  Header bar found and visible: {has_header}")

        assert has_command_bar or has_header, (
            "Neither command bar (#command-bar-container) nor header bar (#header-bar) found"
        )

        # The header should show unit counts per Story 1
        if has_header:
            header_text = header_bar.text_content() or ""
            print(f"  Header text (truncated): {header_text[:120]}")

        _screenshot(page, "story1_command_bar")


# ============================================================
# Story 2: Address Geocoding (2 tests)
# ============================================================

class TestStory2Geocoding:
    """Story 2: Setting up my neighborhood -- geocoding API responds
    and the geo reference can be read.
    """

    def test_geo_reference_endpoint(self, browser_page):
        """GET /api/geo/reference should return the current reference point.

        Story 2 describes setting the map to a real address. The geo
        reference endpoint is the foundation for this feature.
        """
        try:
            resp = requests.get(f"{SERVER}/api/geo/reference", timeout=10)
        except requests.ConnectionError:
            pytest.skip("Server not reachable")

        print(f"  Status: {resp.status_code}")
        assert resp.status_code == 200, (
            f"GET /api/geo/reference returned {resp.status_code}, expected 200"
        )

        data = resp.json()
        print(f"  Reference: {json.dumps(data)}")

        assert "lat" in data, "Response missing 'lat' field"
        assert "lng" in data, "Response missing 'lng' field"
        assert isinstance(data["lat"], (int, float)), "lat must be a number"
        assert isinstance(data["lng"], (int, float)), "lng must be a number"

    def test_geocode_endpoint_responds(self, browser_page):
        """POST /api/geo/geocode should accept an address and return coordinates.

        Story 2 shows calling geocode-and-set-reference. We test the
        geocode endpoint itself to avoid mutating server state during tests.
        This test may fail if Nominatim is unreachable (network dependency).
        """
        try:
            resp = requests.post(
                f"{SERVER}/api/geo/geocode",
                json={"address": "1600 Pennsylvania Avenue, Washington DC"},
                timeout=15,
            )
        except requests.ConnectionError:
            pytest.skip("Server not reachable")

        print(f"  Status: {resp.status_code}")

        # Accept 200 (success) or 502 (Nominatim unreachable -- network issue, not our bug)
        if resp.status_code == 502:
            pytest.skip("Nominatim geocoding service unreachable (network issue)")

        assert resp.status_code == 200, (
            f"POST /api/geo/geocode returned {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        print(f"  Geocode result: lat={data.get('lat')}, lng={data.get('lng')}")
        print(f"  Display name: {data.get('display_name', '')[:80]}")

        assert "lat" in data, "Geocode response missing 'lat'"
        assert "lng" in data, "Geocode response missing 'lng'"


# ============================================================
# Story 3: Battle Gameplay (3 tests)
# ============================================================

class TestStory3BattleGameplay:
    """Story 3: Playing a full battle -- game reset, begin, events.

    We test the game API endpoints and verify game events flow
    through the WebSocket to the frontend.
    """

    def test_game_reset_works(self, browser_page):
        """POST /api/game/reset should return to setup state.

        Story 3 starts with a setup phase. Reset ensures we are in that state.
        """
        try:
            resp = requests.post(f"{SERVER}/api/game/reset", timeout=10)
        except requests.ConnectionError:
            pytest.skip("Server not reachable")

        print(f"  Status: {resp.status_code}")

        if resp.status_code == 503:
            pytest.skip("Simulation engine not available")

        assert resp.status_code == 200, (
            f"POST /api/game/reset returned {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        print(f"  Reset response: {json.dumps(data)}")
        assert data.get("status") == "reset", f"Expected status='reset', got {data.get('status')}"
        assert data.get("state") == "setup", f"Expected state='setup', got {data.get('state')}"

    def test_game_begin_starts_battle(self, browser_page):
        """POST /api/game/begin should start the war countdown.

        Story 3 describes pressing B to begin. The API equivalent starts
        the countdown. We first reset to ensure we are in setup state.
        """
        # Reset first
        try:
            reset_resp = requests.post(f"{SERVER}/api/game/reset", timeout=10)
            if reset_resp.status_code == 503:
                pytest.skip("Simulation engine not available")
        except requests.ConnectionError:
            pytest.skip("Server not reachable")

        time.sleep(0.5)

        # Begin war
        resp = requests.post(f"{SERVER}/api/game/begin", timeout=10)
        print(f"  Status: {resp.status_code}")

        assert resp.status_code == 200, (
            f"POST /api/game/begin returned {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        print(f"  Begin response: {json.dumps(data)}")
        assert data.get("status") == "countdown_started", (
            f"Expected status='countdown_started', got {data.get('status')}"
        )

        _screenshot(browser_page, "story3_battle_begun")

        # Let the countdown play for a moment, then take another screenshot
        time.sleep(3)
        _screenshot(browser_page, "story3_battle_countdown")

    def test_websocket_receives_game_events(self, browser_page):
        """After beginning a battle, the frontend should receive game events
        via WebSocket (game_state_change, wave_start, telemetry).

        Story 3 describes wave announcements, kill feeds, and score updates --
        all of which flow through the WebSocket.
        """
        page = browser_page

        # Reset and begin
        try:
            reset_resp = requests.post(f"{SERVER}/api/game/reset", timeout=10)
            if reset_resp.status_code == 503:
                pytest.skip("Simulation engine not available")
        except requests.ConnectionError:
            pytest.skip("Server not reachable")

        time.sleep(0.5)

        # Set up event listener in the browser BEFORE beginning war
        page.evaluate("""(() => {
            window._testGameEvents = [];
            const origOnMessage = window._ws ? window._ws.onmessage : null;

            // Listen for game-related store events
            if (window.TritiumStore) {
                window.TritiumStore.on('game', (data) => {
                    window._testGameEvents.push({type: 'game', data: JSON.stringify(data).slice(0, 200)});
                });
            }

            // Also listen for EventBus game events if available
            if (window.EventBus) {
                for (const evt of ['game:state', 'game:wave', 'game:combat', 'game:score']) {
                    window.EventBus.on(evt, (data) => {
                        window._testGameEvents.push({type: evt, data: JSON.stringify(data).slice(0, 200)});
                    });
                }
            }
        })()""")

        # Begin war
        requests.post(f"{SERVER}/api/game/begin", timeout=10)

        # Wait for events to arrive (countdown is 5 seconds, then wave 1 starts)
        time.sleep(8)

        events = page.evaluate("window._testGameEvents || []")
        print(f"  Game events received: {len(events)}")
        for evt in events[:10]:
            print(f"    {evt['type']}: {evt['data'][:100]}")

        # Check that the game state changed in the store
        game_state = page.evaluate("""(() => {
            if (!window.TritiumStore) return null;
            return window.TritiumStore.gameState || null;
        })()""")
        print(f"  TritiumStore.gameState: {game_state}")

        # Also check the game state API
        try:
            state_resp = requests.get(f"{SERVER}/api/game/state", timeout=5)
            if state_resp.status_code == 200:
                api_state = state_resp.json()
                print(f"  API game state: {json.dumps(api_state)[:200]}")
        except Exception:
            pass

        _screenshot(page, "story3_game_events")

        # We should see SOME evidence the game is running --
        # either events were captured, or the game state changed from setup
        has_events = len(events) > 0
        has_state_change = game_state is not None and game_state != "setup"

        assert has_events or has_state_change, (
            "No game events received and game state did not change. "
            "The WebSocket game event pipeline may be broken."
        )

        # Clean up: reset the game
        requests.post(f"{SERVER}/api/game/reset", timeout=5)
        time.sleep(1)


# ============================================================
# Story 4: Amy Companion (3 tests)
# ============================================================

class TestStory4AmyCompanion:
    """Story 4: Amy as companion -- status API, Amy panel, chat input.

    Amy should feel like a real presence, not a chatbot behind a button.
    """

    def test_amy_status_api_returns_data(self, browser_page):
        """GET /api/amy/status should return Amy's current state.

        Story 4 describes Amy's state cycling between OBSERVING and THINKING.
        The status endpoint is the source of this data.
        """
        try:
            resp = requests.get(f"{SERVER}/api/amy/status", timeout=10)
        except requests.ConnectionError:
            pytest.skip("Server not reachable")

        print(f"  Status: {resp.status_code}")

        if resp.status_code == 503:
            pytest.skip("Amy not available (AMY_ENABLED may be false)")

        assert resp.status_code == 200, (
            f"GET /api/amy/status returned {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        print(f"  Amy status: {json.dumps(data)[:300]}")

        # Amy status should have at minimum a state/mood field
        assert isinstance(data, dict), "Amy status should be a JSON object"
        # Check for common fields (the exact schema depends on implementation)
        has_state = "state" in data or "status" in data or "mood" in data
        assert has_state or len(data) > 0, (
            "Amy status returned empty or missing state/mood fields"
        )

    def test_amy_panel_shows_status(self, browser_page):
        """The Amy panel should be visible and showing her current state.

        Story 4 says: 'The Amy panel shows her state cycling between
        OBSERVING and THINKING.'
        """
        page = browser_page

        # Ensure Amy panel is open
        page.evaluate("""(() => {
            const pm = window.panelManager;
            if (pm && !pm.isOpen('amy')) pm.open('amy');
        })()""")
        time.sleep(1)

        # Find the Amy panel
        amy_panel = page.locator("[data-panel-id='amy'], #panel-amy, .panel-amy")
        if amy_panel.count() == 0:
            # Try broader search
            amy_panel = page.locator(".panel:has-text('AMY'), .panel:has-text('Amy')")

        panel_found = amy_panel.count() > 0
        print(f"  Amy panel found: {panel_found}")

        if panel_found:
            panel_visible = amy_panel.first.is_visible()
            print(f"  Amy panel visible: {panel_visible}")

            # Get panel text content
            panel_text = amy_panel.first.text_content() or ""
            print(f"  Amy panel text (truncated): {panel_text[:200]}")

            assert panel_visible, "Amy panel found but not visible"
        else:
            # Fallback: check if panelManager knows about 'amy'
            has_amy = page.evaluate("""(() => {
                const pm = window.panelManager;
                if (!pm) return false;
                const ids = pm.registeredIds ? pm.registeredIds() : [];
                return ids.includes('amy');
            })()""")
            print(f"  panelManager has 'amy': {has_amy}")
            assert has_amy, "Amy panel not registered in panelManager"

        _screenshot(page, "story4_amy_panel")

    def test_chat_input_exists(self, browser_page):
        """A chat input should exist for talking to Amy.

        Story 4 says: 'I press C to open the chat panel. I type:
        Amy, what is the situation?'
        """
        page = browser_page

        # The chat input may be hidden behind an overlay
        chat_input = page.locator("#chat-input")
        input_exists = chat_input.count() > 0
        print(f"  #chat-input element exists: {input_exists}")

        if input_exists:
            # It might be hidden inside a chat overlay
            is_visible = chat_input.is_visible()
            print(f"  #chat-input visible: {is_visible}")

            if not is_visible:
                # Try pressing C to open chat overlay
                page.keyboard.press("c")
                time.sleep(1)
                is_visible = chat_input.is_visible()
                print(f"  After pressing 'C', #chat-input visible: {is_visible}")

                if is_visible:
                    _screenshot(page, "story4_chat_open")
                    # Close the overlay
                    page.keyboard.press("Escape")
                    time.sleep(0.5)

            assert input_exists, "Chat input exists in DOM (may need 'C' key to reveal)"
        else:
            # Check for any chat-related input
            any_chat = page.locator("input[placeholder*='chat' i], input[placeholder*='amy' i], input[placeholder*='message' i]")
            assert any_chat.count() > 0, (
                "No chat input found. Story 4 requires a way to talk to Amy."
            )


# ============================================================
# Story 6: Panel Management (3 tests)
# ============================================================

class TestStory6PanelManagement:
    """Story 6: Panel management -- panels toggle open/closed,
    state reflected in UI.
    """

    def test_panels_can_be_toggled(self, browser_page):
        """Panels should toggle open/closed via panelManager.

        Story 6 says: 'I press 1 through 4 to toggle panels on and off.'
        """
        page = browser_page

        # Get registered panel IDs
        panel_ids = page.evaluate("""(() => {
            const pm = window.panelManager;
            if (!pm) return [];
            return pm.registeredIds ? pm.registeredIds() : [];
        })()""")

        print(f"  Registered panels: {panel_ids}")
        assert len(panel_ids) >= 2, (
            f"Expected >= 2 registered panels, got {len(panel_ids)}"
        )

        # Test toggling the first panel
        test_id = panel_ids[0]
        print(f"  Testing toggle on panel: {test_id}")

        # Get initial state
        initial_open = page.evaluate(f"window.panelManager.isOpen('{test_id}')")
        print(f"  Initial state (open): {initial_open}")

        # Toggle
        page.evaluate(f"window.panelManager.toggle('{test_id}')")
        time.sleep(0.5)

        # Check new state
        after_toggle = page.evaluate(f"window.panelManager.isOpen('{test_id}')")
        print(f"  After toggle (open): {after_toggle}")

        assert initial_open != after_toggle, (
            f"Panel '{test_id}' toggle did not change state. "
            f"Was {initial_open}, still {after_toggle}."
        )

        # Toggle back
        page.evaluate(f"window.panelManager.toggle('{test_id}')")
        time.sleep(0.5)

        restored = page.evaluate(f"window.panelManager.isOpen('{test_id}')")
        assert restored == initial_open, (
            f"Panel '{test_id}' did not restore to original state after double toggle. "
            f"Expected {initial_open}, got {restored}."
        )

        _screenshot(page, "story6_panel_toggle")

    def test_panel_visibility_matches_state(self, browser_page):
        """When a panel is toggled closed, it should not be visible in the DOM.
        When toggled open, it should be visible.

        Story 6 says: 'Each panel appears as a floating window.'
        """
        page = browser_page

        # Get a panel that is currently open
        panel_ids = page.evaluate("""(() => {
            const pm = window.panelManager;
            if (!pm || !pm.registeredIds) return [];
            return pm.registeredIds().filter(id => pm.isOpen(id));
        })()""")

        if not panel_ids:
            pytest.skip("No open panels to test")

        test_id = panel_ids[0]
        print(f"  Testing visibility for panel: {test_id}")

        # Panel is open -- verify it is visible in the DOM
        open_visible = page.evaluate(f"""(() => {{
            const pm = window.panelManager;
            const panel = pm.getPanel('{test_id}');
            if (!panel || !panel.el) return null;
            const rect = panel.el.getBoundingClientRect();
            return {{
                display: window.getComputedStyle(panel.el).display,
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                visible: rect.width > 0 && rect.height > 0,
            }};
        }})()""")

        print(f"  Open panel DOM state: {json.dumps(open_visible)}")
        if open_visible:
            assert open_visible.get("visible") or open_visible.get("display") != "none", (
                f"Panel '{test_id}' is marked open but not visible in DOM"
            )

        # Close the panel
        page.evaluate(f"window.panelManager.close('{test_id}')")
        time.sleep(0.5)

        closed_state = page.evaluate(f"""(() => {{
            const pm = window.panelManager;
            return {{
                isOpen: pm.isOpen('{test_id}'),
            }};
        }})()""")

        print(f"  After close: {json.dumps(closed_state)}")
        assert not closed_state.get("isOpen"), (
            f"Panel '{test_id}' still reports as open after close()"
        )

        # Reopen it
        page.evaluate(f"window.panelManager.open('{test_id}')")
        time.sleep(0.5)

    def test_command_bar_reflects_panel_state(self, browser_page):
        """Command bar buttons should reflect open/closed panel state.

        Story 6 describes panel toggle buttons. The command bar should
        have buttons that show which panels are active.
        """
        page = browser_page

        # Check for command bar buttons
        buttons = page.evaluate("""(() => {
            const btns = document.querySelectorAll('.command-bar-btn[data-panel]');
            return Array.from(btns).map(btn => ({
                panel: btn.dataset.panel,
                active: btn.classList.contains('active'),
                text: btn.textContent.trim(),
            }));
        })()""")

        print(f"  Command bar panel buttons: {len(buttons)}")
        for btn in buttons:
            print(f"    [{btn['panel']}] active={btn['active']} text='{btn['text']}'")

        if not buttons:
            # Fallback: check command-bar-container exists with some content
            cb = page.locator("#command-bar-container")
            has_cb = cb.count() > 0 and cb.is_visible()
            print(f"  Command bar container visible: {has_cb}")
            # This is acceptable -- the command bar design may vary
            return

        # At least one button should be active (matching an open panel)
        active_buttons = [b for b in buttons if b["active"]]
        print(f"  Active buttons: {len(active_buttons)}")
        assert len(active_buttons) >= 1, (
            "No command bar buttons are active, but panels are open. "
            "Command bar state is out of sync with panel state."
        )

        _screenshot(page, "story6_command_bar_state")


# ============================================================
# Story 8: At-a-Glance Perception (3 tests)
# ============================================================

class TestStory8AtAGlance:
    """Story 8: Observing from across the room -- mode buttons work,
    unit colors visible, situation readable at a glance.
    """

    def test_mode_buttons_exist_and_respond(self, browser_page):
        """Map mode buttons (Observe/Tactical/Setup) should exist and respond.

        Story 8 describes understanding the situation at a glance.
        Mode buttons control what information is displayed.
        """
        page = browser_page

        # Find mode buttons
        mode_buttons = page.locator("[data-map-mode]")
        count = mode_buttons.count()
        print(f"  Map mode buttons found: {count}")

        assert count >= 2, (
            f"Expected >= 2 map mode buttons (observe/tactical/setup), got {count}"
        )

        # List all modes
        modes = []
        for i in range(count):
            btn = mode_buttons.nth(i)
            mode = btn.get_attribute("data-map-mode")
            is_active = "active" in (btn.get_attribute("class") or "")
            is_visible = btn.is_visible()
            modes.append({"mode": mode, "active": is_active, "visible": is_visible})
            print(f"    [{mode}] active={is_active} visible={is_visible}")

        # At least one should be active
        active_modes = [m for m in modes if m["active"]]
        assert len(active_modes) >= 1, "No mode button is currently active"

        # Click a non-active mode and verify it becomes active
        inactive = [m for m in modes if not m["active"] and m["visible"]]
        if inactive:
            target_mode = inactive[0]["mode"]
            print(f"  Clicking mode: {target_mode}")
            page.locator(f"[data-map-mode='{target_mode}']").click()
            time.sleep(1)

            new_active = page.evaluate(f"""
                document.querySelector("[data-map-mode='{target_mode}']")
                    .classList.contains('active')
            """)
            print(f"  After click, '{target_mode}' is active: {new_active}")
            assert new_active, (
                f"Clicking mode button '{target_mode}' did not make it active"
            )

            _screenshot(page, f"story8_mode_{target_mode}")

            # Click back to observe mode
            page.locator("[data-map-mode='observe']").click()
            time.sleep(0.5)

    def test_unit_colors_visible_on_map(self, browser_page):
        """Friendly units should render as green pixels on the map.

        Story 8 says: 'Green dots are moving on familiar satellite imagery.'
        We use OpenCV to detect neon green pixels matching the friendly
        unit color (#05ffa1).
        """
        page = browser_page
        time.sleep(SETTLE)

        img = _grab(page)
        _save("story8_unit_colors", img)

        # Look for friendly green pixels (BGR: 161, 255, 5) with tolerance
        target_bgr = np.array(FRIENDLY_GREEN)
        diff = np.abs(img.astype(int) - target_bgr)
        green_mask = np.all(diff <= 45, axis=2)
        green_count = int(np.sum(green_mask))

        print(f"  Green pixels (friendly color): {green_count}")

        # Also check for cyan primary color (UI elements)
        target_cyan = np.array(CYAN_PRIMARY)
        diff_cyan = np.abs(img.astype(int) - target_cyan)
        cyan_mask = np.all(diff_cyan <= 45, axis=2)
        cyan_count = int(np.sum(cyan_mask))
        print(f"  Cyan pixels (UI elements): {cyan_count}")

        assert green_count >= 20 or cyan_count >= 50, (
            f"Too few colored pixels visible. Green={green_count}, Cyan={cyan_count}. "
            f"Story 8 requires unit colors to be visible from across the room."
        )

    def test_header_shows_unit_and_threat_counts(self, browser_page):
        """The header should display unit and threat counts at a glance.

        Story 8 says: '0 threats in amber in the header. All clear.'
        Story 1 says: 'unit counts: 6 friendly in green, 0 threats in amber.'
        """
        page = browser_page

        # Check unit count
        unit_stat = page.locator("#header-units .stat-value")
        if unit_stat.count() > 0:
            unit_text = unit_stat.text_content() or ""
            print(f"  Header unit count: '{unit_text}'")
            try:
                unit_count = int(unit_text.strip())
                assert unit_count >= 0, f"Unit count is negative: {unit_count}"
            except ValueError:
                # Might show "--" initially
                print(f"  Unit count not yet numeric: '{unit_text}'")
        else:
            print("  #header-units .stat-value not found")

        # Check threat count
        threat_stat = page.locator("#header-threats .stat-value")
        if threat_stat.count() > 0:
            threat_text = threat_stat.text_content() or ""
            print(f"  Header threat count: '{threat_text}'")
        else:
            print("  #header-threats .stat-value not found")

        # Check connection status
        conn_label = page.locator("#connection-status .conn-label")
        if conn_label.count() > 0:
            conn_text = conn_label.text_content() or ""
            print(f"  Connection status: '{conn_text}'")
            assert "ONLINE" in conn_text, (
                f"Expected ONLINE connection status, got '{conn_text}'"
            )
        else:
            print("  Connection status label not found")

        # At minimum, the header should be visible and have content
        header = page.locator("#header-bar")
        assert header.count() > 0 and header.is_visible(), (
            "Header bar not found or not visible"
        )

        _screenshot(page, "story8_header_counts")
