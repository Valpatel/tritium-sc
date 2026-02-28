# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GeoChat CoT XML generation and parsing.

TDD: tests written BEFORE implementation.
"""

import xml.etree.ElementTree as ET

import pytest

from engine.comms.cot import geochat_to_cot_xml, cot_xml_to_geochat


class TestGeochatToCotXml:
    """Generate GeoChat CoT XML from message data."""

    def test_returns_valid_xml(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Enemy spotted near north fence",
        )
        root = ET.fromstring(xml)
        assert root.tag == "event"

    def test_event_type_is_geochat(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Hello team",
        )
        root = ET.fromstring(xml)
        assert root.get("type") == "b-t-f"

    def test_uid_format(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Hello",
        )
        root = ET.fromstring(xml)
        uid = root.get("uid", "")
        assert uid.startswith("GeoChat.")

    def test_remarks_contains_message(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Contact at grid ref 123",
        )
        root = ET.fromstring(xml)
        remarks = root.find(".//remarks")
        assert remarks is not None
        assert remarks.text == "Contact at grid ref 123"

    def test_remarks_source_attribute(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Test",
        )
        root = ET.fromstring(xml)
        remarks = root.find(".//remarks")
        assert remarks is not None
        assert remarks.get("source") == "TRITIUM-SC"

    def test_chat_element_present(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Test",
        )
        root = ET.fromstring(xml)
        chat = root.find("./detail/__chat")
        assert chat is not None
        assert chat.get("senderCallsign") == "TRITIUM-SC"

    def test_to_all_recipients(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Broadcast",
            to_callsign="All Chat Rooms",
        )
        root = ET.fromstring(xml)
        chat = root.find("./detail/__chat")
        assert chat is not None
        assert "All Chat Rooms" in (chat.get("chatroom") or "")

    def test_point_element(self):
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Here",
            lat=37.7749,
            lng=-122.4194,
        )
        root = ET.fromstring(xml)
        point = root.find("point")
        assert point is not None
        assert float(point.get("lat")) == pytest.approx(37.7749)
        assert float(point.get("lon")) == pytest.approx(-122.4194)


class TestCotXmlToGeochat:
    """Parse inbound GeoChat CoT XML."""

    def test_parse_geochat_message(self):
        xml = geochat_to_cot_xml(
            sender_uid="ANDROID-abc123",
            sender_callsign="Alpha",
            message="Hostile spotted at north gate",
            lat=37.7749,
            lng=-122.4194,
        )
        result = cot_xml_to_geochat(xml)
        assert result is not None
        assert result["sender_uid"] == "ANDROID-abc123"
        assert result["sender_callsign"] == "Alpha"
        assert result["message"] == "Hostile spotted at north gate"

    def test_parse_returns_none_for_non_geochat(self):
        # SA position report, not a geochat
        xml = '<event version="2.0" uid="test" type="a-f-G" how="m-s" time="2026-01-01T00:00:00Z" start="2026-01-01T00:00:00Z" stale="2026-01-01T00:01:00Z"><point lat="0" lon="0" hae="0" ce="10" le="10"/></event>'
        result = cot_xml_to_geochat(xml)
        assert result is None

    def test_parse_returns_none_for_malformed_xml(self):
        result = cot_xml_to_geochat("not xml at all")
        assert result is None

    def test_parse_returns_lat_lng(self):
        xml = geochat_to_cot_xml(
            sender_uid="TEST",
            sender_callsign="Test User",
            message="Position report",
            lat=37.77,
            lng=-122.42,
        )
        result = cot_xml_to_geochat(xml)
        assert result is not None
        assert result["lat"] == pytest.approx(37.77)
        assert result["lng"] == pytest.approx(-122.42)

    def test_parse_round_trip(self):
        """Generate and parse should be lossless for key fields."""
        xml = geochat_to_cot_xml(
            sender_uid="TRITIUM-SC",
            sender_callsign="TRITIUM-SC",
            message="Round trip test message",
            lat=37.7749,
            lng=-122.4194,
        )
        parsed = cot_xml_to_geochat(xml)
        assert parsed is not None
        assert parsed["message"] == "Round trip test message"
        assert parsed["sender_callsign"] == "TRITIUM-SC"
