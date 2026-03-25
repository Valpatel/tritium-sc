# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for engine.tactical.ble_classifier — BLE device threat classification."""

from __future__ import annotations

import pytest

from tritium_lib.tracking.ble_classifier import (
    BLEClassification,
    BLEClassifier,
    CLASSIFICATION_LEVELS,
    DEFAULT_SUSPICIOUS_RSSI,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.published.append((event_type, data))

    def subscribe(self):
        import queue
        return queue.Queue()

    def unsubscribe(self, q) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> MockEventBus:
    return MockEventBus()


@pytest.fixture
def classifier(bus: MockEventBus) -> BLEClassifier:
    return BLEClassifier(event_bus=bus)


@pytest.fixture
def classifier_with_known(bus: MockEventBus) -> BLEClassifier:
    known = {"AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"}
    return BLEClassifier(event_bus=bus, known_macs=known)


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBLEClassification:
    """Core classification logic."""

    def test_known_device_classified_as_known(self, bus, classifier_with_known):
        """A device whose MAC is in known_macs should be classified 'known'."""
        result = classifier_with_known.classify("AA:BB:CC:DD:EE:01", "MyPhone", -60)
        assert result.level == "known"
        assert result.mac == "AA:BB:CC:DD:EE:01"
        # No alerts for known devices
        assert len(bus.published) == 0

    def test_unknown_device_classified_as_unknown(self, bus, classifier):
        """A device seen before but not in known_macs should be 'unknown'."""
        # First sighting -> new
        classifier.classify("11:22:33:44:55:66", "Stranger", -70)
        bus.published.clear()

        # Second sighting -> unknown (seen before, not known)
        result = classifier.classify("11:22:33:44:55:66", "Stranger", -70)
        assert result.level == "unknown"

    def test_first_time_device_classified_as_new(self, bus, classifier):
        """First-ever sighting of a MAC should be classified 'new'."""
        result = classifier.classify("AA:BB:CC:DD:EE:FF", "NewDevice", -80)
        assert result.level == "new"

    def test_new_device_publishes_alert(self, bus, classifier):
        """A 'new' device should publish ble:new_device + ble:first_seen alerts."""
        classifier.classify("AA:BB:CC:DD:EE:FF", "NewDevice", -80)
        # Two events: ble:new_device (legacy) + ble:first_seen (notification)
        assert len(bus.published) == 2
        event_type, data = bus.published[0]
        assert event_type == "ble:new_device"
        assert data["mac"] == "AA:BB:CC:DD:EE:FF"
        assert data["level"] == "new"
        # Second event: first-seen notification
        fs_type, fs_data = bus.published[1]
        assert fs_type == "ble:first_seen"
        assert fs_data["mac"] == "AA:BB:CC:DD:EE:FF"
        assert "New device first seen" in fs_data["message"]

    def test_strong_unknown_signal_classified_as_suspicious(self, bus, classifier):
        """Unknown device with RSSI > threshold should be 'suspicious'."""
        # First sighting with strong signal -> suspicious (new + strong)
        result = classifier.classify("CC:DD:EE:FF:00:11", "StrongDevice", -30)
        assert result.level == "suspicious"

    def test_suspicious_device_publishes_alert(self, bus, classifier):
        """A suspicious device should publish ble:new_device + ble:first_seen (first time)."""
        classifier.classify("CC:DD:EE:FF:00:11", "StrongDevice", -30)
        assert len(bus.published) == 2
        event_type, data = bus.published[0]
        # First time seeing it -> ble:new_device even if suspicious
        assert event_type == "ble:new_device"
        assert data["level"] == "suspicious"
        # Also first-seen notification
        assert bus.published[1][0] == "ble:first_seen"

    def test_returning_strong_unknown_publishes_suspicious_alert(self, bus, classifier):
        """Previously seen unknown device with strong signal -> suspicious alert."""
        # First sighting, weak signal
        classifier.classify("DD:EE:FF:00:11:22", "WeakFirst", -80)
        bus.published.clear()

        # Second sighting, strong signal -> suspicious
        result = classifier.classify("DD:EE:FF:00:11:22", "NowStrong", -30)
        assert result.level == "suspicious"
        assert len(bus.published) == 1
        event_type, data = bus.published[0]
        assert event_type == "ble:suspicious_device"
        assert data["rssi"] == -30

    def test_known_device_not_suspicious_even_strong_signal(self, bus, classifier_with_known):
        """Known devices are never suspicious regardless of signal strength."""
        result = classifier_with_known.classify("AA:BB:CC:DD:EE:01", "MyPhone", -10)
        assert result.level == "known"
        assert len(bus.published) == 0

    def test_case_insensitive_mac(self, bus, classifier_with_known):
        """MAC comparison should be case-insensitive."""
        result = classifier_with_known.classify("aa:bb:cc:dd:ee:01", "MyPhone", -60)
        assert result.level == "known"

    def test_seen_count_increments(self, bus, classifier):
        """Each sighting should increment seen_count."""
        classifier.classify("11:22:33:44:55:66", "Device", -70)
        classifier.classify("11:22:33:44:55:66", "Device", -65)
        result = classifier.classify("11:22:33:44:55:66", "Device", -60)
        assert result.seen_count == 3


# ---------------------------------------------------------------------------
# Known MAC management tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKnownMACManagement:
    """Adding and removing MACs from the known set."""

    def test_add_known_mac(self, bus, classifier):
        """Adding a MAC to known set should reclassify existing records."""
        # First classify as new
        classifier.classify("AA:BB:CC:DD:EE:FF", "Device", -80)
        bus.published.clear()

        # Add to known
        classifier.add_known("AA:BB:CC:DD:EE:FF")

        # Verify existing record was updated
        classifications = classifier.get_classifications()
        assert classifications["AA:BB:CC:DD:EE:FF"].level == "known"

        # New classification should also be known
        result = classifier.classify("AA:BB:CC:DD:EE:FF", "Device", -80)
        assert result.level == "known"

    def test_remove_known_mac(self, bus, classifier_with_known):
        """Removing a MAC from known set returns True; missing returns False."""
        assert classifier_with_known.remove_known("AA:BB:CC:DD:EE:01") is True
        assert classifier_with_known.remove_known("FF:FF:FF:FF:FF:FF") is False

    def test_get_known_macs(self, bus, classifier_with_known):
        """get_known_macs returns a copy of the known set."""
        known = classifier_with_known.get_known_macs()
        assert "AA:BB:CC:DD:EE:01" in known
        assert "AA:BB:CC:DD:EE:02" in known
        assert len(known) == 2

    def test_get_classifications_by_level(self, bus, classifier_with_known):
        """Filter classifications by level."""
        classifier_with_known.classify("AA:BB:CC:DD:EE:01", "Known1", -60)
        classifier_with_known.classify("11:22:33:44:55:66", "Unknown1", -80)

        known = classifier_with_known.get_classifications_by_level("known")
        assert len(known) == 1
        assert known[0].mac == "AA:BB:CC:DD:EE:01"

    def test_clear_resets_state(self, bus, classifier):
        """clear() resets classifications and seen_macs but keeps known_macs."""
        classifier.classify("11:22:33:44:55:66", "Dev", -80)
        classifier.clear()

        classifications = classifier.get_classifications()
        assert len(classifications) == 0

        # Should be "new" again after clear
        bus.published.clear()
        result = classifier.classify("11:22:33:44:55:66", "Dev", -80)
        assert result.level == "new"


# ---------------------------------------------------------------------------
# Custom threshold tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCustomThreshold:
    """Custom RSSI threshold for suspicious classification."""

    def test_custom_suspicious_threshold(self, bus):
        """Classifier respects custom suspicious RSSI threshold."""
        c = BLEClassifier(event_bus=bus, suspicious_rssi=-60)
        # -50 is stronger than -60, should be suspicious
        result = c.classify("AA:BB:CC:DD:EE:FF", "NearbyDevice", -50)
        assert result.level == "suspicious"

    def test_below_custom_threshold_is_new(self, bus):
        """Signal weaker than threshold should be new, not suspicious."""
        c = BLEClassifier(event_bus=bus, suspicious_rssi=-60)
        result = c.classify("AA:BB:CC:DD:EE:FF", "FarDevice", -70)
        assert result.level == "new"
