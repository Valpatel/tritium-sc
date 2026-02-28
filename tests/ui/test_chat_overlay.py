# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Chat overlay tests for the Command Center.

Exercises the chat flow: open, type, send, verify message, close.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_chat_overlay.py -v -m ux
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.ux, pytest.mark.ui]


class TestChatOpen:
    """Opening the chat overlay."""

    def test_chat_opens_with_c(self, page, take_screenshot):
        """Pressing C should open the chat overlay."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        chat = page.locator('#chat-overlay')
        assert chat.is_hidden(), "Chat should be hidden initially"

        page.keyboard.press('c')
        page.wait_for_timeout(500)
        assert not chat.is_hidden(), "Chat should be visible after C"
        take_screenshot(page, 'chat-open')

    def test_chat_input_focused(self, page, take_screenshot):
        """When chat opens, the input should be focused."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('c')
        page.wait_for_timeout(500)

        focused_id = page.evaluate("document.activeElement.id")
        assert focused_id == 'chat-input', "Chat input should be focused"
        take_screenshot(page, 'chat-input-focused')

    def test_chat_has_elements(self, page, take_screenshot):
        """Chat panel should have title, messages area, input, send button."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('c')
        page.wait_for_timeout(500)

        assert page.locator('.chat-title').is_visible(), "Chat title should exist"
        assert page.locator('#chat-messages').is_visible(), "Messages area should exist"
        assert page.locator('#chat-input').is_visible(), "Input should exist"
        assert page.locator('#chat-send').is_visible(), "Send button should exist"
        take_screenshot(page, 'chat-elements')


class TestChatSend:
    """Typing and sending a message."""

    def test_type_and_send_message(self, page, take_screenshot):
        """Typing a message and pressing Enter should add it to chat."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('c')
        page.wait_for_timeout(500)

        chat_input = page.locator('#chat-input')
        chat_input.fill('Hello Amy, this is a test message')
        take_screenshot(page, 'chat-typed')

        chat_input.press('Enter')
        page.wait_for_timeout(1000)

        # Check that a user message appeared
        messages = page.locator('#chat-messages .chat-msg')
        assert messages.count() > 0, "At least one message should appear"

        # The first message should be from the user
        first_msg = page.locator('#chat-messages .chat-msg-user').first
        assert first_msg.is_visible(), "User message should be visible"
        assert 'Hello Amy' in first_msg.text_content(), \
            "User message should contain the typed text"
        take_screenshot(page, 'chat-sent')

    def test_send_button_click(self, page, take_screenshot):
        """Clicking SEND should also send the message."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('c')
        page.wait_for_timeout(500)

        chat_input = page.locator('#chat-input')
        chat_input.fill('Testing send button')

        send_btn = page.locator('#chat-send')
        send_btn.click()
        page.wait_for_timeout(1000)

        # Verify message appeared
        user_msgs = page.locator('#chat-messages .chat-msg-user')
        found = False
        for i in range(user_msgs.count()):
            if 'Testing send button' in user_msgs.nth(i).text_content():
                found = True
                break
        assert found, "Sent message should appear in chat"
        take_screenshot(page, 'chat-send-button')

    def test_empty_send_does_nothing(self, page, take_screenshot):
        """Sending an empty message should not add anything."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('c')
        page.wait_for_timeout(500)

        count_before = page.locator('#chat-messages .chat-msg').count()
        chat_input = page.locator('#chat-input')
        chat_input.fill('')
        chat_input.press('Enter')
        page.wait_for_timeout(500)

        count_after = page.locator('#chat-messages .chat-msg').count()
        assert count_after == count_before, "Empty send should not add messages"
        take_screenshot(page, 'chat-empty-send')


class TestChatClose:
    """Closing the chat overlay."""

    def test_escape_closes_chat(self, page, take_screenshot):
        """Pressing Escape should close the chat."""
        page.keyboard.press('c')
        page.wait_for_timeout(300)
        # Click canvas to unfocus input
        page.locator('#tactical-canvas').click()
        page.wait_for_timeout(200)
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        chat = page.locator('#chat-overlay')
        assert chat.is_hidden(), "Chat should close on Escape"
        take_screenshot(page, 'chat-escape-closed')

    def test_close_button_closes_chat(self, page, take_screenshot):
        """Clicking the X button should close the chat."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('c')
        page.wait_for_timeout(500)

        close_btn = page.locator('#chat-close')
        close_btn.click()
        page.wait_for_timeout(300)

        chat = page.locator('#chat-overlay')
        assert chat.is_hidden(), "Chat should close on X click"
        take_screenshot(page, 'chat-close-button')

    def test_c_toggles_chat_closed(self, page, take_screenshot):
        """Pressing C when chat is open should close it."""
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('c')
        page.wait_for_timeout(300)

        chat = page.locator('#chat-overlay')
        assert not chat.is_hidden()

        # Click canvas first to unfocus input
        page.locator('#tactical-canvas').click()
        page.wait_for_timeout(200)
        page.keyboard.press('c')
        page.wait_for_timeout(300)

        assert chat.is_hidden(), "C should toggle chat closed"
        take_screenshot(page, 'chat-c-toggle-closed')
