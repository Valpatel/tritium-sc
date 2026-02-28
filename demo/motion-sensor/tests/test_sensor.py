# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for sensor detection state machine.

TDD: written BEFORE implementation.
Tests state transitions: idle -> triggered -> cooldown -> idle
Tests cooldown timing per sensor type.
Tests confidence ranges.
Tests metadata fields.
"""

import time
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensor import MotionSensor, SensorState


class TestSensorStates(unittest.TestCase):
    """Test the three-state machine: idle, triggered, cooldown."""

    def test_initial_state_is_idle(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        self.assertEqual(s.state, SensorState.IDLE)

    def test_trigger_transitions_to_triggered(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        event = s.trigger()
        self.assertEqual(s.state, SensorState.TRIGGERED)
        self.assertIsNotNone(event)

    def test_triggered_transitions_to_cooldown(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.trigger()
        s.clear()
        self.assertEqual(s.state, SensorState.COOLDOWN)

    def test_cooldown_transitions_to_idle_after_timeout(self):
        # Use microwave with 0.5s cooldown for fast test
        s = MotionSensor(sensor_id="mw-01", sensor_type="microwave")
        s.trigger()
        s.clear()
        self.assertEqual(s.state, SensorState.COOLDOWN)
        # Simulate time passing
        time.sleep(0.6)
        s.tick()
        self.assertEqual(s.state, SensorState.IDLE)

    def test_cannot_trigger_during_cooldown(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.trigger()
        s.clear()
        self.assertEqual(s.state, SensorState.COOLDOWN)
        event = s.trigger()
        self.assertIsNone(event)
        self.assertEqual(s.state, SensorState.COOLDOWN)

    def test_cannot_trigger_while_already_triggered(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.trigger()
        event = s.trigger()
        self.assertIsNone(event)
        self.assertEqual(s.state, SensorState.TRIGGERED)

    def test_clear_from_idle_does_nothing(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.clear()  # should not raise
        self.assertEqual(s.state, SensorState.IDLE)

    def test_tick_in_idle_stays_idle(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.tick()
        self.assertEqual(s.state, SensorState.IDLE)


class TestCooldownTiming(unittest.TestCase):
    """Test cooldown durations per sensor type."""

    def test_pir_cooldown_is_5s(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        self.assertEqual(s.cooldown_seconds, 5.0)

    def test_microwave_cooldown_is_0_5s(self):
        s = MotionSensor(sensor_id="mw-01", sensor_type="microwave")
        self.assertEqual(s.cooldown_seconds, 0.5)

    def test_acoustic_cooldown_is_1s(self):
        s = MotionSensor(sensor_id="ac-01", sensor_type="acoustic")
        self.assertEqual(s.cooldown_seconds, 1.0)

    def test_tripwire_cooldown_is_2s(self):
        s = MotionSensor(sensor_id="tw-01", sensor_type="tripwire")
        self.assertEqual(s.cooldown_seconds, 2.0)

    def test_cooldown_not_expired_stays_in_cooldown(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.trigger()
        s.clear()
        # PIR has 5s cooldown, should still be in cooldown immediately
        s.tick()
        self.assertEqual(s.state, SensorState.COOLDOWN)

    def test_microwave_cooldown_expires_fast(self):
        s = MotionSensor(sensor_id="mw-01", sensor_type="microwave")
        s.trigger()
        s.clear()
        time.sleep(0.6)
        s.tick()
        self.assertEqual(s.state, SensorState.IDLE)


class TestConfidence(unittest.TestCase):
    """Test confidence values on trigger events."""

    def test_confidence_in_range(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        for _ in range(50):
            s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
            event = s.trigger()
            self.assertGreaterEqual(event["confidence"], 0.7)
            self.assertLessEqual(event["confidence"], 1.0)

    def test_confidence_varies(self):
        """Over many triggers, we should see different confidence values."""
        confidences = set()
        for _ in range(20):
            s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
            event = s.trigger()
            confidences.add(round(event["confidence"], 2))
        # Should have more than 1 unique value over 20 samples
        self.assertGreater(len(confidences), 1)


class TestEventFormat(unittest.TestCase):
    """Test the detection event JSON structure matches spec."""

    def test_event_has_required_fields(self):
        s = MotionSensor(
            sensor_id="demo-pir-01",
            sensor_type="pir",
            zone="front_door",
            position_x=25.0,
            position_y=-10.0,
        )
        event = s.trigger()
        self.assertEqual(event["sensor_id"], "demo-pir-01")
        self.assertEqual(event["sensor_type"], "pir")
        self.assertEqual(event["event"], "motion_detected")
        self.assertIn("confidence", event)
        self.assertEqual(event["position"], {"x": 25.0, "y": -10.0})
        self.assertEqual(event["zone"], "front_door")
        self.assertIn("timestamp", event)
        self.assertIn("metadata", event)

    def test_event_metadata_has_duration_and_amplitude(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        event = s.trigger()
        meta = event["metadata"]
        self.assertIn("duration_ms", meta)
        self.assertIn("peak_amplitude", meta)
        self.assertIsInstance(meta["duration_ms"], int)
        self.assertIsInstance(meta["peak_amplitude"], float)

    def test_timestamp_is_iso8601_utc(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        event = s.trigger()
        ts = event["timestamp"]
        self.assertTrue(ts.endswith("Z"), f"Timestamp should end with Z: {ts}")
        # Should parse as valid ISO8601
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        self.assertIsNotNone(dt)

    def test_metadata_duration_is_positive(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        event = s.trigger()
        self.assertGreater(event["metadata"]["duration_ms"], 0)

    def test_metadata_peak_amplitude_in_range(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        event = s.trigger()
        amp = event["metadata"]["peak_amplitude"]
        self.assertGreaterEqual(amp, 0.0)
        self.assertLessEqual(amp, 1.0)


class TestSensorEnable(unittest.TestCase):
    """Test enable/disable functionality."""

    def test_sensor_starts_enabled(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        self.assertTrue(s.enabled)

    def test_disabled_sensor_cannot_trigger(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.enabled = False
        event = s.trigger()
        self.assertIsNone(event)
        self.assertEqual(s.state, SensorState.IDLE)

    def test_re_enabled_sensor_can_trigger(self):
        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        s.enabled = False
        s.enabled = True
        event = s.trigger()
        self.assertIsNotNone(event)


class TestUnknownSensorType(unittest.TestCase):
    """Test handling of unknown sensor types."""

    def test_unknown_type_gets_default_cooldown(self):
        s = MotionSensor(sensor_id="x-01", sensor_type="ultrasonic")
        # Should use a reasonable default cooldown
        self.assertGreater(s.cooldown_seconds, 0)


if __name__ == "__main__":
    unittest.main()
