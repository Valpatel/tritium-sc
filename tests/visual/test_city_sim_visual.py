# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Visual verification tests for the city simulation.

Uses Playwright to open the Command Center, start the city sim,
and verify rendering state via JavaScript evaluation.
"""
from __future__ import annotations

import asyncio
import json

import pytest

try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


pytestmark = [
    pytest.mark.visual,
    pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed"),
]

BASE_URL = "http://localhost:8000"


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def _check_server():
    """Return True if the server is running."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{BASE_URL}/api/city-sim/status", timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status == 200
    except Exception:
        return False


@pytest.mark.asyncio
async def test_module_loading_in_browser():
    """All 19 city sim ES modules load without errors in a real browser."""
    if not await _check_server():
        pytest.skip("Server not running on port 8000")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        await page.goto(f"{BASE_URL}/static/city-sim-test.html", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        results = await page.evaluate("""() => {
            const all = document.querySelectorAll('.test');
            const pass_count = document.querySelectorAll('.test.pass').length;
            const fail_count = document.querySelectorAll('.test.fail').length;
            const fails = Array.from(document.querySelectorAll('.test.fail')).map(e => e.textContent);
            return { pass_count, fail_count, fails };
        }""")

        await browser.close()

    assert len(errors) == 0, f"Page errors: {errors}"
    assert results["fail_count"] == 0, f"Failed tests: {results['fails']}"
    assert results["pass_count"] >= 40, f"Only {results['pass_count']} tests passed"


@pytest.mark.asyncio
async def test_city_sim_starts_with_j_key():
    """Pressing J starts the city sim with vehicles and pedestrians."""
    if not await _check_server():
        pytest.skip("Server not running on port 8000")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        await page.goto(f"{BASE_URL}/", wait_until="networkidle")
        await page.wait_for_timeout(6000)

        await page.keyboard.press("j")
        await page.wait_for_timeout(12000)

        # Verify via exported function
        stats = await page.evaluate("""async () => {
            const mod = await import('/static/js/command/map-maplibre.js');
            return mod.getCitySimStats ? mod.getCitySimStats() : null;
        }""")

        await browser.close()

    assert stats is not None, "getCitySimStats returned null"
    assert stats["running"] is True, "City sim not running"
    assert stats["vehicles"] > 0, f"No vehicles: {stats['vehicles']}"
    assert stats["pedestrians"] > 0, f"No pedestrians: {stats['pedestrians']}"
    assert stats["nodes"] > 0, f"No road nodes: {stats['nodes']}"
    assert stats["edges"] > 0, f"No road edges: {stats['edges']}"
    assert stats["trafficControllers"] > 0, f"No traffic controllers"

    # Check console for expected messages
    has_road_network = any("Road network" in m for m in console_msgs)
    has_spawned = any("Spawned" in m for m in console_msgs)
    has_rendering = any("Rendering initialized" in m for m in console_msgs)

    assert has_road_network, "Missing 'Road network' console message"
    assert has_spawned, "Missing 'Spawned' console message"
    assert has_rendering, "Missing 'Rendering initialized' console message"


@pytest.mark.asyncio
async def test_integration_stress():
    """Run integration + physics stress tests in browser."""
    if not await _check_server():
        pytest.skip("Server not running on port 8000")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(f"{BASE_URL}/static/city-sim-test.html", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Run integration tests
        await page.click("#btn-integration")
        await page.wait_for_timeout(5000)

        # Run physics stress
        await page.click("#btn-physics")
        await page.wait_for_timeout(10000)

        results = await page.evaluate("""() => {
            const summary = document.getElementById('summary').textContent;
            const pass_count = document.querySelectorAll('.test.pass').length;
            const fail_count = document.querySelectorAll('.test.fail').length;
            const fails = Array.from(document.querySelectorAll('.test.fail')).map(e => e.textContent);
            return { summary, pass_count, fail_count, fails };
        }""")

        await browser.close()

    assert results["fail_count"] == 0, f"Failed: {results['fails']}"
    assert results["pass_count"] >= 60, f"Only {results['pass_count']} passed (expected 65)"
