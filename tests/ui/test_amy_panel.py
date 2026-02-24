"""Amy Commander panel integration tests.

Verifies the enhanced Amy panel shows sensorium narrative,
mood indicators, event count, and thought stream.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_amy_panel.py -v -m ux
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.ux, pytest.mark.ui]


class TestAmyPanelContent:
    """Amy panel should show rich sensorium data, not just static text."""

    def test_amy_panel_has_narrative_section(self, page, take_screenshot):
        """Amy panel should have an AWARENESS narrative section."""
        # Open Amy panel
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        narrative = page.locator('[data-bind="narrative"]')
        assert narrative.count() > 0, "Amy panel should have a narrative element"
        take_screenshot(page, 'amy-panel-narrative')

    def test_amy_panel_has_thought_section(self, page, take_screenshot):
        """Amy panel should have a LAST THOUGHT section."""
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        thought = page.locator('[data-bind="thought"]')
        assert thought.count() > 0, "Amy panel should have a thought element"

    def test_amy_panel_has_event_count(self, page, take_screenshot):
        """Amy panel should show event count from sensorium."""
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        events = page.locator('[data-bind="event-count"]')
        assert events.count() > 0, "Amy panel should have event count element"

    def test_amy_panel_mood_dot_exists(self, page, take_screenshot):
        """Amy panel should have a colored mood indicator dot."""
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        dot = page.locator('[data-bind="mood-dot"]')
        assert dot.count() > 0, "Amy panel should have mood indicator dot"

    def test_amy_panel_state_shows_value(self, page, take_screenshot):
        """Amy state should show a real value, not empty."""
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        state = page.locator('[data-bind="state"]')
        text = state.text_content()
        assert text and len(text) > 0, f"Amy state should have text, got: '{text}'"
        assert text != '', "Amy state should not be empty"

    def test_amy_panel_mood_shows_value(self, page, take_screenshot):
        """Amy mood should show a real value, not empty."""
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        mood = page.locator('[data-bind="mood-label"]')
        text = mood.text_content()
        assert text and len(text) > 0, f"Amy mood should have text, got: '{text}'"

    def test_amy_panel_chat_button_opens_chat(self, page, take_screenshot):
        """CHAT button in Amy panel should open the chat overlay."""
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        # Button exists in DOM
        btn_count = page.evaluate(
            "document.querySelectorAll('[data-panel-id=\"amy\"] [data-action=\"chat\"]').length"
        )
        assert btn_count > 0, "Amy panel should have CHAT button in DOM"

        # Click via JS (button may be in overflow area)
        page.evaluate("""
            document.querySelector('[data-panel-id="amy"] [data-action="chat"]').click()
        """)
        page.wait_for_timeout(500)

        chat = page.locator('#chat-overlay')
        assert not chat.is_hidden(), "Chat overlay should open after clicking CHAT"
        take_screenshot(page, 'amy-panel-chat-opened')

        # Clean up
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

    def test_sensorium_narrative_updates(self, page, take_screenshot):
        """Sensorium narrative should update from polling (not stay at init text)."""
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        narrative = page.locator('[data-bind="narrative"]')

        # Wait for sensorium poll (5s interval + network)
        page.wait_for_timeout(6000)

        updated_text = narrative.text_content()
        # The narrative should have changed from the loading placeholder
        # Accept: Amy sensorium narrative OR simulation fallback text
        assert updated_text != 'Loading awareness data...', \
            f"Narrative should update from placeholder, got: '{updated_text}'"
        assert len(updated_text) > 5, \
            f"Narrative should have meaningful content, got: '{updated_text}'"
        take_screenshot(page, 'amy-panel-sensorium-updated')


class TestAmyPanelInteraction:
    """Amy panel interaction tests."""

    def test_amy_panel_toggles_with_key_1(self, page, take_screenshot):
        """Key 1 should toggle the Amy panel open and closed."""
        # Ensure panel is open
        page.keyboard.press('1')
        page.wait_for_timeout(500)
        panel = page.locator('[data-panel-id="amy"]')

        if panel.count() > 0 and panel.is_visible():
            # Close it
            page.keyboard.press('1')
            page.wait_for_timeout(500)
            # Should be gone or hidden
            if panel.count() > 0:
                assert not panel.is_visible(), "Panel should hide after second press"
            take_screenshot(page, 'amy-panel-closed')

            # Open again
            page.keyboard.press('1')
            page.wait_for_timeout(500)
            panel = page.locator('[data-panel-id="amy"]')
            assert panel.count() > 0 and panel.is_visible(), "Panel should open on third press"
            take_screenshot(page, 'amy-panel-reopened')
