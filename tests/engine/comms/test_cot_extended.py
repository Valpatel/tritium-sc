"""Tests for Phase 4 Extended CoT Event Types.

TDD: ALL tests written BEFORE implementation.
Tests cover: video feed, emergency, tasking, sensor reading, spot report
builder functions + inbound routing + outbound bridge methods.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def target_tracker():
    tracker = MagicMock()
    tracker.get_all.return_value = []
    return tracker


@pytest.fixture
def bridge(event_bus, target_tracker):
    from engine.comms.tak_bridge import TAKBridge
    return TAKBridge(
        event_bus=event_bus,
        target_tracker=target_tracker,
        cot_url="tcp://localhost:8088",
        callsign="TEST-HQ",
        team="Cyan",
        role="HQ",
        publish_interval=1.0,
        stale_seconds=60,
    )


# ===================================================================
# TestVideoFeedCot — b-f-t-r type with URL, callsign, mime_type
# ===================================================================

@pytest.mark.unit
class TestVideoFeedCot:
    """Video feed CoT builder with b-f-t-r type code."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_uid_contains_feed_id(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-front", "http://localhost:8000/api/cam/front/mjpeg",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert "cam-front" in root.get("uid")

    def test_point_lat_lng(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194, alt=20.0,
        )
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)
        assert float(point.get("hae")) == pytest.approx(20.0, abs=0.1)

    def test_video_detail_url(self):
        from engine.comms.cot import video_feed_to_cot
        url = "http://localhost:8000/api/cam/01/mjpeg"
        xml_str = video_feed_to_cot("cam-01", url, lat=37.7749, lng=-122.4194)
        root = ET.fromstring(xml_str)
        video = root.find("detail/__video")
        assert video is not None
        assert video.get("url") == url

    def test_contact_callsign_default(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        # Default callsign should use feed_id
        assert "cam-01" in contact.get("callsign", "")

    def test_contact_callsign_custom(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
            callsign="Front Door Camera",
        )
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        assert contact.get("callsign") == "Front Door Camera"

    def test_mime_type_in_video_element(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
            mime_type="video/x-motion-jpeg",
        )
        root = ET.fromstring(xml_str)
        video = root.find("detail/__video")
        assert video is not None
        assert video.get("mimeType") == "video/x-motion-jpeg"

    def test_default_mime_type(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        video = root.find("detail/__video")
        assert video is not None
        # Default mime_type should be "video/mp4"
        assert video.get("mimeType") == "video/mp4"

    def test_stale_time_5_minutes(self):
        """Video feed advertisements should stay fresh for 5 minutes by default."""
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        start = datetime.fromisoformat(root.get("start").replace("Z", "+00:00"))
        stale = datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        delta = (stale - start).total_seconds()
        assert delta == pytest.approx(300.0, abs=5.0)

    def test_timestamps_utc_iso(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        time_str = root.get("time")
        assert time_str.endswith("Z")
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        assert dt.tzinfo is not None


# ===================================================================
# TestVideoFeedParseable
# ===================================================================

@pytest.mark.unit
class TestVideoFeedParseable:
    """Video feed CoT output must be parseable by xml.etree.ElementTree."""

    def test_round_trip_parseable(self):
        from engine.comms.cot import video_feed_to_cot
        xml_str = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert root.tag == "event"
        assert root.get("version") == "2.0"


# ===================================================================
# TestEmergencyCot — b-e-r / b-e-s types
# ===================================================================

@pytest.mark.unit
class TestEmergencyCot:
    """Emergency CoT builder with extended emergency types."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

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

    def test_contact_callsign(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("ALPHA-HQ", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        assert contact.get("callsign") == "ALPHA-HQ"

    def test_emergency_detail_element(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "medic", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        emergency = root.find("detail/emergency")
        assert emergency is not None
        assert emergency.get("type") == "medic"

    def test_remarks_custom(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot(
            "TRITIUM-SC", "911", 37.7749, -122.4194,
            remarks="Intruder in sector 7",
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert "Intruder in sector 7" in remarks.text

    def test_remarks_default(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "fire", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert remarks.text is not None
        assert len(remarks.text) > 0


# ===================================================================
# TestEmergency911 — 911 uses appropriate type code
# ===================================================================

@pytest.mark.unit
class TestEmergency911:
    """Emergency type '911' uses b-a-o-tbl type code."""

    def test_911_type_code(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        cot_type = root.get("type")
        # 911 maps to alert/trouble
        assert cot_type.startswith("b-a-o") or cot_type.startswith("b-e")


# ===================================================================
# TestEmergencySOS — SOS uses appropriate type code
# ===================================================================

@pytest.mark.unit
class TestEmergencySOS:
    """Emergency type 'sos' uses appropriate type code."""

    def test_sos_type_code(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "sos", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        cot_type = root.get("type")
        assert cot_type.startswith("b-a-o") or cot_type.startswith("b-e")


# ===================================================================
# TestEmergencyMedic — medic type supported
# ===================================================================

@pytest.mark.unit
class TestEmergencyMedic:
    """Emergency type 'medic' is supported."""

    def test_medic_type_valid_xml(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("FIELD-MEDIC", "medic", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_medic_type_has_emergency_detail(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("FIELD-MEDIC", "medic", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        emergency = root.find("detail/emergency")
        assert emergency is not None
        assert emergency.get("type") == "medic"


# ===================================================================
# TestEmergencyFire — fire type supported
# ===================================================================

@pytest.mark.unit
class TestEmergencyFire:
    """Emergency type 'fire' is supported."""

    def test_fire_type_valid_xml(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("FIRE-HQ", "fire", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_fire_type_has_emergency_detail(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("FIRE-HQ", "fire", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        emergency = root.find("detail/emergency")
        assert emergency is not None
        assert emergency.get("type") == "fire"


# ===================================================================
# TestEmergencyRemarks — remarks included in element
# ===================================================================

@pytest.mark.unit
class TestEmergencyRemarks:
    """Emergency CoT includes remarks element."""

    def test_remarks_with_text(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot(
            "TRITIUM-SC", "911", 37.7749, -122.4194,
            remarks="Armed intruder near gate",
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert "Armed intruder near gate" in remarks.text

    def test_remarks_empty_string_gets_default(self):
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "sos", 37.7749, -122.4194, remarks="")
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert remarks.text is not None and len(remarks.text) > 0


# ===================================================================
# TestEmergencyStaleTime — emergencies have 1-minute stale
# ===================================================================

@pytest.mark.unit
class TestEmergencyStaleTime:
    """Emergency CoT should have shorter stale time."""

    def test_stale_time_reasonable(self):
        """Emergency stale time should be reasonable (2 minutes or less)."""
        from engine.comms.cot import emergency_to_cot
        xml_str = emergency_to_cot("TRITIUM-SC", "911", 37.7749, -122.4194)
        root = ET.fromstring(xml_str)
        start = datetime.fromisoformat(root.get("start").replace("Z", "+00:00"))
        stale = datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        delta = (stale - start).total_seconds()
        # Should be 120s or less
        assert delta <= 125.0


# ===================================================================
# TestTaskingCot — t-x-t-a with assignee
# ===================================================================

@pytest.mark.unit
class TestTaskingCot:
    """Tasking CoT builder with t-x-t-a type code."""

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
        xml_str = tasking_to_cot(
            "task-001", "rover-1", "dispatch",
            lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)

    def test_tasking_detail_element(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-001", "rover-1", "dispatch")
        root = ET.fromstring(xml_str)
        tasking = root.find("detail/tasking")
        assert tasking is not None
        assert tasking.get("task_id") == "task-001"
        assert tasking.get("assignee_uid") == "rover-1"
        assert tasking.get("task_type") == "dispatch"


# ===================================================================
# TestTaskingAssignee — assignee preserved in detail
# ===================================================================

@pytest.mark.unit
class TestTaskingAssignee:
    """Tasking assignee is preserved in the detail element."""

    def test_assignee_in_tasking_element(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-002", "drone-alpha", "patrol")
        root = ET.fromstring(xml_str)
        tasking = root.find("detail/tasking")
        assert tasking is not None
        assert tasking.get("assignee_uid") == "drone-alpha"

    def test_patrol_task_type(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-003", "drone-2", "patrol")
        root = ET.fromstring(xml_str)
        tasking = root.find("detail/tasking")
        assert tasking.get("task_type") == "patrol"

    def test_recall_task_type(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-004", "rover-3", "recall")
        root = ET.fromstring(xml_str)
        tasking = root.find("detail/tasking")
        assert tasking.get("task_type") == "recall"


# ===================================================================
# TestTaskingRemarks — task description in remarks
# ===================================================================

@pytest.mark.unit
class TestTaskingRemarks:
    """Tasking remarks contain task description."""

    def test_custom_remarks(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot(
            "task-005", "rover-1", "dispatch",
            remarks="Patrol north perimeter",
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert "Patrol north perimeter" in remarks.text

    def test_default_remarks(self):
        from engine.comms.cot import tasking_to_cot
        xml_str = tasking_to_cot("task-006", "rover-1", "dispatch")
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert remarks.text is not None
        assert len(remarks.text) > 0


# ===================================================================
# TestSensorReadingCot — b-s-r type
# ===================================================================

@pytest.mark.unit
class TestSensorReadingCot:
    """Sensor reading CoT builder with b-s-r type code."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_type_is_sensor_reading(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        cot_type = root.get("type")
        assert cot_type.startswith("b-s-r")

    def test_default_type_is_motion(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-s-r"

    def test_uid_contains_sensor_id(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "pir-front-door", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert "pir-front-door" in root.get("uid")

    def test_point_element(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194, alt=3.0,
        )
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)
        assert float(point.get("hae")) == pytest.approx(3.0, abs=0.1)

    def test_sensor_detail_element(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
            sensor_type="motion", detection_type="human", confidence=0.85,
        )
        root = ET.fromstring(xml_str)
        sensor = root.find("detail/sensor")
        assert sensor is not None
        assert sensor.get("type") == "motion"
        assert sensor.get("detection") == "human"
        assert float(sensor.get("confidence")) == pytest.approx(0.85, abs=0.01)

    def test_contact_callsign_from_sensor_id(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "pir-front", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        assert "pir-front" in contact.get("callsign", "")

    def test_remarks_element(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
            sensor_type="motion", detection_type="vehicle",
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert remarks.text is not None

    def test_timestamps_utc_iso(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        time_str = root.get("time")
        assert time_str.endswith("Z")

    def test_stale_time_5_minutes(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        start = datetime.fromisoformat(root.get("start").replace("Z", "+00:00"))
        stale = datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        delta = (stale - start).total_seconds()
        assert delta == pytest.approx(300.0, abs=5.0)


# ===================================================================
# TestSensorReadingInfrared — b-s-r-i type
# ===================================================================

@pytest.mark.unit
class TestSensorReadingInfrared:
    """Infrared sensor type uses b-s-r-i."""

    def test_infrared_type_code(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "ir-01", lat=37.7749, lng=-122.4194,
            sensor_type="infrared",
        )
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-s-r-i"


# ===================================================================
# TestSensorReadingRadar — b-s-r-r type
# ===================================================================

@pytest.mark.unit
class TestSensorReadingRadar:
    """Radar sensor type uses b-s-r-r."""

    def test_radar_type_code(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "radar-01", lat=37.7749, lng=-122.4194,
            sensor_type="radar",
        )
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-s-r-r"


# ===================================================================
# TestSensorReadingConfidence — confidence in detail
# ===================================================================

@pytest.mark.unit
class TestSensorReadingConfidence:
    """Sensor reading confidence is stored in detail element."""

    def test_high_confidence(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
            confidence=0.95,
        )
        root = ET.fromstring(xml_str)
        sensor = root.find("detail/sensor")
        assert sensor is not None
        assert float(sensor.get("confidence")) == pytest.approx(0.95, abs=0.01)

    def test_low_confidence(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
            confidence=0.2,
        )
        root = ET.fromstring(xml_str)
        sensor = root.find("detail/sensor")
        assert float(sensor.get("confidence")) == pytest.approx(0.2, abs=0.01)

    def test_default_confidence(self):
        from engine.comms.cot import sensor_reading_to_cot
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        sensor = root.find("detail/sensor")
        assert float(sensor.get("confidence")) == pytest.approx(0.8, abs=0.01)


# ===================================================================
# TestSensorReadingParse — round-trip parsing
# ===================================================================

@pytest.mark.unit
class TestSensorReadingParse:
    """Sensor reading CoT can be parsed back."""

    def test_round_trip(self):
        from engine.comms.cot import sensor_reading_to_cot, cot_xml_to_sensor_reading
        xml_str = sensor_reading_to_cot(
            "sensor-01", lat=37.7749, lng=-122.4194, alt=3.0,
            sensor_type="motion", detection_type="human", confidence=0.9,
        )
        result = cot_xml_to_sensor_reading(xml_str)
        assert result is not None
        assert result["sensor_id"] == "sensor-01"
        assert result["sensor_type"] == "motion"
        assert result["detection_type"] == "human"
        assert result["confidence"] == pytest.approx(0.9, abs=0.01)
        assert result["lat"] == pytest.approx(37.7749, abs=0.001)
        assert result["lng"] == pytest.approx(-122.4194, abs=0.001)

    def test_returns_none_for_non_sensor(self):
        from engine.comms.cot import cot_xml_to_sensor_reading, make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.77, -122.42, 16.0, "Cyan", "HQ")
        result = cot_xml_to_sensor_reading(xml_str)
        assert result is None

    def test_returns_none_for_malformed_xml(self):
        from engine.comms.cot import cot_xml_to_sensor_reading
        result = cot_xml_to_sensor_reading("not xml")
        assert result is None

    def test_infrared_round_trip(self):
        from engine.comms.cot import sensor_reading_to_cot, cot_xml_to_sensor_reading
        xml_str = sensor_reading_to_cot(
            "ir-01", lat=37.77, lng=-122.42,
            sensor_type="infrared", detection_type="vehicle", confidence=0.7,
        )
        result = cot_xml_to_sensor_reading(xml_str)
        assert result is not None
        assert result["sensor_type"] == "infrared"


# ===================================================================
# TestSpotReportCot — b-m-p-s-m type
# ===================================================================

@pytest.mark.unit
class TestSpotReportCot:
    """Spot report CoT builder with b-m-p-s-m type code."""

    def test_returns_valid_xml(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert root.tag == "event"

    def test_type_is_spot_report(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        assert root.get("type") == "b-m-p-s-m"

    def test_uid_format(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        uid = root.get("uid")
        assert uid.startswith("spotrep-")

    def test_point_element(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194, alt=16.0,
        )
        root = ET.fromstring(xml_str)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749, abs=0.001)
        assert float(point.get("lon")) == pytest.approx(-122.4194, abs=0.001)

    def test_contact_callsign(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        contact = root.find("detail/contact")
        assert contact is not None
        assert contact.get("callsign") == "Amy"

    def test_category_hostile(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
            category="hostile",
        )
        root = ET.fromstring(xml_str)
        # Category should be in the detail somewhere
        spotrep = root.find("detail/spotrep")
        assert spotrep is not None
        assert spotrep.get("category") == "hostile"

    def test_category_friendly(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
            category="friendly",
        )
        root = ET.fromstring(xml_str)
        spotrep = root.find("detail/spotrep")
        assert spotrep is not None
        assert spotrep.get("category") == "friendly"

    def test_timestamps_utc_iso(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        time_str = root.get("time")
        assert time_str.endswith("Z")

    def test_stale_time_5_minutes(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        start = datetime.fromisoformat(root.get("start").replace("Z", "+00:00"))
        stale = datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        delta = (stale - start).total_seconds()
        assert delta == pytest.approx(300.0, abs=5.0)


# ===================================================================
# TestSpotReportDescription — description in remarks
# ===================================================================

@pytest.mark.unit
class TestSpotReportDescription:
    """Spot report description is included in remarks element."""

    def test_description_in_remarks(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
            description="Two unknown individuals approaching from the east",
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert "Two unknown individuals approaching from the east" in remarks.text

    def test_default_description(self):
        from engine.comms.cot import spot_report_to_cot
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194,
        )
        root = ET.fromstring(xml_str)
        remarks = root.find("detail/remarks")
        assert remarks is not None
        assert remarks.text is not None
        assert len(remarks.text) > 0


# ===================================================================
# TestSpotReportParse — round-trip parsing
# ===================================================================

@pytest.mark.unit
class TestSpotReportParse:
    """Spot report CoT can be parsed back."""

    def test_round_trip(self):
        from engine.comms.cot import spot_report_to_cot, cot_xml_to_spot_report
        xml_str = spot_report_to_cot(
            "Amy", lat=37.7749, lng=-122.4194, alt=16.0,
            category="hostile", description="Hostile vehicle spotted",
        )
        result = cot_xml_to_spot_report(xml_str)
        assert result is not None
        assert result["callsign"] == "Amy"
        assert result["category"] == "hostile"
        assert "Hostile vehicle spotted" in result["description"]
        assert result["lat"] == pytest.approx(37.7749, abs=0.001)
        assert result["lng"] == pytest.approx(-122.4194, abs=0.001)

    def test_returns_none_for_non_spot_report(self):
        from engine.comms.cot import cot_xml_to_spot_report, make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.77, -122.42, 16.0, "Cyan", "HQ")
        result = cot_xml_to_spot_report(xml_str)
        assert result is None

    def test_returns_none_for_malformed_xml(self):
        from engine.comms.cot import cot_xml_to_spot_report
        result = cot_xml_to_spot_report("not xml")
        assert result is None


# ===================================================================
# TestVideoFeedParse — round-trip parsing
# ===================================================================

@pytest.mark.unit
class TestVideoFeedParse:
    """Video feed CoT can be parsed back."""

    def test_round_trip(self):
        from engine.comms.cot import video_feed_to_cot, cot_xml_to_video_feed
        url = "http://localhost:8000/api/cam/01/mjpeg"
        xml_str = video_feed_to_cot(
            "cam-01", url, lat=37.7749, lng=-122.4194, alt=16.0,
            callsign="Front Door",
        )
        result = cot_xml_to_video_feed(xml_str)
        assert result is not None
        assert result["feed_id"] == "cam-01"
        assert result["url"] == url
        assert result["callsign"] == "Front Door"
        assert result["lat"] == pytest.approx(37.7749, abs=0.001)
        assert result["lng"] == pytest.approx(-122.4194, abs=0.001)

    def test_returns_none_for_non_video(self):
        from engine.comms.cot import cot_xml_to_video_feed, make_sa_cot
        xml_str = make_sa_cot("TRITIUM-SC", 37.77, -122.42, 16.0, "Cyan", "HQ")
        result = cot_xml_to_video_feed(xml_str)
        assert result is None

    def test_returns_none_for_malformed_xml(self):
        from engine.comms.cot import cot_xml_to_video_feed
        result = cot_xml_to_video_feed("not xml")
        assert result is None


# ===================================================================
# TestBridgeTaskingInbound — t-x-t-a routed to tak_tasking event
# ===================================================================

@pytest.mark.unit
class TestBridgeTaskingInbound:
    """Tasking CoT routed to tak_tasking EventBus event."""

    def test_tasking_routes_to_event_bus(self, bridge, event_bus):
        from engine.comms.cot import tasking_to_cot
        q = event_bus.subscribe()
        xml = tasking_to_cot("task-001", "rover-1", "dispatch", lat=37.77, lng=-122.42)
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_tasking":
                found = True
                assert msg["data"]["task_id"] == "task-001"
                break
        assert found


# ===================================================================
# TestBridgeEmergencyInbound — b-a-o routed to tak_emergency event
# ===================================================================

@pytest.mark.unit
class TestBridgeEmergencyInbound:
    """Emergency CoT routed to tak_emergency EventBus event."""

    def test_emergency_routes_to_event_bus(self, bridge, event_bus):
        from engine.comms.cot import emergency_to_cot
        q = event_bus.subscribe()
        xml = emergency_to_cot("FIELD-01", "911", 37.77, -122.42, remarks="Help!")
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_emergency":
                found = True
                assert msg["data"]["callsign"] == "FIELD-01"
                break
        assert found


# ===================================================================
# TestBridgeSensorInbound — b-s-r routed to tak_sensor event
# ===================================================================

@pytest.mark.unit
class TestBridgeSensorInbound:
    """Sensor reading CoT routed to tak_sensor EventBus event."""

    def test_sensor_routes_to_event_bus(self, bridge, event_bus):
        from engine.comms.cot import sensor_reading_to_cot
        q = event_bus.subscribe()
        xml = sensor_reading_to_cot(
            "sensor-01", lat=37.77, lng=-122.42,
            sensor_type="motion", detection_type="human", confidence=0.9,
        )
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_sensor":
                found = True
                assert msg["data"]["sensor_id"] == "sensor-01"
                assert msg["data"]["sensor_type"] == "motion"
                break
        assert found

    def test_infrared_sensor_routes(self, bridge, event_bus):
        from engine.comms.cot import sensor_reading_to_cot
        q = event_bus.subscribe()
        xml = sensor_reading_to_cot(
            "ir-01", lat=37.77, lng=-122.42,
            sensor_type="infrared",
        )
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_sensor":
                found = True
                break
        assert found

    def test_sensor_does_not_inject_to_tracker(self, bridge, target_tracker):
        from engine.comms.cot import sensor_reading_to_cot
        xml = sensor_reading_to_cot(
            "sensor-01", lat=37.77, lng=-122.42,
        )
        bridge._handle_inbound(xml)
        target_tracker.update_from_simulation.assert_not_called()


# ===================================================================
# TestBridgeVideoInbound — b-i-v routed to tak_video_feed event
# ===================================================================

@pytest.mark.unit
class TestBridgeVideoInbound:
    """Video feed CoT routed to tak_video_feed EventBus event."""

    def test_video_feed_routes_to_event_bus(self, bridge, event_bus):
        from engine.comms.cot import video_feed_to_cot
        q = event_bus.subscribe()
        xml = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.77, lng=-122.42,
        )
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_video_feed":
                found = True
                assert msg["data"]["feed_id"] == "cam-01"
                assert "mjpeg" in msg["data"]["url"]
                break
        assert found

    def test_video_feed_does_not_inject_to_tracker(self, bridge, target_tracker):
        from engine.comms.cot import video_feed_to_cot
        xml = video_feed_to_cot(
            "cam-01", "http://localhost:8000/api/cam/01/mjpeg",
            lat=37.77, lng=-122.42,
        )
        bridge._handle_inbound(xml)
        target_tracker.update_from_simulation.assert_not_called()


# ===================================================================
# TestBridgeSpotReportInbound — b-m-p-s-m routed to tak_spot_report
# ===================================================================

@pytest.mark.unit
class TestBridgeSpotReportInbound:
    """Spot report CoT routed to tak_spot_report EventBus event."""

    def test_spot_report_routes_to_event_bus(self, bridge, event_bus):
        from engine.comms.cot import spot_report_to_cot
        q = event_bus.subscribe()
        xml = spot_report_to_cot(
            "Amy", lat=37.77, lng=-122.42,
            category="hostile", description="Unknown vehicle",
        )
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_spot_report":
                found = True
                assert msg["data"]["callsign"] == "Amy"
                break
        assert found

    def test_spot_report_does_not_inject_to_tracker(self, bridge, target_tracker):
        from engine.comms.cot import spot_report_to_cot
        xml = spot_report_to_cot(
            "Amy", lat=37.77, lng=-122.42,
        )
        bridge._handle_inbound(xml)
        target_tracker.update_from_simulation.assert_not_called()


# ===================================================================
# TestBridgeSendTasking — outbound tasking generates correct XML
# ===================================================================

@pytest.mark.unit
class TestBridgeSendTasking:
    """TAKBridge.send_tasking() queues correct CoT XML."""

    def test_send_tasking_queues_message(self, bridge):
        bridge.send_tasking("task-001", "rover-1", "dispatch")
        assert bridge._tx_queue.qsize() == 1

    def test_send_tasking_xml_type(self, bridge):
        bridge.send_tasking("task-001", "rover-1", "dispatch")
        xml = bridge._tx_queue.get_nowait()
        assert "t-x-t-a" in xml


# ===================================================================
# TestBridgeSendEmergency — outbound emergency generates correct XML
# ===================================================================

@pytest.mark.unit
class TestBridgeSendEmergency:
    """TAKBridge.send_emergency() queues correct CoT XML."""

    def test_send_emergency_queues_message(self, bridge):
        bridge.send_emergency("911", remarks="Alert")
        assert bridge._tx_queue.qsize() == 1

    def test_send_emergency_xml_contains_emergency_type(self, bridge):
        bridge.send_emergency("911", remarks="Fire in sector 3")
        xml = bridge._tx_queue.get_nowait()
        root = ET.fromstring(xml)
        # Should be an emergency-prefixed type
        assert root.get("type").startswith("b-a-o") or root.get("type").startswith("b-e")


# ===================================================================
# TestBridgeSendVideoFeed — outbound video feed generates correct XML
# ===================================================================

@pytest.mark.unit
class TestBridgeSendVideoFeed:
    """TAKBridge.send_video_feed() queues correct CoT XML."""

    def test_send_video_feed_queues_message(self, bridge):
        bridge.send_video_feed("cam-01", "rtsp://192.168.1.100/stream")
        assert bridge._tx_queue.qsize() == 1

    def test_send_video_feed_xml_has_url(self, bridge):
        bridge.send_video_feed("cam-01", "rtsp://192.168.1.100/stream")
        xml = bridge._tx_queue.get_nowait()
        assert "rtsp://192.168.1.100/stream" in xml


# ===================================================================
# TestBridgeSendSensorReading — outbound sensor reading
# ===================================================================

@pytest.mark.unit
class TestBridgeSendSensorReading:
    """TAKBridge.send_sensor_reading() queues correct CoT XML."""

    def test_send_sensor_reading_queues_message(self, bridge):
        bridge.send_sensor_reading(
            "sensor-01", lat=37.77, lng=-122.42,
            sensor_type="motion", detection_type="human", confidence=0.9,
        )
        assert bridge._tx_queue.qsize() == 1

    def test_send_sensor_reading_xml_type(self, bridge):
        bridge.send_sensor_reading(
            "sensor-01", lat=37.77, lng=-122.42,
        )
        xml = bridge._tx_queue.get_nowait()
        assert "b-s-r" in xml


# ===================================================================
# TestBridgeSendSpotReport — outbound spot report
# ===================================================================

@pytest.mark.unit
class TestBridgeSendSpotReport:
    """TAKBridge.send_spot_report() queues correct CoT XML."""

    def test_send_spot_report_queues_message(self, bridge):
        bridge.send_spot_report(
            "Amy", lat=37.77, lng=-122.42,
            category="hostile", description="Unknown vehicle",
        )
        assert bridge._tx_queue.qsize() == 1

    def test_send_spot_report_xml_type(self, bridge):
        bridge.send_spot_report(
            "Amy", lat=37.77, lng=-122.42,
        )
        xml = bridge._tx_queue.get_nowait()
        assert "b-m-p-s-m" in xml


# ===================================================================
# TestExistingRoutingPreserved — backward compatibility
# ===================================================================

@pytest.mark.unit
class TestExistingRoutingPreserved:
    """All existing routing paths must continue to work."""

    def test_sa_events_still_work(self, bridge, event_bus, target_tracker):
        from engine.comms.cot import make_sa_cot
        xml = make_sa_cot("ATAK-User", 37.7749, -122.4194, 16.0, "Green", "Team Member")
        bridge._handle_inbound(xml)
        target_tracker.update_from_simulation.assert_called_once()

    def test_geochat_still_works(self, bridge, event_bus):
        from engine.comms.cot import geochat_to_cot_xml
        q = event_bus.subscribe()
        xml = geochat_to_cot_xml("USER-1", "Alpha", "Test message")
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_geochat":
                found = True
                break
        assert found

    def test_tasking_still_works(self, bridge, event_bus):
        from engine.comms.cot import tasking_to_cot
        q = event_bus.subscribe()
        xml = tasking_to_cot("task-001", "rover-1", "dispatch")
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_tasking":
                found = True
                break
        assert found

    def test_emergency_still_works(self, bridge, event_bus):
        from engine.comms.cot import emergency_to_cot
        q = event_bus.subscribe()
        xml = emergency_to_cot("HQ", "911", 37.77, -122.42)
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_emergency":
                found = True
                break
        assert found

    def test_malformed_xml_does_not_crash(self, bridge, target_tracker):
        bridge._handle_inbound("not xml at all")
        target_tracker.update_from_simulation.assert_not_called()

    def test_geochat_does_not_inject_to_tracker(self, bridge, target_tracker):
        from engine.comms.cot import geochat_to_cot_xml
        xml = geochat_to_cot_xml("USER-1", "Alpha", "Hello")
        bridge._handle_inbound(xml)
        target_tracker.update_from_simulation.assert_not_called()
