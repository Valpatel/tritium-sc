# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Reusable framework for testing addon UIs with real mouse clicks.

This framework:
1. Launches a HEADED browser (user can watch)
2. Opens addon panels by clicking the WINDOWS menu
3. Clicks every button, tab, and control
4. Takes screenshots at each step
5. Verifies the UI responds (no stale state, no errors)
6. Can run in randomized loops for stress testing

Usage:
    tester = AddonUITester(panel_id='hackrf', panel_title='HACKRF SDR')
    tester.setup()
    tester.open_panel_via_menu()
    tester.click_all_tabs()
    tester.click_all_buttons()
    tester.teardown()
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Locator


class AddonUITester:
    """Reusable addon UI tester using headed Playwright with real clicks."""

    def __init__(
        self,
        panel_id: str,
        panel_title: str,
        base_url: str = "http://localhost:8000",
        screenshot_dir: str = "tests/.test-results",
        headed: bool = True,
    ):
        self.panel_id = panel_id
        self.panel_title = panel_title
        self.base_url = base_url
        self.screenshot_dir = Path(screenshot_dir) / panel_id
        self.headed = headed

        self._pw = None
        self._browser = None
        self._context = None
        self.page: Optional[Page] = None
        self.errors: list[str] = []
        self.screenshots: list[str] = []
        self.actions_log: list[str] = []
        self._step = 0

    def setup(self, timeout_ms: int = 30000):
        """Launch browser and navigate to app."""
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not self.headed)
        self._context = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = self._context.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=timeout_ms)
        time.sleep(6)  # Wait for JS to initialize
        self._log("Setup complete")

    def teardown(self):
        """Close browser."""
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._log(f"Teardown — {len(self.errors)} JS errors, {len(self.screenshots)} screenshots")

    def screenshot(self, label: str = "") -> str:
        """Take a screenshot with a sequential number and label."""
        self._step += 1
        name = f"{self._step:03d}_{label or 'step'}.png"
        path = str(self.screenshot_dir / name)
        self.page.screenshot(path=path)
        self.screenshots.append(path)
        return path

    # ── Panel Operations ──────────────────────────────────────

    def open_panel_via_menu(self) -> bool:
        """Open the addon panel by clicking through WINDOWS menu — real mouse clicks."""
        self._log("Opening panel via WINDOWS menu")

        # Click WINDOWS menu trigger
        triggers = self.page.query_selector_all('.menu-trigger')
        windows_trigger = None
        for t in triggers:
            if 'WINDOWS' in (t.inner_text() or ''):
                windows_trigger = t
                break

        if not windows_trigger:
            self._log("FAIL: WINDOWS menu trigger not found")
            return False

        windows_trigger.click()
        time.sleep(0.5)

        # Find and click our panel in the dropdown
        items = self.page.query_selector_all('.menu-item-label')
        for item in items:
            text = item.inner_text() or ''
            if self.panel_title.upper() in text.upper():
                item.click()
                self._log(f"Clicked menu item: {text}")
                time.sleep(2)
                self.screenshot("panel_opened")
                return True

        # Panel not found in menu — try escape and search in Other section
        self.page.keyboard.press('Escape')
        self._log(f"FAIL: {self.panel_title} not found in WINDOWS menu")
        return False

    def find_panel(self) -> Optional[Locator]:
        """Find the addon's panel element in the DOM."""
        panels = self.page.query_selector_all('.panel')
        for panel in panels:
            title = panel.query_selector('.panel-title')
            if title and self.panel_title.upper() in title.inner_text().upper():
                return panel
        return None

    # ── Tab Operations ────────────────────────────────────────

    def get_tabs(self) -> list[dict]:
        """Get all tabs in the panel with their labels and active state."""
        panel = self.find_panel()
        if not panel:
            return []
        tabs = panel.query_selector_all(f'.{self.panel_id[:3]}-tab')
        # Fallback: try common class patterns
        if not tabs:
            tabs = panel.query_selector_all('[data-tab]')
        return [
            {"element": tab, "label": tab.inner_text(), "active": 'active' in (tab.get_attribute('class') or '')}
            for tab in tabs
        ]

    def click_tab(self, label: str) -> bool:
        """Click a specific tab by its label text."""
        tabs = self.get_tabs()
        for tab in tabs:
            if label.upper() in tab["label"].upper():
                tab["element"].click()
                time.sleep(1)
                self._log(f"Clicked tab: {tab['label']}")
                self.screenshot(f"tab_{label.lower().replace(' ', '_')}")
                return True
        self._log(f"Tab not found: {label}")
        return False

    def click_all_tabs(self):
        """Click every tab in sequence, screenshot each."""
        tabs = self.get_tabs()
        self._log(f"Found {len(tabs)} tabs: {[t['label'] for t in tabs]}")
        for tab in tabs:
            tab["element"].click()
            time.sleep(1)
            self.screenshot(f"tab_{tab['label'].lower().replace(' ', '_')}")
            self._log(f"Tab {tab['label']}: OK")

    # ── Button Operations ─────────────────────────────────────

    def get_buttons(self) -> list[dict]:
        """Get all buttons in the currently visible panel body."""
        panel = self.find_panel()
        if not panel:
            return []
        buttons = panel.query_selector_all('button')
        result = []
        for btn in buttons:
            try:
                text = btn.inner_text().strip()
                if not text:
                    continue
                disabled = btn.is_disabled()
                result.append({"element": btn, "text": text, "disabled": disabled})
            except Exception:
                pass  # Element detached from DOM — skip
        return result

    def click_button(self, text: str, wait_s: float = 2.0) -> bool:
        """Click a button by its text content."""
        buttons = self.get_buttons()
        for btn in buttons:
            if text.upper() in btn["text"].upper() and not btn["disabled"]:
                btn["element"].click()
                time.sleep(wait_s)
                self._log(f"Clicked button: {btn['text']}")
                self.screenshot(f"btn_{text.lower().replace(' ', '_')[:20]}")
                return True
        self._log(f"Button not found or disabled: {text}")
        return False

    def click_all_buttons(self, skip: list[str] = None, wait_s: float = 2.0):
        """Click every enabled button in the panel. Skip dangerous ones."""
        skip = [s.upper() for s in (skip or ["FLASH", "RESET", "FACTORY", "REBOOT", "DELETE"])]
        buttons = self.get_buttons()
        self._log(f"Found {len(buttons)} buttons")
        for btn in buttons:
            text = btn["text"].upper()
            if btn["disabled"]:
                self._log(f"  Skip (disabled): {btn['text']}")
                continue
            if any(s in text for s in skip):
                self._log(f"  Skip (dangerous): {btn['text']}")
                continue
            try:
                btn["element"].click()
                time.sleep(wait_s)
                self.screenshot(f"btn_{btn['text'][:20].lower().replace(' ', '_')}")
                self._log(f"  Clicked: {btn['text']}")
            except Exception as e:
                self._log(f"  Error clicking {btn['text']}: {e}")

    # ── Randomized Stress Test ────────────────────────────────

    def random_exercise(self, iterations: int = 20, seed: int = 42):
        """Randomly click tabs and buttons in a loop to find edge cases."""
        rng = random.Random(seed)
        self._log(f"Starting random exercise: {iterations} iterations, seed={seed}")

        for i in range(iterations):
            action = rng.choice(["tab", "button", "button", "tab"])

            if action == "tab":
                tabs = self.get_tabs()
                if tabs:
                    tab = rng.choice(tabs)
                    tab["element"].click()
                    time.sleep(0.5)
                    self._log(f"  [{i+1}] Tab: {tab['label']}")

            elif action == "button":
                buttons = self.get_buttons()
                safe = [b for b in buttons
                        if not b["disabled"]
                        and not any(d in b["text"].upper() for d in ["FLASH", "RESET", "FACTORY", "REBOOT"])]
                if safe:
                    btn = rng.choice(safe)
                    try:
                        btn["element"].click()
                        time.sleep(1)
                        self._log(f"  [{i+1}] Button: {btn['text']}")
                    except Exception:
                        pass

            # Check for JS errors
            if self.errors:
                self._log(f"  JS ERROR at iteration {i+1}: {self.errors[-1][:80]}")
                self.screenshot(f"error_iter_{i+1}")

        self.screenshot("random_exercise_final")
        self._log(f"Random exercise complete: {len(self.errors)} errors")

    # ── Verification ──────────────────────────────────────────

    def verify_no_js_errors(self) -> bool:
        """Check that no JS errors occurred."""
        if self.errors:
            self._log(f"JS ERRORS ({len(self.errors)}):")
            for e in self.errors[:5]:
                self._log(f"  {e[:100]}")
            return False
        return True

    def verify_panel_has_content(self) -> bool:
        """Verify the panel body is not empty."""
        panel = self.find_panel()
        if not panel:
            self._log("Panel not found")
            return False
        body_text = panel.inner_text()
        has_content = len(body_text.strip()) > 20
        if not has_content:
            self._log(f"Panel appears empty (text length: {len(body_text)})")
        return has_content

    # ── Reporting ─────────────────────────────────────────────

    def get_report(self) -> dict:
        """Generate a test report."""
        return {
            "panel_id": self.panel_id,
            "panel_title": self.panel_title,
            "js_errors": len(self.errors),
            "screenshots": len(self.screenshots),
            "actions": len(self.actions_log),
            "errors": self.errors[:10],
            "log": self.actions_log[-20:],
        }

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.actions_log.append(entry)
        print(entry)
