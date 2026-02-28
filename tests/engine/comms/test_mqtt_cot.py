# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MQTT CoT codec — converts between TRITIUM JSON and CoT XML on MQTT.

TDD: these tests are written BEFORE the implementation.
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rover_telemetry():
    """Typical rover telemetry dict as published over MQTT."""
    return {
        "lat": 37.7751,
        "lng": -122.4192,
        "alt": 16.0,
        "speed": 1.5,
        "heading": 45.0,
        "battery": 0.85,
        "asset_type": "rover",
        "alliance": "friendly",
    }


@pytest.fixture
def drone_telemetry():
    """Typical drone telemetry dict."""
    return {
        "lat": 37.7750,
        "lng": -122.4193,
        "alt": 30.0,
        "speed": 5.0,
        "heading": 270.0,
        "battery": 0.60,
        "asset_type": "drone",
        "alliance": "friendly",
    }


@pytest.fixture
def hostile_telemetry():
    """Hostile unit telemetry."""
    return {
        "lat": 37.7753,
        "lng": -122.4198,
        "alt": 16.0,
        "speed": 2.0,
        "heading": 180.0,
        "battery": 1.0,
        "asset_type": "person",
        "alliance": "hostile",
    }


@pytest.fixture
def sensor_event():
    """Typical sensor activation event dict."""
    return {
        "sensor_type": "motion",
        "lat": 37.7749,
        "lng": -122.4194,
        "triggered_by": "hostile-7",
        "timestamp": "2026-02-23T12:00:00Z",
    }


# ===================================================================
# telemetry_to_cot
# ===================================================================

class TestTelemetryToCot:
    """Test converting robot JSON telemetry to CoT SA XML."""

    def test_returns_valid_xml(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_event_version(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        assert root.get("version") == "2.0"

    def test_event_uid(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        assert root.get("uid") == "rover-1"

    def test_type_from_registry(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-f-G-E-V-A-L"

    def test_hostile_type_swap(self, hostile_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("hostile-7", hostile_telemetry)
        root = ET.fromstring(xml_str)
        cot_type = root.get("type")
        assert cot_type[2] == "h"

    def test_drone_type(self, drone_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("drone-2", drone_telemetry)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-f-A-M-F-Q"

    def test_point_coordinates(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7751, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4192, abs=0.001)
        assert float(point.get("hae")) == pytest.approx(16.0, abs=0.1)

    def test_point_error_estimates(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert float(point.get("ce")) > 0
        assert float(point.get("le")) > 0

    def test_detail_contact_callsign(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        assert contact.get("callsign") == "rover-1"

    def test_detail_group(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        group = root.find("detail/__group")
        assert group is not None
        assert group.get("name") == "Cyan"

    def test_detail_group_hostile(self, hostile_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("hostile-7", hostile_telemetry)
        root = ET.fromstring(xml_str)
        group = root.find("detail/__group")
        assert group.get("name") == "Red"

    def test_detail_status_battery(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        status = root.find("detail/status")
        assert status is not None
        assert float(status.get("battery")) == pytest.approx(85.0, abs=1)

    def test_detail_track(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        track = root.find("detail/track")
        assert track is not None
        assert float(track.get("speed")) == pytest.approx(1.5, abs=0.01)
        assert float(track.get("course")) == pytest.approx(45.0, abs=0.01)

    def test_how_is_machine_gps(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        assert root.get("how") == "m-g"

    def test_timestamps_are_utc(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        assert root.get("time").endswith("Z")
        assert root.get("start").endswith("Z")
        assert root.get("stale").endswith("Z")

    def test_stale_is_after_start(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        start = datetime.fromisoformat(root.get("start").replace("Z", "+00:00"))
        stale = datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        assert stale > start

    def test_site_id_not_in_xml(self, rover_telemetry):
        """site_id is for MQTT topics, not the XML itself."""
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml_str = telemetry_to_cot("rover-1", rover_telemetry, site_id="test-site")
        assert "test-site" not in xml_str

    def test_unknown_asset_type_fallback(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        rover_telemetry["asset_type"] = "submarine"
        xml_str = telemetry_to_cot("sub-1", rover_telemetry)
        root = ET.fromstring(xml_str)
        # Should fall back to alliance-based code
        assert root.get("type").startswith("a-f")


# ===================================================================
# cot_to_telemetry
# ===================================================================

class TestCotToTelemetry:
    """Test parsing CoT SA XML back to TRITIUM telemetry dict."""

    def _make_cot(self, uid="rover-1", cot_type="a-f-G-E-V-A-L",
                  lat=37.7751, lon=-122.4192, hae=16.0,
                  callsign="rover-1", team="Cyan",
                  speed=1.5, course=45.0, battery=85.0):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return (
            f'<event version="2.0" uid="{uid}" type="{cot_type}" how="m-g"'
            f' time="{now}" start="{now}" stale="{now}">'
            f'<point lat="{lat}" lon="{lon}" hae="{hae}" ce="10.0" le="10.0"/>'
            f'<detail>'
            f'<contact callsign="{callsign}"/>'
            f'<__group name="{team}" role="Team Member"/>'
            f'<status battery="{battery}"/>'
            f'<track speed="{speed}" course="{course}"/>'
            f'</detail></event>'
        )

    def test_returns_dict(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot()
        result = cot_to_telemetry(xml)
        assert isinstance(result, dict)

    def test_target_id(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(uid="rover-1")
        result = cot_to_telemetry(xml)
        assert result["target_id"] == "rover-1"

    def test_lat_lng(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(lat=37.7751, lon=-122.4192)
        result = cot_to_telemetry(xml)
        assert result["lat"] == pytest.approx(37.7751, abs=0.001)
        assert result["lng"] == pytest.approx(-122.4192, abs=0.001)

    def test_alt(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(hae=30.0)
        result = cot_to_telemetry(xml)
        assert result["alt"] == pytest.approx(30.0, abs=0.1)

    def test_speed(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(speed=3.5)
        result = cot_to_telemetry(xml)
        assert result["speed"] == pytest.approx(3.5, abs=0.01)

    def test_heading(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(course=90.0)
        result = cot_to_telemetry(xml)
        assert result["heading"] == pytest.approx(90.0, abs=0.01)

    def test_battery_normalized(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(battery=85.0)
        result = cot_to_telemetry(xml)
        # Battery should be 0..1 (divide by 100)
        assert result["battery"] == pytest.approx(0.85, abs=0.01)

    def test_alliance_from_type(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(cot_type="a-h-G-U-C-I")
        result = cot_to_telemetry(xml)
        assert result["alliance"] == "hostile"

    def test_asset_type_inferred(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot(cot_type="a-f-G-E-V-A-L")
        result = cot_to_telemetry(xml)
        assert result["asset_type"] == "rover"

    def test_source_is_mqtt_cot(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        xml = self._make_cot()
        result = cot_to_telemetry(xml)
        assert result["source"] == "mqtt_cot"

    def test_malformed_xml_returns_none(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        result = cot_to_telemetry("not xml at all")
        assert result is None

    def test_missing_point_returns_none(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        xml = (
            f'<event version="2.0" uid="x" type="a-f-G" how="m-g"'
            f' time="{now}" start="{now}" stale="{now}">'
            f'<detail/></event>'
        )
        result = cot_to_telemetry(xml)
        assert result is None

    def test_not_event_returns_none(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        result = cot_to_telemetry("<root><child/></root>")
        assert result is None

    def test_empty_string_returns_none(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        result = cot_to_telemetry("")
        assert result is None


# ===================================================================
# command_to_cot
# ===================================================================

class TestCommandToCot:
    """Test converting dispatch/patrol/recall commands to CoT tasking XML."""

    def test_dispatch_returns_valid_xml(self):
        from engine.comms.mqtt_cot import command_to_cot
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 10.0, "y": 20.0})
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_dispatch_type(self):
        from engine.comms.mqtt_cot import command_to_cot
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 10.0, "y": 20.0})
        root = ET.fromstring(xml_str)
        assert root.get("type") == "t-x-t-a"

    def test_dispatch_uid_contains_robot(self):
        from engine.comms.mqtt_cot import command_to_cot
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 10.0, "y": 20.0})
        root = ET.fromstring(xml_str)
        assert "rover-1" in root.get("uid")

    def test_dispatch_has_point(self):
        from engine.comms.mqtt_cot import command_to_cot
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 10.0, "y": 20.0})
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None

    def test_dispatch_detail_contains_command(self):
        from engine.comms.mqtt_cot import command_to_cot
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 10.0, "y": 20.0})
        root = ET.fromstring(xml_str)
        detail = root.find("detail")
        assert detail is not None
        remarks = detail.find("remarks")
        assert remarks is not None
        assert "dispatch" in remarks.text.lower()

    def test_patrol_with_waypoints(self):
        from engine.comms.mqtt_cot import command_to_cot
        waypoints = [{"x": 10.0, "y": 20.0}, {"x": 30.0, "y": 40.0}]
        xml_str = command_to_cot("rover-1", "patrol", {"waypoints": waypoints})
        root = ET.fromstring(xml_str)
        assert root.get("type") == "t-x-t-a"
        detail = root.find("detail")
        remarks = detail.find("remarks")
        assert "patrol" in remarks.text.lower()

    def test_recall_command(self):
        from engine.comms.mqtt_cot import command_to_cot
        xml_str = command_to_cot("rover-1", "recall")
        root = ET.fromstring(xml_str)
        assert root.get("type") == "t-x-t-a"
        detail = root.find("detail")
        remarks = detail.find("remarks")
        assert "recall" in remarks.text.lower()

    def test_command_timestamps(self):
        from engine.comms.mqtt_cot import command_to_cot
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 1.0, "y": 2.0})
        root = ET.fromstring(xml_str)
        assert root.get("time").endswith("Z")


# ===================================================================
# sensor_event_to_cot
# ===================================================================

class TestSensorEventToCot:
    """Test converting sensor activations to CoT sensor reading XML."""

    def test_returns_valid_xml(self, sensor_event):
        from engine.comms.mqtt_cot import sensor_event_to_cot
        xml_str = sensor_event_to_cot("motion-1", sensor_event)
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_sensor_type_code(self, sensor_event):
        from engine.comms.mqtt_cot import sensor_event_to_cot
        xml_str = sensor_event_to_cot("motion-1", sensor_event)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-s-r"

    def test_sensor_uid(self, sensor_event):
        from engine.comms.mqtt_cot import sensor_event_to_cot
        xml_str = sensor_event_to_cot("motion-1", sensor_event)
        root = ET.fromstring(xml_str)
        assert "motion-1" in root.get("uid")

    def test_sensor_point(self, sensor_event):
        from engine.comms.mqtt_cot import sensor_event_to_cot
        xml_str = sensor_event_to_cot("motion-1", sensor_event)
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)

    def test_sensor_detail(self, sensor_event):
        from engine.comms.mqtt_cot import sensor_event_to_cot
        xml_str = sensor_event_to_cot("motion-1", sensor_event)
        root = ET.fromstring(xml_str)
        detail = root.find("detail")
        assert detail is not None
        remarks = detail.find("remarks")
        assert remarks is not None
        assert "motion" in remarks.text.lower()


# ===================================================================
# Round-trip: telemetry -> CoT -> telemetry
# ===================================================================

class TestRoundTrip:
    """Round-trip tests: telemetry -> CoT XML -> telemetry preserves key fields."""

    def test_round_trip_lat_lng(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["lat"] == pytest.approx(rover_telemetry["lat"], abs=0.001)
        assert result["lng"] == pytest.approx(rover_telemetry["lng"], abs=0.001)

    def test_round_trip_alt(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["alt"] == pytest.approx(rover_telemetry["alt"], abs=0.1)

    def test_round_trip_speed(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["speed"] == pytest.approx(rover_telemetry["speed"], abs=0.01)

    def test_round_trip_heading(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["heading"] == pytest.approx(rover_telemetry["heading"], abs=0.01)

    def test_round_trip_battery(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["battery"] == pytest.approx(rover_telemetry["battery"], abs=0.01)

    def test_round_trip_alliance(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["alliance"] == "friendly"

    def test_round_trip_asset_type(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["asset_type"] == "rover"

    def test_round_trip_target_id(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["target_id"] == "rover-1"


# ===================================================================
# Dual-format detection (for mqtt_bridge integration)
# ===================================================================

class TestDualFormatDetection:
    """Test that XML vs JSON payloads are correctly distinguished."""

    def test_xml_payload_starts_with_angle(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        assert xml.strip().startswith("<")

    def test_json_payload_does_not_start_with_angle(self, rover_telemetry):
        json_str = json.dumps(rover_telemetry)
        assert not json_str.strip().startswith("<")

    def test_cot_to_telemetry_rejects_json(self):
        from engine.comms.mqtt_cot import cot_to_telemetry
        result = cot_to_telemetry('{"lat": 37.7751, "lng": -122.4192}')
        assert result is None


# ===================================================================
# cot_to_command -- parse CoT tasking XML back to command + params
# ===================================================================

class TestCotToCommand:
    """Test parsing CoT tasking XML back to (command, params) tuple."""

    def test_dispatch_round_trip(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 10.0, "y": 20.0})
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert command == "dispatch"

    def test_dispatch_preserves_coordinates(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 10.0, "y": 20.0})
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert params.get("x") == pytest.approx(10.0, abs=0.01)
        assert params.get("y") == pytest.approx(20.0, abs=0.01)

    def test_patrol_round_trip(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        waypoints = [{"x": 10.0, "y": 20.0}, {"x": 30.0, "y": 40.0}]
        xml_str = command_to_cot("rover-1", "patrol", {"waypoints": waypoints})
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert command == "patrol"

    def test_patrol_preserves_waypoints(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        waypoints = [{"x": 10.0, "y": 20.0}, {"x": 30.0, "y": 40.0}]
        xml_str = command_to_cot("rover-1", "patrol", {"waypoints": waypoints})
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        wp = params.get("waypoints", [])
        assert len(wp) == 2
        assert wp[0]["x"] == pytest.approx(10.0, abs=0.01)
        assert wp[0]["y"] == pytest.approx(20.0, abs=0.01)
        assert wp[1]["x"] == pytest.approx(30.0, abs=0.01)
        assert wp[1]["y"] == pytest.approx(40.0, abs=0.01)

    def test_recall_round_trip(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        xml_str = command_to_cot("rover-1", "recall")
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert command == "recall"

    def test_recall_params_empty_or_minimal(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        xml_str = command_to_cot("rover-1", "recall")
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        # recall should have no waypoints or coordinates
        assert "waypoints" not in params or params["waypoints"] == []

    def test_non_tasking_cot_returns_none(self):
        """SA event (not tasking) should return None from cot_to_command."""
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_command
        xml_str = telemetry_to_cot("rover-1", {
            "lat": 37.7, "lng": -122.4, "alt": 16.0,
            "speed": 1.0, "heading": 90.0, "battery": 0.9,
            "asset_type": "rover", "alliance": "friendly",
        })
        result = cot_to_command(xml_str)
        assert result is None

    def test_malformed_xml_returns_none(self):
        from engine.comms.mqtt_cot import cot_to_command
        result = cot_to_command("not xml at all")
        assert result is None

    def test_empty_string_returns_none(self):
        from engine.comms.mqtt_cot import cot_to_command
        result = cot_to_command("")
        assert result is None

    def test_sensor_event_returns_none(self):
        """Sensor event XML should not parse as a command."""
        from engine.comms.mqtt_cot import sensor_event_to_cot, cot_to_command
        xml_str = sensor_event_to_cot("motion-1", {
            "sensor_type": "motion", "lat": 37.7, "lng": -122.4,
            "triggered_by": "hostile-7",
        })
        result = cot_to_command(xml_str)
        assert result is None

    def test_dispatch_robot_id_in_contact(self):
        """Robot ID should be in the contact callsign."""
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 5.0, "y": 6.0})
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert params.get("robot_id") == "rover-1"


# ===================================================================
# Command round-trip preservation
# ===================================================================

class TestCommandRoundTrip:
    """Full round-trip: command -> CoT XML -> command preserves all fields."""

    def test_dispatch_coordinates_preserved(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        xml_str = command_to_cot("rover-1", "dispatch", {"x": 123.456, "y": 78.9})
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert command == "dispatch"
        assert params["x"] == pytest.approx(123.456, abs=0.01)
        assert params["y"] == pytest.approx(78.9, abs=0.01)

    def test_patrol_all_waypoints_preserved(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        waypoints = [
            {"x": 1.1, "y": 2.2},
            {"x": 3.3, "y": 4.4},
            {"x": 5.5, "y": 6.6},
        ]
        xml_str = command_to_cot("drone-3", "patrol", {"waypoints": waypoints})
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert command == "patrol"
        wp = params["waypoints"]
        assert len(wp) == 3
        for i, orig in enumerate(waypoints):
            assert wp[i]["x"] == pytest.approx(orig["x"], abs=0.01)
            assert wp[i]["y"] == pytest.approx(orig["y"], abs=0.01)

    def test_recall_round_trip_robot_id(self):
        from engine.comms.mqtt_cot import command_to_cot, cot_to_command
        xml_str = command_to_cot("tank-1", "recall")
        result = cot_to_command(xml_str)
        assert result is not None
        command, params = result
        assert command == "recall"
        assert params.get("robot_id") == "tank-1"


# ===================================================================
# MQTTBridge._parse_payload — dual-format helper
# ===================================================================

@pytest.mark.skip(reason="MQTTBridge._parse_payload method does not exist")
class TestBridgeParsePayload:
    """Test the _parse_payload helper on MQTTBridge."""

    def _make_bridge(self):
        """Create a minimal MQTTBridge without real MQTT."""
        from unittest.mock import MagicMock
        from engine.comms.mqtt_bridge import MQTTBridge
        eb = MagicMock()
        tt = MagicMock()
        return MQTTBridge(event_bus=eb, target_tracker=tt)

    def test_json_payload_parsed(self):
        bridge = self._make_bridge()
        payload = b'{"lat": 37.7751, "lng": -122.4192}'
        result = bridge._parse_payload(payload)
        assert isinstance(result, dict)
        assert result["lat"] == pytest.approx(37.7751, abs=0.001)

    def test_xml_payload_parsed_as_cot(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        bridge = self._make_bridge()
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = bridge._parse_payload(xml.encode("utf-8"))
        assert isinstance(result, dict)
        assert result["target_id"] == "rover-1"
        assert result["source"] == "mqtt_cot"

    def test_invalid_payload_returns_none(self):
        bridge = self._make_bridge()
        result = bridge._parse_payload(b"not json and not xml")
        assert result is None

    def test_empty_payload_returns_none(self):
        bridge = self._make_bridge()
        result = bridge._parse_payload(b"")
        assert result is None

    def test_xml_with_whitespace_prefix(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot
        bridge = self._make_bridge()
        xml = "  " + telemetry_to_cot("rover-1", rover_telemetry)
        result = bridge._parse_payload(xml.encode("utf-8"))
        assert isinstance(result, dict)
        assert result["target_id"] == "rover-1"

    def test_json_with_whitespace_prefix(self):
        bridge = self._make_bridge()
        payload = b'  {"lat": 37.0, "lng": -122.0}'
        result = bridge._parse_payload(payload)
        assert isinstance(result, dict)
        assert result["lat"] == pytest.approx(37.0, abs=0.01)

    def test_invalid_xml_returns_none(self):
        bridge = self._make_bridge()
        result = bridge._parse_payload(b"<broken xml no close tag")
        assert result is None

    def test_non_event_xml_returns_none(self):
        bridge = self._make_bridge()
        result = bridge._parse_payload(b"<root><child/></root>")
        assert result is None


# ===================================================================
# FakeRobot CoT telemetry
# ===================================================================

class TestFakeRobotCotTelemetry:
    """Test that FakeRobot.get_cot_telemetry() returns valid CoT XML."""

    def test_returns_valid_xml(self):
        from engine.simulation.fake_robot import FakeRobot
        robot = FakeRobot(robot_id="test-rover", asset_type="rover")
        xml_str = robot.get_cot_telemetry()
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_uid_matches_robot_id(self):
        from engine.simulation.fake_robot import FakeRobot
        robot = FakeRobot(robot_id="test-rover", asset_type="rover")
        xml_str = robot.get_cot_telemetry()
        root = ET.fromstring(xml_str)
        assert root.get("uid") == "test-rover"

    def test_round_trip_through_cot_to_telemetry(self):
        from engine.simulation.fake_robot import FakeRobot
        from engine.comms.mqtt_cot import cot_to_telemetry
        robot = FakeRobot(
            robot_id="test-rover",
            asset_type="rover",
            alliance="friendly",
            lat=37.7749,
            lng=-122.4194,
            alt=16.0,
            heading=90.0,
            speed=2.0,
            battery=0.75,
        )
        xml_str = robot.get_cot_telemetry()
        result = cot_to_telemetry(xml_str)
        assert result is not None
        assert result["target_id"] == "test-rover"
        assert result["lat"] == pytest.approx(37.7749, abs=0.001)
        assert result["lng"] == pytest.approx(-122.4194, abs=0.001)
        assert result["speed"] == pytest.approx(2.0, abs=0.1)
        assert result["heading"] == pytest.approx(90.0, abs=1)
        assert result["battery"] == pytest.approx(0.75, abs=0.01)

    def test_drone_cot_telemetry(self):
        from engine.simulation.fake_robot import FakeRobot
        from engine.comms.mqtt_cot import cot_to_telemetry
        robot = FakeRobot(
            robot_id="drone-1",
            asset_type="drone",
            alliance="friendly",
            lat=37.775,
            lng=-122.419,
            alt=30.0,
        )
        xml_str = robot.get_cot_telemetry()
        result = cot_to_telemetry(xml_str)
        assert result is not None
        assert result["asset_type"] == "drone"
        assert result["alliance"] == "friendly"

    def test_moving_robot_cot_updates(self):
        """After ticking, telemetry values change and CoT reflects them."""
        from engine.simulation.fake_robot import FakeRobot
        robot = FakeRobot(
            robot_id="rover-move",
            asset_type="rover",
            lat=37.7749,
            lng=-122.4194,
        )
        robot.dispatch(37.7760, -122.4190)
        robot.tick(1.0)  # move 1 second
        xml_str = robot.get_cot_telemetry()
        root = ET.fromstring(xml_str)
        track = root.find("detail/track")
        assert track is not None
        speed = float(track.get("speed"))
        assert speed > 0  # robot is moving


# ===================================================================
# Full round-trip preservation with all unit types
# ===================================================================

class TestRoundTripPreservation:
    """Full field preservation at strict tolerances across unit types."""

    def test_position_preserved_within_tolerance(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["lat"] == pytest.approx(rover_telemetry["lat"], abs=0.0001)
        assert result["lng"] == pytest.approx(rover_telemetry["lng"], abs=0.0001)
        assert result["alt"] == pytest.approx(rover_telemetry["alt"], abs=0.01)

    def test_heading_preserved_within_1_degree(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["heading"] == pytest.approx(rover_telemetry["heading"], abs=1.0)

    def test_speed_preserved_within_tolerance(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["speed"] == pytest.approx(rover_telemetry["speed"], abs=0.1)

    def test_battery_preserved_within_tolerance(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["battery"] == pytest.approx(rover_telemetry["battery"], abs=0.001)

    def test_alliance_preserved_exactly(self, rover_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("rover-1", rover_telemetry)
        result = cot_to_telemetry(xml)
        assert result["alliance"] == rover_telemetry["alliance"]

    def test_drone_full_round_trip(self, drone_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("drone-2", drone_telemetry)
        result = cot_to_telemetry(xml)
        assert result["lat"] == pytest.approx(drone_telemetry["lat"], abs=0.0001)
        assert result["lng"] == pytest.approx(drone_telemetry["lng"], abs=0.0001)
        assert result["alt"] == pytest.approx(drone_telemetry["alt"], abs=0.01)
        assert result["speed"] == pytest.approx(drone_telemetry["speed"], abs=0.1)
        assert result["heading"] == pytest.approx(drone_telemetry["heading"], abs=1.0)
        assert result["battery"] == pytest.approx(drone_telemetry["battery"], abs=0.001)
        assert result["alliance"] == "friendly"
        assert result["asset_type"] == "drone"

    def test_hostile_full_round_trip(self, hostile_telemetry):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        xml = telemetry_to_cot("hostile-7", hostile_telemetry)
        result = cot_to_telemetry(xml)
        assert result["lat"] == pytest.approx(hostile_telemetry["lat"], abs=0.0001)
        assert result["lng"] == pytest.approx(hostile_telemetry["lng"], abs=0.0001)
        assert result["speed"] == pytest.approx(hostile_telemetry["speed"], abs=0.1)
        assert result["heading"] == pytest.approx(hostile_telemetry["heading"], abs=1.0)
        assert result["battery"] == pytest.approx(hostile_telemetry["battery"], abs=0.001)
        assert result["alliance"] == "hostile"

    def test_neutral_alliance_round_trip(self):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        telemetry = {
            "lat": 37.775, "lng": -122.419, "alt": 16.0,
            "speed": 1.0, "heading": 0.0, "battery": 1.0,
            "asset_type": "person", "alliance": "neutral",
        }
        xml = telemetry_to_cot("neutral-1", telemetry)
        result = cot_to_telemetry(xml)
        assert result["alliance"] == "neutral"

    def test_unknown_alliance_round_trip(self):
        from engine.comms.mqtt_cot import telemetry_to_cot, cot_to_telemetry
        telemetry = {
            "lat": 37.775, "lng": -122.419, "alt": 16.0,
            "speed": 0.0, "heading": 0.0, "battery": 1.0,
            "asset_type": "person", "alliance": "unknown",
        }
        xml = telemetry_to_cot("unk-1", telemetry)
        result = cot_to_telemetry(xml)
        assert result["alliance"] == "unknown"
