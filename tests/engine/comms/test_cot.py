# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for CoT (Cursor on Target) XML generation and parsing.

TDD: these tests are written BEFORE the implementation.
"""

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def friendly_rover():
    """A friendly rover target dict (from SimulationTarget.to_dict())."""
    return {
        "target_id": "rover-1",
        "name": "Rover Alpha",
        "alliance": "friendly",
        "asset_type": "rover",
        "position": {"x": 10.0, "y": 20.0},
        "lat": 37.7751,
        "lng": -122.4192,
        "alt": 16.0,
        "heading": 45.0,
        "speed": 1.5,
        "battery": 0.85,
        "status": "active",
        "health": 150.0,
        "max_health": 150.0,
        "kills": 2,
        "is_combatant": True,
        "weapon_range": 10.0,
    }


@pytest.fixture
def hostile_person():
    """A hostile person target dict."""
    return {
        "target_id": "hostile-7",
        "name": "Hostile 7",
        "alliance": "hostile",
        "asset_type": "person",
        "position": {"x": -30.0, "y": 50.0},
        "lat": 37.7753,
        "lng": -122.4198,
        "alt": 16.0,
        "heading": 180.0,
        "speed": 2.0,
        "battery": 1.0,
        "status": "active",
        "health": 80.0,
        "max_health": 80.0,
        "kills": 0,
        "is_combatant": True,
        "weapon_range": 8.0,
    }


@pytest.fixture
def neutral_person():
    """A neutral person target dict."""
    return {
        "target_id": "neutral-3",
        "name": "Pedestrian 3",
        "alliance": "neutral",
        "asset_type": "person",
        "position": {"x": 0.0, "y": 0.0},
        "lat": 37.7749,
        "lng": -122.4194,
        "alt": 16.0,
        "heading": 90.0,
        "speed": 1.0,
        "battery": 1.0,
        "status": "active",
        "health": 50.0,
        "max_health": 50.0,
        "kills": 0,
        "is_combatant": False,
        "weapon_range": 0.0,
    }


@pytest.fixture
def friendly_drone():
    """A friendly drone target dict."""
    return {
        "target_id": "drone-2",
        "name": "Drone Beta",
        "alliance": "friendly",
        "asset_type": "drone",
        "position": {"x": 5.0, "y": 10.0},
        "lat": 37.7750,
        "lng": -122.4193,
        "alt": 30.0,
        "heading": 270.0,
        "speed": 5.0,
        "battery": 0.60,
        "status": "active",
        "health": 60.0,
        "max_health": 60.0,
        "kills": 1,
        "is_combatant": True,
        "weapon_range": 12.0,
    }


@pytest.fixture
def friendly_turret():
    """A friendly turret target dict."""
    return {
        "target_id": "turret-1",
        "name": "Turret 1",
        "alliance": "friendly",
        "asset_type": "turret",
        "position": {"x": 0.0, "y": 0.0},
        "lat": 37.7749,
        "lng": -122.4194,
        "alt": 16.0,
        "heading": 0.0,
        "speed": 0.0,
        "battery": 0.99,
        "status": "stationary",
        "health": 200.0,
        "max_health": 200.0,
        "kills": 5,
        "is_combatant": True,
        "weapon_range": 20.0,
    }


# ===================================================================
# target_to_cot_xml
# ===================================================================

class TestTargetToCotXml:
    """Test CoT XML generation from target dicts."""

    def test_returns_valid_xml(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_event_attributes(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        assert root.get("version") == "2.0"
        assert root.get("uid") == "rover-1"
        assert root.get("how") is not None
        assert root.get("type") is not None
        assert root.get("time") is not None
        assert root.get("start") is not None
        assert root.get("stale") is not None

    def test_friendly_rover_type(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-f-G-E-V-A-L"

    def test_friendly_drone_type(self, friendly_drone):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_drone)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-f-A-M-F-Q"

    def test_friendly_turret_type(self, friendly_turret):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_turret)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-f-G-E-W-D"

    def test_hostile_person_type(self, hostile_person):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(hostile_person)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-h-G-U-C-I"

    def test_neutral_person_type(self, neutral_person):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(neutral_person)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-n-G-U-C"

    def test_unknown_alliance_type(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        friendly_rover["alliance"] = "unknown"
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        # Should fall back to unknown ground
        assert root.get("type").startswith("a-u-G")

    def test_point_element(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7751, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4192, abs=0.001)
        assert float(point.get("hae")) == pytest.approx(16.0, abs=0.1)
        assert float(point.get("ce")) > 0
        assert float(point.get("le")) > 0

    def test_detail_contact(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        assert contact.get("callsign") == "Rover Alpha"

    def test_detail_group(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        group = root.find("detail/__group")
        assert group is not None
        assert group.get("name") == "Cyan"
        assert group.get("role") == "Team Member"

    def test_hostile_team_color(self, hostile_person):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(hostile_person)
        root = ET.fromstring(xml_str)
        group = root.find("detail/__group")
        assert group.get("name") == "Red"

    def test_neutral_team_color(self, neutral_person):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(neutral_person)
        root = ET.fromstring(xml_str)
        group = root.find("detail/__group")
        assert group.get("name") == "White"

    def test_detail_status_battery(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        status = root.find("detail/status")
        assert status is not None
        assert float(status.get("battery")) == pytest.approx(85.0, abs=1)

    def test_detail_track(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        track = root.find("detail/track")
        assert track is not None
        assert float(track.get("speed")) == pytest.approx(1.5, abs=0.01)
        assert float(track.get("course")) == pytest.approx(45.0, abs=0.01)

    def test_detail_remarks(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert "health:150.0/150.0" in remarks.text
        assert "kills:2" in remarks.text

    def test_detail_uid_droid(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        uid = root.find("detail/uid")
        assert uid is not None
        assert uid.get("Droid") == "Rover Alpha"

    def test_how_code_simulation_source(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        # Default source is simulation
        assert root.get("how") == "m-s"

    def test_how_code_yolo_source(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        friendly_rover["source"] = "yolo"
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        assert root.get("how") == "m-r"

    def test_how_code_mqtt_source(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        friendly_rover["source"] = "mqtt"
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        assert root.get("how") == "m-g"

    def test_how_code_manual_source(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        friendly_rover["source"] = "manual"
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        assert root.get("how") == "h-e"

    def test_stale_seconds(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover, stale_seconds=60)
        root = ET.fromstring(xml_str)
        start = datetime.fromisoformat(root.get("start").replace("Z", "+00:00"))
        stale = datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        delta = (stale - start).total_seconds()
        assert delta == pytest.approx(60.0, abs=2.0)

    def test_opex_attribute(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover, opex="e")
        root = ET.fromstring(xml_str)
        assert root.get("opex") == "e"

    def test_camera_sensor_type(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        friendly_rover["asset_type"] = "camera"
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-f-G-E-S-E"

    def test_fallback_type_unknown_asset(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        friendly_rover["asset_type"] = "submarine"
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        # Falls back to alliance-only ground type
        assert root.get("type") == "a-f-G"

    def test_zero_battery(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        friendly_rover["battery"] = 0.0
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        status = root.find("detail/status")
        assert float(status.get("battery")) == pytest.approx(0.0, abs=0.1)

    def test_timestamps_are_utc_iso(self, friendly_rover):
        from engine.comms.cot import target_to_cot_xml
        xml_str = target_to_cot_xml(friendly_rover)
        root = ET.fromstring(xml_str)
        time_str = root.get("time")
        # Should end with Z and be parseable
        assert time_str.endswith("Z")
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        assert dt.tzinfo is not None


# ===================================================================
# cot_xml_to_target
# ===================================================================

class TestCotXmlToTarget:
    """Test parsing inbound CoT XML into target dicts."""

    def _make_cot_xml(self, uid="atak-user-1", cot_type="a-f-G-U-C",
                      lat=37.7749, lon=-122.4194, hae=16.0,
                      callsign="John", team="Cyan", speed=1.0, course=0.0):
        """Helper to build a CoT XML string."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="{uid}" type="{cot_type}" how="h-e"
       time="{now}" start="{now}" stale="{now}">
  <point lat="{lat}" lon="{lon}" hae="{hae}" ce="10.0" le="10.0"/>
  <detail>
    <contact callsign="{callsign}"/>
    <__group name="{team}" role="Team Member"/>
    <track speed="{speed}" course="{course}"/>
  </detail>
</event>"""

    def test_parse_friendly(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(cot_type="a-f-G-U-C")
        result = cot_xml_to_target(xml)
        assert result is not None
        assert result["alliance"] == "friendly"

    def test_parse_hostile(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(cot_type="a-h-G-U-C-I")
        result = cot_xml_to_target(xml)
        assert result is not None
        assert result["alliance"] == "hostile"

    def test_parse_neutral(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(cot_type="a-n-G-U-C")
        result = cot_xml_to_target(xml)
        assert result is not None
        assert result["alliance"] == "neutral"

    def test_parse_unknown(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(cot_type="a-u-G")
        result = cot_xml_to_target(xml)
        assert result is not None
        assert result["alliance"] == "unknown"

    def test_target_id_from_uid(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(uid="ANDROID-abc123")
        result = cot_xml_to_target(xml)
        assert result["target_id"] == "ANDROID-abc123"

    def test_callsign_as_name(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(callsign="Operator-1")
        result = cot_xml_to_target(xml)
        assert result["name"] == "Operator-1"

    def test_position_from_latlng(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(lat=37.7749, lon=-122.4194)
        result = cot_xml_to_target(xml)
        pos = result["position"]
        assert "x" in pos
        assert "y" in pos

    def test_speed_and_heading(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(speed=3.5, course=90.0)
        result = cot_xml_to_target(xml)
        assert result["speed"] == pytest.approx(3.5, abs=0.01)
        assert result["heading"] == pytest.approx(90.0, abs=0.01)

    def test_malformed_xml_returns_none(self):
        from engine.comms.cot import cot_xml_to_target
        result = cot_xml_to_target("not xml at all")
        assert result is None

    def test_missing_point_returns_none(self):
        from engine.comms.cot import cot_xml_to_target
        xml = '<event version="2.0" uid="test" type="a-f-G" how="h-e" time="2026-01-01T00:00:00Z" start="2026-01-01T00:00:00Z" stale="2026-01-01T01:00:00Z"><detail/></event>'
        result = cot_xml_to_target(xml)
        assert result is None

    def test_asset_type_inferred_ground(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(cot_type="a-f-G-E-V")
        result = cot_xml_to_target(xml)
        assert result["asset_type"] == "rover"

    def test_asset_type_inferred_air(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(cot_type="a-f-A-M-H")
        result = cot_xml_to_target(xml)
        assert result["asset_type"] == "drone"

    def test_no_callsign_uses_uid(self):
        from engine.comms.cot import cot_xml_to_target
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        xml = f"""<event version="2.0" uid="device-99" type="a-f-G" how="h-e"
                   time="{now}" start="{now}" stale="{now}">
          <point lat="37.7749" lon="-122.4194" hae="16.0" ce="10" le="10"/>
          <detail/>
        </event>"""
        result = cot_xml_to_target(xml)
        assert result is not None
        assert result["name"] == "device-99"

    def test_alt_from_hae(self):
        from engine.comms.cot import cot_xml_to_target
        xml = self._make_cot_xml(hae=50.0)
        result = cot_xml_to_target(xml)
        assert result.get("alt") == pytest.approx(50.0, abs=0.1)


# ===================================================================
# make_sa_cot
# ===================================================================

class TestMakeSaCot:
    """Test self-SA (situational awareness) CoT generation."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.7749, -122.4194, 16.0, "Cyan", "HQ")
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_sa_type(self):
        from engine.comms.cot import make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.7749, -122.4194, 16.0, "Cyan", "HQ")
        root = ET.fromstring(xml_str)
        assert root.get("type") == "a-f-G-E-C-I"

    def test_sa_uid_contains_callsign(self):
        from engine.comms.cot import make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.7749, -122.4194, 16.0, "Cyan", "HQ")
        root = ET.fromstring(xml_str)
        assert "TRITIUM-SC" in root.get("uid")

    def test_sa_point(self):
        from engine.comms.cot import make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.7749, -122.4194, 16.0, "Cyan", "HQ")
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)

    def test_sa_callsign(self):
        from engine.comms.cot import make_sa_cot
        xml_str = make_sa_cot("MY-HQ", 37.7749, -122.4194, 16.0, "Cyan", "HQ")
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact.get("callsign") == "MY-HQ"

    def test_sa_group(self):
        from engine.comms.cot import make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.7749, -122.4194, 16.0, "Cyan", "HQ")
        root = ET.fromstring(xml_str)
        group = root.find("detail/__group")
        assert group.get("name") == "Cyan"
        assert group.get("role") == "HQ"

    def test_sa_how_is_human(self):
        from engine.comms.cot import make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.7749, -122.4194, 16.0, "Cyan", "HQ")
        root = ET.fromstring(xml_str)
        assert root.get("how") == "h-g-i-g-o"


# ===================================================================
# video_feed_to_cot
# ===================================================================

class TestVideoFeedToCot:
    """Test video feed CoT XML generation."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot("cam-01", "rtsp://192.168.1.100:554/stream1")
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_type_is_video_feed(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot("cam-01", "rtsp://192.168.1.100:554/stream1")
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-i-v"

    def test_uid_contains_feed_id(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot("cam-01", "rtsp://192.168.1.100:554/stream1")
        root = ET.fromstring(xml_str)
        assert "cam-01" in root.get("uid")

    def test_point_element(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "rtsp://192.168.1.100:554/stream1",
            lat=37.7749, lng=-122.4194, alt=16.0,
        )
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)

    def test_video_detail_element(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot("cam-01", "rtsp://192.168.1.100:554/stream1")
        root = ET.fromstring(xml_str)
        video = root.find("detail/__video")
        assert video is not None
        assert video.get("url") == "rtsp://192.168.1.100:554/stream1"

    def test_stale_seconds(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot("cam-01", "rtsp://192.168.1.100:554/stream1", stale_seconds=600)
        root = ET.fromstring(xml_str)
        start = datetime.fromisoformat(root.get("start").replace("Z", "+00:00"))
        stale = datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        delta = (stale - start).total_seconds()
        assert delta == pytest.approx(600.0, abs=2.0)

    def test_default_position_is_zero(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot("cam-01", "rtsp://192.168.1.100:554/stream1")
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert float(point.get("lat")) == pytest.approx(0.0)
        assert float(point.get("lon")) == pytest.approx(0.0)


# ===================================================================
# emergency_to_cot
# ===================================================================

class TestEmergencyToCot:
    """Test emergency CoT XML generation."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_type_911(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-a-o-tbl"

    def test_type_cancel(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "cancel", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-a-o-can"

    def test_uid_contains_callsign(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        assert "TRITIUM-SC" in root.get("uid")

    def test_point_element(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194, alt=16.0)
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)

    def test_emergency_detail(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        emergency = root.find("detail/emergency")
        assert emergency is not None
        assert emergency.get("type") == "911"

    def test_remarks_present(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot(
            "TRITIUM-SC", "911", 37.7749, -122.4194,
            remarks="Intruder detected in sector 7"
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert "Intruder detected in sector 7" in remarks.text

    def test_contact_callsign(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("ALPHA-HQ", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        assert contact.get("callsign") == "ALPHA-HQ"


# ===================================================================
# tasking_to_cot
# ===================================================================

class TestTaskingToCot:
    """Test tasking CoT XML generation."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch")
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_type_is_tasking(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch")
        root = ET.fromstring(xml_str)
        assert root.get("type") == "t-x-t-a"

    def test_uid_contains_task_id(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch")
        root = ET.fromstring(xml_str)
        assert "task-001" in root.get("uid")

    def test_point_element(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch", lat=37.7749, lng=-122.4194)
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)

    def test_tasking_detail(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch")
        root = ET.fromstring(xml_str)
        tasking = root.find("detail/tasking")
        assert tasking is not None
        assert tasking.get("task_id") == "task-001"
        assert tasking.get("assignee_uid") == "rover-1"
        assert tasking.get("task_type") == "dispatch"

    def test_remarks(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot(
            "task-002", "drone-1", "patrol",
            remarks="Patrol north sector"
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert "Patrol north sector" in remarks.text

    def test_default_position_is_zero(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch")
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert float(point.get("lat")) == pytest.approx(0.0)
        assert float(point.get("lon")) == pytest.approx(0.0)


# ===================================================================
# cot_xml_to_tasking
# ===================================================================

class TestCotXmlToTasking:
    """Test parsing tasking CoT XML."""

    def test_round_trip(self):
        from engine.comms.cot import tasking_to_cot, cot_xml_to_tasking
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch", lat=37.77, lng=-122.42, remarks="Go north")
        result = cot_xml_to_tasking(xml_str)
        assert result is not None
        assert result["task_id"] == "task-001"
        assert result["assignee_uid"] == "rover-1"
        assert result["task_type"] == "dispatch"
        assert result["lat"] == pytest.approx(37.77, abs=0.001)
        assert result["lng"] == pytest.approx(-122.42, abs=0.001)
        assert "Go north" in result["remarks"]

    def test_returns_none_for_non_tasking(self):
        from engine.comms.cot import cot_xml_to_tasking, make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.77, -122.42, 16.0, "Cyan", "HQ")
        result = cot_xml_to_tasking(xml_str)
        assert result is None

    def test_returns_none_for_malformed_xml(self):
        from engine.comms.cot import cot_xml_to_tasking
        result = cot_xml_to_tasking("not xml")
        assert result is None

    def test_patrol_task_type(self):
        from engine.comms.cot import tasking_to_cot, cot_xml_to_tasking
        xml_str = tasking_to_cot("task-003", "drone-2", "patrol")
        result = cot_xml_to_tasking(xml_str)
        assert result is not None
        assert result["task_type"] == "patrol"

    def test_recall_task_type(self):
        from engine.comms.cot import tasking_to_cot, cot_xml_to_tasking
        xml_str = tasking_to_cot("task-004", "rover-3", "recall")
        result = cot_xml_to_tasking(xml_str)
        assert result is not None
        assert result["task_type"] == "recall"


# ===================================================================
# cot_xml_to_emergency
# ===================================================================

class TestCotXmlToEmergency:
    """Test parsing emergency CoT XML."""

    def test_round_trip(self):
        from engine.comms.cot import emergency_to_cot, cot_xml_to_emergency
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.77, -122.42, remarks="Help needed")
        result = cot_xml_to_emergency(xml_str)
        assert result is not None
        assert result["callsign"] == "TRITIUM-SC"
        assert result["emergency_type"] == "911"
        assert result["lat"] == pytest.approx(37.77, abs=0.001)
        assert result["lng"] == pytest.approx(-122.42, abs=0.001)
        assert "Help needed" in result["remarks"]

    def test_returns_none_for_non_emergency(self):
        from engine.comms.cot import cot_xml_to_emergency, make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.77, -122.42, 16.0, "Cyan", "HQ")
        result = cot_xml_to_emergency(xml_str)
        assert result is None

    def test_returns_none_for_malformed_xml(self):
        from engine.comms.cot import cot_xml_to_emergency
        result = cot_xml_to_emergency("not xml")
        assert result is None

    def test_cancel_type(self):
        from engine.comms.cot import emergency_to_cot, cot_xml_to_emergency
        xml_str = emergency_to_cot("HQ", "cancel", 37.77, -122.42)
        result = cot_xml_to_emergency(xml_str)
        assert result is not None
        assert result["emergency_type"] == "cancel"
