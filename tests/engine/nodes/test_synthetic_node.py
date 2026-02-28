# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for SyntheticSensorNode."""

import time

import numpy as np
import pytest

from engine.nodes.base import SensorNode, Position
from engine.scenarios.schema import (
    Scenario,
    ScenarioEvent,
    EventKind,
    Position2D,
    PersonConfig,
)
from engine.scenarios.synthetic_node import SyntheticSensorNode, WorldClock, WorldState


def _simple_scenario(duration: float = 5.0, time_scale: float = 0.1) -> Scenario:
    """Create a minimal scenario for testing."""
    return Scenario(
        name="test",
        description="Test scenario",
        duration=duration,
        time_scale=time_scale,
        people=[PersonConfig(person_id="p1", name="Test Person")],
        events=[
            ScenarioEvent(
                time=1.0,
                kind=EventKind.PERSON_ENTER,
                person_id="p1",
                position=Position2D(x=0.5, y=0.5),
            ),
            ScenarioEvent(
                time=3.0,
                kind=EventKind.PERSON_MOVE,
                person_id="p1",
                position=Position2D(x=0.8, y=0.5),
            ),
            ScenarioEvent(
                time=4.0,
                kind=EventKind.PERSON_EXIT,
                person_id="p1",
            ),
        ],
        expected=[],
    )


@pytest.mark.unit
class TestWorldClock:
    def test_elapsed_starts_at_zero(self):
        clock = WorldClock(1.0)
        assert clock.elapsed == 0.0

    def test_elapsed_increases(self):
        clock = WorldClock(1.0)
        clock.start()
        time.sleep(0.1)
        assert clock.elapsed > 0.05

    def test_time_scale_faster(self):
        """time_scale=0.5 means scenario runs 2x faster."""
        clock = WorldClock(0.5)
        clock.start()
        time.sleep(0.1)
        # Should report ~0.2s of scenario time
        assert clock.elapsed > 0.15

    def test_real_delay(self):
        clock = WorldClock(0.5)
        # 1 scenario second = 0.5 real seconds
        assert clock.real_delay(1.0) == 0.5


@pytest.mark.unit
class TestWorldState:
    def test_add_person(self):
        ws = WorldState()
        ws.add_person("p1", Position2D(x=0.5, y=0.5))
        people = ws.get_visible_people()
        assert len(people) == 1

    def test_remove_person(self):
        ws = WorldState()
        ws.add_person("p1", Position2D(x=0.5, y=0.5))
        ws.remove_person("p1")
        assert len(ws.get_visible_people()) == 0

    def test_move_person(self):
        ws = WorldState()
        ws.add_person("p1", Position2D(x=0.3, y=0.5))
        ws.move_person("p1", Position2D(x=0.8, y=0.5))
        people = ws.get_visible_people()
        assert people[0]["position"].x == 0.8

    def test_speech_consumed(self):
        ws = WorldState()
        ws.set_speech("Hello")
        assert ws.get_speech() == "Hello"
        assert ws.get_speech() is None  # Consumed

    def test_snapshot(self):
        ws = WorldState()
        ws.add_person("p1", Position2D(x=0.5, y=0.5))
        snap = ws.snapshot()
        assert "people" in snap
        assert len(snap["people"]) == 1


@pytest.mark.unit
class TestSyntheticSensorNode:
    def test_implements_sensor_node(self):
        """SyntheticSensorNode must be a SensorNode subclass."""
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        assert isinstance(node, SensorNode)

    def test_capabilities(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        assert node.has_camera is True
        assert node.has_ptz is True
        assert node.has_mic is True
        assert node.has_speaker is True

    def test_get_frame_before_start(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        assert node.get_frame() is None

    def test_get_frame_after_start(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        node.start()
        time.sleep(0.3)
        frame = node.get_frame()
        node.stop()
        assert frame is not None
        assert frame.shape == (240, 320, 3)
        assert frame.dtype == np.uint8

    def test_get_jpeg(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        node.start()
        time.sleep(0.3)
        jpeg = node.get_jpeg()
        node.stop()
        assert jpeg is not None
        assert isinstance(jpeg, bytes)

    def test_frame_id_increments(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        node.start()
        time.sleep(0.2)
        id1 = node.frame_id
        node.get_frame()
        id2 = node.frame_id
        node.stop()
        assert id2 > id1

    def test_ptz_move(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        pos_before = node.get_position()
        node.move(1, 0, 0.5)  # Pan right
        pos_after = node.get_position()
        assert pos_after.pan > pos_before.pan

    def test_ptz_limits(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        # Pan way past limit
        node.move(1, 0, 100.0)
        pos = node.get_position()
        assert pos.pan <= 170.0

    def test_reset_position(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        node.move(1, 1, 0.5)
        node.reset_position()
        pos = node.get_position()
        assert pos.pan == 0.0
        assert pos.tilt == 0.0

    def test_play_audio_captured(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        node.play_audio(b"test_audio", 22050)
        assert len(node.played_audio) == 1
        assert node.played_audio[0] == (b"test_audio", 22050)

    def test_record_audio(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario)
        audio = node.record_audio(1.0)
        assert audio is not None
        assert audio.dtype == np.float32
        assert len(audio) == 16000  # 1 second at 16kHz

    def test_timeline_processes_events(self):
        """Events should update world state over time."""
        # Use time_scale=0.2 so scenario runs at 5x speed with comfortable margins.
        # Person enters at t=1.0 (real 0.2s), exits at t=8.0 (real 1.6s).
        scenario = Scenario(
            name="timeline_test",
            description="Test timeline event processing",
            duration=10.0,
            time_scale=0.2,
            people=[PersonConfig(person_id="p1", name="Test Person")],
            events=[
                ScenarioEvent(
                    time=1.0,
                    kind=EventKind.PERSON_ENTER,
                    person_id="p1",
                    position=Position2D(x=0.5, y=0.5),
                ),
                ScenarioEvent(
                    time=8.0,
                    kind=EventKind.PERSON_EXIT,
                    person_id="p1",
                ),
            ],
            expected=[],
        )
        node = SyntheticSensorNode(scenario)
        node.start()

        # Wait for person to enter (event at t=1.0, real time = 0.2s)
        time.sleep(0.5)
        people = node.world.get_visible_people()
        assert len(people) >= 1  # Person should have entered

        # Wait for person to exit (event at t=8.0, real time = 1.6s)
        time.sleep(1.5)
        people = node.world.get_visible_people()
        # Person should have exited by now
        assert len(people) == 0

        node.stop()

    def test_speech_event_queues_transcript(self):
        scenario = Scenario(
            name="speech_test",
            duration=3.0,
            time_scale=0.05,
            people=[PersonConfig(person_id="p1")],
            events=[
                ScenarioEvent(
                    time=0.5,
                    kind=EventKind.PERSON_ENTER,
                    person_id="p1",
                    position=Position2D(x=0.5, y=0.5),
                ),
                ScenarioEvent(
                    time=1.0,
                    kind=EventKind.PERSON_SPEAK,
                    person_id="p1",
                    text="Hello Amy",
                ),
            ],
            expected=[],
        )
        node = SyntheticSensorNode(scenario)
        node.start()
        time.sleep(0.3)

        transcripts = node.get_pending_transcripts()
        node.stop()
        assert "Hello Amy" in transcripts

    def test_scenario_finishes(self):
        scenario = _simple_scenario(duration=2.0, time_scale=0.05)
        node = SyntheticSensorNode(scenario)
        node.start()
        time.sleep(0.5)  # 2.0 * 0.05 = 0.1s real time + buffer
        assert node.finished
        node.stop()

    def test_custom_dimensions(self):
        scenario = _simple_scenario()
        node = SyntheticSensorNode(scenario, width=640, height=480)
        node.start()
        time.sleep(0.3)
        frame = node.get_frame()
        node.stop()
        assert frame is not None
        assert frame.shape == (480, 640, 3)
