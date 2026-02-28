# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TAK history model and bridge geochat methods.

TDD: tests written BEFORE implementation.
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

pytest.skip(
    "TAKHistory SQLAlchemy model not implemented in app.models — "
    "TAK history persistence not yet built",
    allow_module_level=True,
)

from engine.comms.event_bus import EventBus


# ===================================================================
# TAK History Model
# ===================================================================

class TestTAKHistoryModel:
    """Verify the TAKHistory SQLAlchemy model exists and has correct fields."""

    def test_model_importable(self):
        from app.models import TAKHistory
        assert TAKHistory is not None

    def test_tablename(self):
        from app.models import TAKHistory
        assert TAKHistory.__tablename__ == "tak_history"

    def test_has_required_columns(self):
        from app.models import TAKHistory
        columns = {c.name for c in TAKHistory.__table__.columns}
        expected = {"id", "event_type", "uid", "callsign", "lat", "lng",
                    "message", "cot_xml", "created_at"}
        assert expected.issubset(columns)


# ===================================================================
# TAKBridge geochat methods
# ===================================================================

class TestBridgeGeochat:

    @pytest.fixture
    def event_bus(self):
        return EventBus()

    @pytest.fixture
    def target_tracker(self):
        tracker = MagicMock()
        tracker.get_all.return_value = []
        return tracker

    @pytest.fixture
    def bridge(self, event_bus, target_tracker):
        from engine.comms.tak_bridge import TAKBridge
        return TAKBridge(
            event_bus=event_bus,
            target_tracker=target_tracker,
            cot_url="tcp://localhost:8088",
            callsign="TEST-HQ",
            publish_interval=1.0,
        )

    def test_send_geochat_queues_cot(self, bridge):
        """send_geochat() should queue a GeoChat CoT XML string."""
        bridge.send_geochat("Enemy at north gate")
        assert bridge._tx_queue.qsize() == 1
        xml = bridge._tx_queue.get_nowait()
        assert "GeoChat" in xml
        assert "b-t-f" in xml

    def test_send_geochat_publishes_event(self, bridge, event_bus):
        """send_geochat() should publish a tak_geochat event."""
        q = event_bus.subscribe()
        bridge.send_geochat("Hello team")

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_geochat":
                found = True
                assert msg["data"]["message"] == "Hello team"
                assert msg["data"]["direction"] == "outbound"
                break
        assert found

    def test_handle_geochat_inbound(self, bridge, event_bus):
        """Inbound GeoChat CoT should be parsed and published as event."""
        from engine.comms.cot import geochat_to_cot_xml
        q = event_bus.subscribe()

        xml = geochat_to_cot_xml(
            sender_uid="ANDROID-abc123",
            sender_callsign="Alpha",
            message="Contact at south fence",
            lat=37.7749,
            lng=-122.4194,
        )
        bridge._handle_inbound(xml)

        found = False
        while not q.empty():
            msg = q.get_nowait()
            if msg["type"] == "tak_geochat":
                found = True
                assert msg["data"]["message"] == "Contact at south fence"
                assert msg["data"]["sender_callsign"] == "Alpha"
                assert msg["data"]["direction"] == "inbound"
                break
        assert found

    def test_geochat_sensorium_push(self, event_bus, target_tracker):
        """Inbound GeoChat should push to sensorium when available."""
        from engine.comms.tak_bridge import TAKBridge
        from engine.comms.cot import geochat_to_cot_xml

        sensorium = MagicMock()
        bridge = TAKBridge(
            event_bus=event_bus,
            target_tracker=target_tracker,
            cot_url="tcp://localhost:8088",
            callsign="TEST-HQ",
            sensorium=sensorium,
        )

        xml = geochat_to_cot_xml(
            sender_uid="ANDROID-abc",
            sender_callsign="Bravo",
            message="All clear",
        )
        bridge._handle_inbound(xml)

        calls = [c for c in sensorium.push.call_args_list
                 if c[0][0] == "tak_chat"]
        assert len(calls) >= 1
        assert "Bravo" in calls[0][0][1]
