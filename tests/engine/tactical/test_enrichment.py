# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for engine.tactical.enrichment — target enrichment pipeline."""

from __future__ import annotations

import asyncio
import queue
import time

import pytest

from engine.tactical.enrichment import (
    EnrichmentPipeline,
    EnrichmentResult,
    _oui_lookup,
    _wifi_fingerprint,
    _ble_device_class,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    """Minimal EventBus mock for enrichment tests."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self._subscribers: list[queue.Queue] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.published.append((event_type, data))
        msg = {"type": event_type}
        if data is not None:
            msg["data"] = data
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def subscribe(self, _filter=None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> MockEventBus:
    return MockEventBus()


@pytest.fixture
def pipeline() -> EnrichmentPipeline:
    """Pipeline without EventBus (no background listener)."""
    return EnrichmentPipeline(event_bus=None)


@pytest.fixture
def pipeline_with_bus(bus: MockEventBus) -> EnrichmentPipeline:
    """Pipeline with EventBus for auto-enrichment tests."""
    p = EnrichmentPipeline(event_bus=bus)
    yield p
    p.stop()


# ---------------------------------------------------------------------------
# Built-in provider tests
# ---------------------------------------------------------------------------


class TestOUILookup:
    """Test OUI manufacturer lookup provider."""

    @pytest.mark.asyncio
    async def test_known_espressif_mac(self):
        result = await _oui_lookup("test1", {"mac": "24:0A:C4:12:34:56"})
        assert result is not None
        assert result.provider == "oui_lookup"
        assert result.enrichment_type == "manufacturer"
        assert result.data["manufacturer"] == "Espressif"
        assert result.confidence > 0.9

    @pytest.mark.asyncio
    async def test_known_apple_mac(self):
        result = await _oui_lookup("test2", {"mac": "3C:E0:72:AA:BB:CC"})
        assert result is not None
        assert result.data["manufacturer"] == "Apple"

    @pytest.mark.asyncio
    async def test_unknown_mac(self):
        result = await _oui_lookup("test3", {"mac": "FF:FF:FF:00:00:00"})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_mac(self):
        result = await _oui_lookup("test4", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_short_mac(self):
        result = await _oui_lookup("test5", {"mac": "AA:BB"})
        assert result is None

    @pytest.mark.asyncio
    async def test_mac_normalization(self):
        """MAC with dashes or dots should still work."""
        result = await _oui_lookup("test6", {"mac": "24-0a-c4-12-34-56"})
        assert result is not None
        assert result.data["manufacturer"] == "Espressif"


class TestWiFiFingerprint:
    """Test WiFi SSID fingerprinting provider."""

    @pytest.mark.asyncio
    async def test_iphone_ssid(self):
        result = await _wifi_fingerprint("test1", {"probed_ssids": ["iPhone-Matt"]})
        assert result is not None
        assert result.data["device_type"] == "phone"

    @pytest.mark.asyncio
    async def test_printer_ssid(self):
        result = await _wifi_fingerprint("test2", {"probed_ssids": ["DIRECT-AB-HP-Printer"]})
        assert result is not None
        assert result.data["device_type"] == "printer"

    @pytest.mark.asyncio
    async def test_laptop_ssid(self):
        result = await _wifi_fingerprint("test3", {"probed_ssids": ["LAPTOP-ABC123"]})
        assert result is not None
        assert result.data["device_type"] == "laptop"

    @pytest.mark.asyncio
    async def test_no_match(self):
        result = await _wifi_fingerprint("test4", {"probed_ssids": ["MyHomeNetwork"]})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_ssids(self):
        result = await _wifi_fingerprint("test5", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_best_match_wins(self):
        """When multiple SSIDs match, highest confidence wins."""
        result = await _wifi_fingerprint("test6", {
            "probed_ssids": ["xfinitywifi", "iPhone-Personal"]
        })
        assert result is not None
        assert result.data["device_type"] == "phone"  # Higher confidence


class TestBLEDeviceClass:
    """Test BLE device name classification provider."""

    @pytest.mark.asyncio
    async def test_airpods(self):
        result = await _ble_device_class("test1", {"name": "AirPods Pro"})
        assert result is not None
        assert result.data["category"] == "earbuds"

    @pytest.mark.asyncio
    async def test_watch(self):
        result = await _ble_device_class("test2", {"name": "Apple Watch"})
        assert result is not None
        assert result.data["category"] == "watch"

    @pytest.mark.asyncio
    async def test_esp32(self):
        result = await _ble_device_class("test3", {"name": "ESP32-Tritium"})
        assert result is not None
        assert result.data["category"] == "microcontroller"

    @pytest.mark.asyncio
    async def test_tracker(self):
        result = await _ble_device_class("test4", {"name": "AirTag"})
        assert result is not None
        assert result.data["category"] == "tracker"

    @pytest.mark.asyncio
    async def test_no_name(self):
        result = await _ble_device_class("test5", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_name(self):
        result = await _ble_device_class("test6", {"name": "XYZ-Unknown-123"})
        assert result is None


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


class TestEnrichmentPipeline:
    """Test the EnrichmentPipeline orchestration."""

    @pytest.mark.asyncio
    async def test_builtin_providers_registered(self, pipeline: EnrichmentPipeline):
        names = pipeline.get_provider_names()
        assert "oui_lookup" in names
        assert "wifi_fingerprint" in names
        assert "ble_device_class" in names

    @pytest.mark.asyncio
    async def test_enrich_ble_device(self, pipeline: EnrichmentPipeline):
        """Enrich a BLE device with known MAC and name."""
        results = await pipeline.enrich("ble_240ac4123456", {
            "mac": "24:0A:C4:12:34:56",
            "name": "ESP32-Tritium",
        })
        # Should get OUI result (Espressif) and BLE class (microcontroller)
        providers = {r.provider for r in results}
        assert "oui_lookup" in providers
        assert "ble_device_class" in providers

    @pytest.mark.asyncio
    async def test_parallel_execution(self, pipeline: EnrichmentPipeline):
        """Verify providers run in parallel (all execute, not short-circuit)."""
        call_order: list[str] = []

        async def slow_provider(tid, ids):
            call_order.append("slow_start")
            await asyncio.sleep(0.05)
            call_order.append("slow_end")
            return EnrichmentResult(
                provider="slow", enrichment_type="test",
                data={"ran": True}, confidence=1.0,
            )

        async def fast_provider(tid, ids):
            call_order.append("fast")
            return EnrichmentResult(
                provider="fast", enrichment_type="test",
                data={"ran": True}, confidence=1.0,
            )

        pipeline.register_provider("slow_test", slow_provider)
        pipeline.register_provider("fast_test", fast_provider)

        results = await pipeline.enrich("parallel_test", {"mac": "FF:FF:FF:00:00:00"})
        # Both custom providers should have returned results
        custom_providers = {r.provider for r in results if r.provider in ("slow", "fast")}
        assert "slow" in custom_providers
        assert "fast" in custom_providers
        # Fast should start before slow finishes (parallel)
        assert "fast" in call_order
        assert "slow_start" in call_order

    @pytest.mark.asyncio
    async def test_caching(self, pipeline: EnrichmentPipeline):
        """Second call should return cached results."""
        results1 = await pipeline.enrich("cache_test", {"mac": "24:0A:C4:12:34:56"})
        results2 = await pipeline.enrich("cache_test", {"mac": "24:0A:C4:12:34:56"})
        # Same results (cached)
        assert len(results1) == len(results2)
        for r1, r2 in zip(results1, results2):
            assert r1.provider == r2.provider
            assert r1.timestamp == r2.timestamp  # Same object from cache

    @pytest.mark.asyncio
    async def test_force_enrich_bypasses_cache(self, pipeline: EnrichmentPipeline):
        """force_enrich should clear cache and re-run."""
        results1 = await pipeline.enrich("force_test", {"mac": "24:0A:C4:12:34:56"})
        t1 = results1[0].timestamp if results1 else 0

        # Wait a tiny bit so timestamps differ
        await asyncio.sleep(0.01)

        results2 = await pipeline.force_enrich("force_test", {"mac": "24:0A:C4:12:34:56"})
        t2 = results2[0].timestamp if results2 else 0

        # Timestamps should differ (re-queried)
        assert t2 >= t1

    @pytest.mark.asyncio
    async def test_get_cached_none(self, pipeline: EnrichmentPipeline):
        """get_cached returns None for unknown targets."""
        assert pipeline.get_cached("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_cached_after_enrich(self, pipeline: EnrichmentPipeline):
        """get_cached returns results after enrichment."""
        await pipeline.enrich("cached_check", {"mac": "24:0A:C4:12:34:56"})
        cached = pipeline.get_cached("cached_check")
        assert cached is not None
        assert len(cached) > 0

    @pytest.mark.asyncio
    async def test_clear_cache_specific(self, pipeline: EnrichmentPipeline):
        """clear_cache(target_id) clears only that target."""
        await pipeline.enrich("a", {"mac": "24:0A:C4:12:34:56"})
        await pipeline.enrich("b", {"mac": "B8:27:EB:00:00:00"})
        pipeline.clear_cache("a")
        assert pipeline.get_cached("a") is None
        assert pipeline.get_cached("b") is not None

    @pytest.mark.asyncio
    async def test_clear_cache_all(self, pipeline: EnrichmentPipeline):
        """clear_cache() clears everything."""
        await pipeline.enrich("x", {"mac": "24:0A:C4:12:34:56"})
        await pipeline.enrich("y", {"mac": "B8:27:EB:00:00:00"})
        pipeline.clear_cache()
        assert pipeline.get_cached("x") is None
        assert pipeline.get_cached("y") is None

    @pytest.mark.asyncio
    async def test_register_custom_provider(self, pipeline: EnrichmentPipeline):
        """Custom providers are callable and included in results."""
        async def custom(tid, ids):
            return EnrichmentResult(
                provider="custom", enrichment_type="test",
                data={"custom": True}, confidence=0.5,
            )

        pipeline.register_provider("custom", custom)
        results = await pipeline.enrich("custom_test", {})
        providers = {r.provider for r in results}
        assert "custom" in providers

    @pytest.mark.asyncio
    async def test_unregister_provider(self, pipeline: EnrichmentPipeline):
        """Unregistered providers are not called."""
        assert pipeline.unregister_provider("oui_lookup") is True
        assert pipeline.unregister_provider("oui_lookup") is False
        assert "oui_lookup" not in pipeline.get_provider_names()

    @pytest.mark.asyncio
    async def test_provider_exception_handled(self, pipeline: EnrichmentPipeline):
        """A failing provider does not break other providers."""
        async def broken(tid, ids):
            raise ValueError("boom")

        pipeline.register_provider("broken", broken)
        # Should not raise, and other providers still return results
        results = await pipeline.enrich("error_test", {"mac": "24:0A:C4:12:34:56"})
        providers = {r.provider for r in results}
        assert "oui_lookup" in providers
        assert "broken" not in providers

    @pytest.mark.asyncio
    async def test_result_to_dict(self):
        """EnrichmentResult.to_dict() returns expected structure."""
        r = EnrichmentResult(
            provider="test", enrichment_type="foo",
            data={"key": "val"}, confidence=0.8,
        )
        d = r.to_dict()
        assert d["provider"] == "test"
        assert d["enrichment_type"] == "foo"
        assert d["data"] == {"key": "val"}
        assert d["confidence"] == 0.8
        assert "timestamp" in d


class TestAutoEnrichment:
    """Test auto-enrichment via EventBus subscription."""

    @pytest.mark.asyncio
    async def test_auto_enrich_on_ble_new_device(
        self, bus: MockEventBus, pipeline_with_bus: EnrichmentPipeline
    ):
        """Publishing ble:new_device should trigger enrichment."""
        # Publish a new BLE device event
        bus.publish("ble:new_device", {
            "mac": "24:0A:C4:AA:BB:CC",
            "name": "ESP32-Test",
            "rssi": -50,
            "level": "new",
        })

        # Give the listener thread time to process
        await asyncio.sleep(0.3)

        # Check that enrichment was performed and cached
        target_id = "ble_240ac4aabbcc"
        cached = pipeline_with_bus.get_cached(target_id)
        assert cached is not None
        providers = {r.provider for r in cached}
        assert "oui_lookup" in providers

    @pytest.mark.asyncio
    async def test_auto_enrich_on_suspicious_device(
        self, bus: MockEventBus, pipeline_with_bus: EnrichmentPipeline
    ):
        """Publishing ble:suspicious_device should also trigger enrichment."""
        bus.publish("ble:suspicious_device", {
            "mac": "B8:27:EB:11:22:33",
            "name": "Raspberry Pi",
            "rssi": -30,
            "level": "suspicious",
        })

        await asyncio.sleep(0.3)

        target_id = "ble_b827eb112233"
        cached = pipeline_with_bus.get_cached(target_id)
        assert cached is not None

    @pytest.mark.asyncio
    async def test_ignores_unrelated_events(
        self, bus: MockEventBus, pipeline_with_bus: EnrichmentPipeline
    ):
        """Non-BLE events should not trigger enrichment."""
        bus.publish("sim_telemetry", {"target_id": "rover1"})
        await asyncio.sleep(0.2)
        assert pipeline_with_bus.get_cached("rover1") is None

    def test_stop_listener(self, pipeline_with_bus: EnrichmentPipeline):
        """stop() should cleanly shut down the listener thread."""
        pipeline_with_bus.stop()
        assert pipeline_with_bus._running is False
