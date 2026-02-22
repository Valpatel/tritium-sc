"""Tests for ActionRecorder and Scorer."""

import time

import pytest

from amy.commander import EventBus
from amy.scenarios.recorder import ActionRecorder
from amy.scenarios.scorer import Scorer
from amy.scenarios.schema import RecordedAction, ExpectedAction


@pytest.mark.unit
class TestActionRecorder:
    def test_records_amy_speech(self):
        bus = EventBus()
        recorder = ActionRecorder(bus)
        recorder.start()

        bus.publish("transcript", {"speaker": "amy", "text": "Hello there"})
        time.sleep(0.2)
        recorder.stop()

        assert len(recorder.speech) == 1
        assert recorder.speech[0].text == "Hello there"
        assert recorder.speech[0].action_type == "say"

    def test_records_user_speech(self):
        bus = EventBus()
        recorder = ActionRecorder(bus)
        recorder.start()

        bus.publish("transcript", {"speaker": "user", "text": "Hey Amy"})
        time.sleep(0.2)
        recorder.stop()

        actions = recorder.all_actions
        assert any(a.action_type == "user_speech" for a in actions)

    def test_records_thoughts(self):
        bus = EventBus()
        recorder = ActionRecorder(bus)
        recorder.start()

        bus.publish("thought", {"text": "I see someone"})
        time.sleep(0.2)
        recorder.stop()

        assert len(recorder.thoughts) == 1
        assert recorder.thoughts[0].text == "I see someone"

    def test_records_detections(self):
        bus = EventBus()
        recorder = ActionRecorder(bus)
        recorder.start()

        bus.publish("detections", {"summary": "1 person", "people": 1, "boxes": []})
        time.sleep(0.2)
        recorder.stop()

        assert len(recorder.detections) == 1
        assert recorder.detections[0].action_type == "detect_person"

    def test_ignores_zero_people_detections(self):
        bus = EventBus()
        recorder = ActionRecorder(bus)
        recorder.start()

        bus.publish("detections", {"summary": "empty", "people": 0, "boxes": []})
        time.sleep(0.2)
        recorder.stop()

        assert len(recorder.detections) == 0

    def test_timestamps_relative_to_start(self):
        bus = EventBus()
        start = time.monotonic()
        recorder = ActionRecorder(bus, start_time=start)
        recorder.start()

        time.sleep(0.1)
        bus.publish("thought", {"text": "test"})
        time.sleep(0.2)
        recorder.stop()

        # Timestamp should be relative to start_time (~0.1-0.3s range)
        assert 0.05 < recorder.thoughts[0].timestamp < 0.5


@pytest.mark.unit
class TestScorer:
    def test_empty_expected(self):
        scorer = Scorer()
        result = scorer.score([], [])
        assert result.total_score == 1.0
        assert result.matched == 0

    def test_simple_match(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="Hello, welcome!",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(0, 10), action_type="say"),
        ]
        result = scorer.score(actions, expected)
        assert result.total_score == 1.0
        assert result.matched == 1

    def test_no_match_outside_window(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=15.0, category="speech", action_type="say",
                text="Hello",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(0, 10), action_type="say"),
        ]
        result = scorer.score(actions, expected)
        assert result.total_score == 0.0
        assert result.matched == 0

    def test_contains_match(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="Hello there, welcome to the command center",
            ),
        ]
        expected = [
            ExpectedAction(
                time_window=(0, 10), action_type="say",
                contains="welcome",
            ),
        ]
        result = scorer.score(actions, expected)
        assert result.total_score == 1.0

    def test_contains_no_match(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="I'm watching the room",
            ),
        ]
        expected = [
            ExpectedAction(
                time_window=(0, 10), action_type="say",
                contains="hello",
            ),
        ]
        result = scorer.score(actions, expected)
        assert result.total_score == 0.0

    def test_not_contains(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="How can I help you?",
            ),
        ]
        expected = [
            ExpectedAction(
                time_window=(0, 10), action_type="say",
                not_contains="help",
            ),
        ]
        result = scorer.score(actions, expected)
        assert result.total_score == 0.0

    def test_greet_matches_say(self):
        """'greet' expected should match any 'say' action."""
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="Hi there!",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(0, 10), action_type="greet"),
        ]
        result = scorer.score(actions, expected)
        assert result.total_score == 1.0

    def test_weighted_scoring(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="Hello",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(0, 10), action_type="say", weight=2.0),
            ExpectedAction(time_window=(0, 10), action_type="think", weight=1.0),
        ]
        result = scorer.score(actions, expected)
        # 2.0 matched / 3.0 total = 0.667
        assert abs(result.total_score - 0.667) < 0.01

    def test_multiple_expected(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=2.0, category="detection", action_type="detect_person",
                text="1 person detected",
            ),
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="Hello",
            ),
            RecordedAction(
                timestamp=8.0, category="thought", action_type="think",
                text="They seem friendly",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(0, 5), action_type="detect_person"),
            ExpectedAction(time_window=(3, 10), action_type="say"),
            ExpectedAction(time_window=(6, 12), action_type="think"),
        ]
        result = scorer.score(actions, expected)
        assert result.total_score == 1.0
        assert result.matched == 3

    def test_details_included(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=5.0, category="speech", action_type="say",
                text="Hi",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(0, 10), action_type="say"),
        ]
        result = scorer.score(actions, expected)
        assert len(result.details) == 1
        assert result.details[0]["matched"] is True

    def test_latency_computed(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=7.0, category="speech", action_type="say",
                text="Hello",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(5, 15), action_type="say"),
        ]
        result = scorer.score(actions, expected)
        assert result.avg_response_latency == 2.0  # 7.0 - 5.0

    def test_detection_accuracy(self):
        scorer = Scorer()
        actions = [
            RecordedAction(
                timestamp=2.0, category="detection", action_type="detect_person",
                text="1 person",
            ),
        ]
        expected = [
            ExpectedAction(time_window=(0, 10), action_type="detect_person"),
        ]
        result = scorer.score(actions, expected)
        assert result.detection_accuracy == 1.0
