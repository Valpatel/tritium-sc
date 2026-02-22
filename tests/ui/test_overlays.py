"""Overlay tests for the Command Center.

Tests help overlay, modal overlay, and game-over overlay behavior.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_overlays.py -v -m ux
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.ux, pytest.mark.ui]


class TestHelpOverlay:
    """Help overlay open/close behavior."""

    def test_help_opens_on_question_mark(self, page, take_screenshot):
        """Pressing ? should open the help overlay."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        help_overlay = page.locator('#help-overlay')
        assert help_overlay.is_hidden(), "Help should start hidden"

        page.keyboard.press('?')
        page.wait_for_timeout(500)
        assert not help_overlay.is_hidden(), "Help should be visible"
        take_screenshot(page, 'overlay-help-open')

    def test_help_has_keyboard_shortcuts(self, page, take_screenshot):
        """Help overlay should show keyboard shortcut sections."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('?')
        page.wait_for_timeout(500)

        # Check sections exist
        sections = page.locator('.help-section')
        assert sections.count() >= 4, "Help should have at least 4 sections"

        # Check for known section titles
        section_titles = page.locator('.help-section-title')
        titles_text = [section_titles.nth(i).text_content()
                       for i in range(section_titles.count())]
        assert 'GENERAL' in titles_text, "Should have GENERAL section"
        assert 'MAP' in titles_text, "Should have MAP section"
        assert 'PANELS' in titles_text, "Should have PANELS section"
        take_screenshot(page, 'overlay-help-sections')

    def test_help_closes_on_escape(self, page, take_screenshot):
        """Pressing Escape should close the help overlay."""
        page.keyboard.press('?')
        page.wait_for_timeout(300)
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        help_overlay = page.locator('#help-overlay')
        assert help_overlay.is_hidden(), "Help should close on Escape"
        take_screenshot(page, 'overlay-help-escape-closed')

    def test_help_closes_on_click_outside(self, page, take_screenshot):
        """Clicking outside the help panel should close it."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('?')
        page.wait_for_timeout(500)

        help_overlay = page.locator('#help-overlay')
        assert not help_overlay.is_hidden()

        # Click the overlay backdrop (not the panel itself)
        help_overlay.click(position={"x": 10, "y": 10})
        page.wait_for_timeout(300)

        assert help_overlay.is_hidden(), "Help should close on backdrop click"
        take_screenshot(page, 'overlay-help-click-outside-closed')

    def test_help_close_button(self, page, take_screenshot):
        """Clicking the X button should close the help overlay."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('?')
        page.wait_for_timeout(500)

        close_btn = page.locator('[data-element="help-close"]')
        close_btn.click()
        page.wait_for_timeout(300)

        help_overlay = page.locator('#help-overlay')
        assert help_overlay.is_hidden(), "Help should close on X click"
        take_screenshot(page, 'overlay-help-close-button')

    def test_help_reopen_after_close(self, page, take_screenshot):
        """After closing help, pressing ? again should reopen it."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        page.keyboard.press('?')
        page.wait_for_timeout(300)
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        help_overlay = page.locator('#help-overlay')
        assert help_overlay.is_hidden()

        page.keyboard.press('?')
        page.wait_for_timeout(300)
        assert not help_overlay.is_hidden(), "Help should reopen"
        take_screenshot(page, 'overlay-help-reopened')
        page.keyboard.press('Escape')


class TestModalOverlay:
    """Modal overlay behavior."""

    def test_modal_starts_hidden(self, page, take_screenshot):
        """Modal overlay should be hidden by default."""
        modal = page.locator('#modal-overlay')
        assert modal.is_hidden(), "Modal should start hidden"
        take_screenshot(page, 'overlay-modal-hidden')

    def test_modal_closes_on_escape(self, page, take_screenshot):
        """If modal were shown, Escape should close it."""
        # Programmatically show modal
        page.evaluate("document.getElementById('modal-overlay').hidden = false")
        page.wait_for_timeout(300)

        modal = page.locator('#modal-overlay')
        assert not modal.is_hidden()

        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        assert modal.is_hidden(), "Modal should close on Escape"
        take_screenshot(page, 'overlay-modal-escape-closed')

    def test_modal_closes_on_backdrop_click(self, page, take_screenshot):
        """Clicking the modal backdrop should close it."""
        page.evaluate("document.getElementById('modal-overlay').hidden = false")
        page.wait_for_timeout(300)

        modal = page.locator('#modal-overlay')
        modal.click(position={"x": 10, "y": 10})
        page.wait_for_timeout(300)

        assert modal.is_hidden(), "Modal should close on backdrop click"
        take_screenshot(page, 'overlay-modal-backdrop-closed')


class TestGameOverOverlay:
    """Game over overlay behavior."""

    def test_game_over_starts_hidden(self, page, take_screenshot):
        """Game over overlay should be hidden by default."""
        overlay = page.locator('#game-over-overlay')
        assert overlay.is_hidden(), "Game over should start hidden"
        take_screenshot(page, 'overlay-gameover-hidden')

    def test_game_over_closes_on_escape(self, page, take_screenshot):
        """Escape should close the game over overlay."""
        page.evaluate("document.getElementById('game-over-overlay').hidden = false")
        page.wait_for_timeout(300)
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        overlay = page.locator('#game-over-overlay')
        assert overlay.is_hidden(), "Game over should close on Escape"
        take_screenshot(page, 'overlay-gameover-escape-closed')

    def test_game_over_has_stats(self, page, take_screenshot):
        """Game over overlay should contain score, waves, and eliminations."""
        page.evaluate("document.getElementById('game-over-overlay').hidden = false")
        page.wait_for_timeout(300)

        title = page.locator('#game-over-title')
        assert title.is_visible(), "Game over title should exist"

        score = page.locator('#go-score')
        assert score.is_visible(), "Score stat should exist"

        waves = page.locator('#go-waves')
        assert waves.is_visible(), "Waves stat should exist"

        elims = page.locator('#go-eliminations')
        assert elims.is_visible(), "Eliminations stat should exist"

        take_screenshot(page, 'overlay-gameover-stats')
        page.keyboard.press('Escape')
