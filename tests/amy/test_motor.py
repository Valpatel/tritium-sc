"""Unit tests for Amy's motor programs module."""

from __future__ import annotations

import random
from itertools import islice
from unittest.mock import MagicMock

import pytest

from amy.motor import (
    MotorCommand,
    auto_track,
    breathe,
    curious_tilt,
    double_take,
    emphasis_look,
    head_shake,
    idle_scan,
    nod,
    search_scan,
    track_person,
)
from amy.nodes.base import Position

pytestmark = pytest.mark.unit


def take(gen, n: int) -> list[MotorCommand]:
    """Consume *n* commands from a motor program generator."""
    return list(islice(gen, n))


# ---------------------------------------------------------------------------
# MotorCommand defaults
# ---------------------------------------------------------------------------

class TestMotorCommand:
    def test_defaults(self):
        cmd = MotorCommand()
        assert cmd.pan_dir == 0
        assert cmd.tilt_dir == 0
        assert cmd.duration == 0.1
        assert cmd.pause_after == 0.0


# ---------------------------------------------------------------------------
# idle_scan
# ---------------------------------------------------------------------------

class TestIdleScan:
    def test_yields_commands(self, mock_node):
        random.seed(42)
        cmds = take(idle_scan(mock_node), 10)
        assert len(cmds) == 10
        assert all(isinstance(c, MotorCommand) for c in cmds)

    def test_reverses_at_left_limit(self, mock_node):
        """When the node is at the left limit, idle_scan should not yield
        pan_dir=-1 (it should reverse to pan right)."""
        mock_node._position.pan = mock_node._position.pan_min
        random.seed(0)
        cmds = take(idle_scan(mock_node), 30)
        panning = [c for c in cmds if c.pan_dir != 0]
        assert len(panning) > 0
        for c in panning:
            assert c.pan_dir == 1, (
                f"Expected pan_dir=1 at left limit, got {c.pan_dir}"
            )

    def test_reverses_at_right_limit(self, mock_node):
        """When the node is at the right limit, idle_scan should not yield
        pan_dir=1 (it should reverse to pan left)."""
        mock_node._position.pan = mock_node._position.pan_max
        random.seed(0)
        cmds = take(idle_scan(mock_node), 30)
        panning = [c for c in cmds if c.pan_dir != 0]
        assert len(panning) > 0
        for c in panning:
            assert c.pan_dir == -1, (
                f"Expected pan_dir=-1 at right limit, got {c.pan_dir}"
            )


# ---------------------------------------------------------------------------
# breathe
# ---------------------------------------------------------------------------

class TestBreathe:
    def test_alternating_tilt(self):
        cmds = take(breathe(), 4)
        assert cmds[0].tilt_dir == 1
        assert cmds[1].tilt_dir == -1
        assert cmds[2].tilt_dir == 1
        assert cmds[3].tilt_dir == -1
        for c in cmds:
            assert c.duration == 0.05
            assert c.pause_after == 2.0

    def test_infinite(self):
        cmds = take(breathe(), 10)
        assert len(cmds) == 10


# ---------------------------------------------------------------------------
# nod
# ---------------------------------------------------------------------------

class TestNod:
    def test_exactly_four_commands(self):
        cmds = list(nod())
        assert len(cmds) == 4

    def test_sequence(self):
        cmds = list(nod())
        # tilt up, tilt down, tilt up, tilt down
        assert cmds[0].tilt_dir == 1
        assert cmds[0].duration == 0.12
        assert cmds[1].tilt_dir == -1
        assert cmds[1].duration == 0.12
        assert cmds[2].tilt_dir == 1
        assert cmds[2].duration == 0.08
        assert cmds[3].tilt_dir == -1
        assert cmds[3].duration == 0.08


# ---------------------------------------------------------------------------
# track_person
# ---------------------------------------------------------------------------

class TestTrackPerson:
    def test_none_target_yields_breathing(self):
        gen = track_person(lambda: None)
        cmds = take(gen, 4)
        assert cmds[0].tilt_dir == 1
        assert cmds[0].duration == 0.05
        assert cmds[1].tilt_dir == -1
        assert cmds[1].duration == 0.05
        assert cmds[2].tilt_dir == 1
        assert cmds[3].tilt_dir == -1

    def test_centered_target_no_movement(self):
        gen = track_person(lambda: (0.5, 0.5))
        cmd = next(gen)
        assert cmd.pan_dir == 0
        assert cmd.tilt_dir == 0
        assert cmd.pause_after == 0.3

    def test_left_target_pans_left(self):
        gen = track_person(lambda: (0.2, 0.5))
        cmd = next(gen)
        assert cmd.pan_dir == -1

    def test_right_target_pans_right(self):
        gen = track_person(lambda: (0.8, 0.5))
        cmd = next(gen)
        assert cmd.pan_dir == 1

    def test_high_target_tilts_up(self):
        gen = track_person(lambda: (0.5, 0.2))
        cmd = next(gen)
        assert cmd.tilt_dir == 1

    def test_low_target_tilts_down(self):
        gen = track_person(lambda: (0.5, 0.8))
        cmd = next(gen)
        assert cmd.tilt_dir == -1


# ---------------------------------------------------------------------------
# auto_track
# ---------------------------------------------------------------------------

class TestAutoTrack:
    def test_switches_to_tracking(self, mock_node):
        """When a target appears, auto_track should produce tracking commands
        (pan/tilt toward the target) instead of scanning commands."""
        random.seed(42)
        target = [None]

        def target_fn():
            return target[0]

        gen = auto_track(mock_node, target_fn)
        # First few commands: no target -> scanning
        scan_cmds = take(gen, 3)
        assert len(scan_cmds) == 3

        # Now provide a left+high target
        target[0] = (0.1, 0.1)
        cmd = next(gen)
        assert cmd.pan_dir == -1
        assert cmd.tilt_dir == 1

    def test_switches_back_to_scanning(self, mock_node):
        """When the target disappears, auto_track should revert to scanning."""
        random.seed(42)
        target = [(0.2, 0.5)]

        def target_fn():
            return target[0]

        gen = auto_track(mock_node, target_fn)
        # Tracking phase
        cmd = next(gen)
        assert cmd.pan_dir == -1, "Should track left target"

        # Remove target -> scanning
        target[0] = None
        scan_cmds = take(gen, 5)
        assert len(scan_cmds) == 5
        # At least one scanning command should have a nonzero pan or pause
        assert any(c.pan_dir != 0 or c.pause_after > 0 for c in scan_cmds)


# ---------------------------------------------------------------------------
# search_scan
# ---------------------------------------------------------------------------

class TestSearchScan:
    def test_respects_limits(self, mock_node):
        """search_scan should flip pan direction when at limits rather than
        commanding movement into the wall."""
        mock_node._position.pan = mock_node._position.pan_min
        random.seed(0)
        cmds = take(search_scan(mock_node), 8)
        assert len(cmds) == 8
        for c in cmds:
            if c.pan_dir != 0:
                # At left limit every command should have been flipped to 1
                # (or the generator naturally chose 1).  It should never be -1
                # when can_pan_left is False.
                pos = mock_node.get_position()
                if not pos.can_pan_left:
                    assert c.pan_dir != -1


# ---------------------------------------------------------------------------
# Phase 3A: survey_room
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSurveyRoom:
    def test_survey_room_is_finite(self, mock_node):
        from amy.motor import survey_room
        cmds = list(survey_room(mock_node))
        assert len(cmds) > 0
        # Should end (finite generator)
        assert len(cmds) <= 15

    def test_survey_room_starts_with_pan_left(self, mock_node):
        from amy.motor import survey_room
        cmds = list(survey_room(mock_node))
        assert cmds[0].pan_dir == -1  # sweep to left limit first

    def test_survey_room_sweeps_right(self, mock_node):
        from amy.motor import survey_room
        cmds = list(survey_room(mock_node))
        right_pans = [c for c in cmds if c.pan_dir == 1]
        assert len(right_pans) >= 2  # multiple right sweep steps


# ---------------------------------------------------------------------------
# Expressive motor programs (C1)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHeadShake:
    def test_head_shake_is_finite(self, mock_node):
        cmds = list(head_shake(mock_node))
        assert len(cmds) > 0
        assert len(cmds) <= 10

    def test_head_shake_alternates_pan(self, mock_node):
        cmds = list(head_shake(mock_node))
        pan_dirs = [c.pan_dir for c in cmds if c.pan_dir != 0]
        assert len(pan_dirs) >= 2
        # Should have both left and right pans
        assert -1 in pan_dirs
        assert 1 in pan_dirs


@pytest.mark.unit
class TestDoubleTake:
    def test_double_take_is_finite(self, mock_node):
        cmds = list(double_take(mock_node))
        assert len(cmds) > 0
        assert len(cmds) <= 5

    def test_double_take_includes_tilt(self, mock_node):
        cmds = list(double_take(mock_node))
        tilts = [c for c in cmds if c.tilt_dir != 0]
        assert len(tilts) >= 1


@pytest.mark.unit
class TestCuriousTilt:
    def test_curious_tilt_is_finite(self):
        cmds = list(curious_tilt())
        assert len(cmds) == 2

    def test_curious_tilt_up_then_down(self):
        cmds = list(curious_tilt())
        assert cmds[0].tilt_dir == 1
        assert cmds[1].tilt_dir == -1

    def test_curious_tilt_has_pause(self):
        cmds = list(curious_tilt())
        assert cmds[0].pause_after >= 0.5


@pytest.mark.unit
class TestEmphasisLook:
    def test_emphasis_look_right(self, mock_node):
        cmds = list(emphasis_look(mock_node, direction=1))
        assert len(cmds) == 2
        assert cmds[0].pan_dir == 1
        assert cmds[1].pan_dir == -1

    def test_emphasis_look_left(self, mock_node):
        cmds = list(emphasis_look(mock_node, direction=-1))
        assert cmds[0].pan_dir == -1
        assert cmds[1].pan_dir == 1


@pytest.mark.unit
class TestAutoTrackMood:
    def test_auto_track_calm_slower(self, mock_node):
        """Calm mood produces slower movement durations."""
        random.seed(42)
        target = [(0.1, 0.5)]
        gen_calm = auto_track(mock_node, lambda: target[0], mood="calm")
        cmd_calm = next(gen_calm)

        random.seed(42)
        gen_neutral = auto_track(mock_node, lambda: target[0], mood="neutral")
        cmd_neutral = next(gen_neutral)

        assert cmd_calm.duration < cmd_neutral.duration

    def test_auto_track_excited_faster(self, mock_node):
        """Excited mood produces faster movement durations."""
        random.seed(42)
        target = [(0.1, 0.5)]
        gen_excited = auto_track(mock_node, lambda: target[0], mood="excited")
        cmd_excited = next(gen_excited)

        random.seed(42)
        gen_neutral = auto_track(mock_node, lambda: target[0], mood="neutral")
        cmd_neutral = next(gen_neutral)

        assert cmd_excited.duration > cmd_neutral.duration

    def test_auto_track_default_mood_backward_compat(self, mock_node):
        """auto_track() without mood param works (defaults to neutral)."""
        random.seed(42)
        gen = auto_track(mock_node, lambda: None)
        cmds = take(gen, 3)
        assert len(cmds) == 3
