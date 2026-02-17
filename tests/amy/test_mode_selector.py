"""Unit tests for Live/Sim mode selector."""

from __future__ import annotations

import queue
import threading

import pytest

from amy.commander import Commander, EventBus
from amy.simulation.engine import SimulationEngine
from amy.simulation.target import SimulationTarget


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object = None) -> None:
        msg = {"type": topic}
        if data is not None:
            msg["data"] = data
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Commander mode property
# ---------------------------------------------------------------------------


class TestCommanderMode:
    """Test Commander.mode property and set_mode()."""

    def _make_commander(self, sim_engine=None):
        """Create a minimal Commander (no boot, no hardware)."""
        return Commander(
            nodes={},
            use_listener=False,
            use_tts=False,
            simulation_engine=sim_engine,
        )

    def test_default_mode_is_sim(self):
        cmd = self._make_commander()
        assert cmd.mode == "sim"

    def test_set_mode_to_live(self):
        cmd = self._make_commander()
        result = cmd.set_mode("live")
        assert result == "live"
        assert cmd.mode == "live"

    def test_set_mode_to_sim(self):
        cmd = self._make_commander()
        cmd._mode = "live"
        result = cmd.set_mode("sim")
        assert result == "sim"
        assert cmd.mode == "sim"

    def test_set_mode_invalid_raises(self):
        cmd = self._make_commander()
        with pytest.raises(ValueError, match="Invalid mode"):
            cmd.set_mode("hybrid")

    def test_set_mode_invalid_empty_raises(self):
        cmd = self._make_commander()
        with pytest.raises(ValueError, match="Invalid mode"):
            cmd.set_mode("")

    def test_set_mode_case_insensitive(self):
        cmd = self._make_commander()
        assert cmd.set_mode("LIVE") == "live"
        assert cmd.set_mode("SIM") == "sim"
        assert cmd.set_mode("  Live  ") == "live"

    def test_set_mode_publishes_event(self):
        cmd = self._make_commander()
        sub = cmd.event_bus.subscribe()
        cmd.set_mode("live")

        # Drain messages looking for mode_change
        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "mode_change":
                assert msg["data"]["mode"] == "live"
                assert msg["data"]["previous"] == "sim"
                found = True
                break
        assert found, "mode_change event not published"

    def test_set_mode_same_no_sensorium_push(self):
        cmd = self._make_commander()
        # Set mode to sim (already sim) — should not push to sensorium
        initial_count = cmd.sensorium.event_count
        cmd.set_mode("sim")
        assert cmd.sensorium.event_count == initial_count

    def test_set_mode_different_pushes_to_sensorium(self):
        cmd = self._make_commander()
        initial_count = cmd.sensorium.event_count
        cmd.set_mode("live")
        assert cmd.sensorium.event_count > initial_count

    def test_mode_in_context_update(self):
        """Commander._publish_context includes mode in the payload."""
        cmd = self._make_commander()
        # Need minimal setup for _publish_context
        cmd.chat_agent = None
        cmd.thinking = None
        cmd.vision_thread = None

        sub = cmd.event_bus.subscribe()
        cmd._publish_context()

        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "context_update":
                assert msg["data"]["mode"] == "sim"
                found = True
                break
        assert found, "context_update with mode not published"


# ---------------------------------------------------------------------------
# SimulationEngine spawner pause/resume
# ---------------------------------------------------------------------------


class TestSimulationEngineSpawnerPause:
    """Test SimulationEngine.pause_spawners() and resume_spawners()."""

    def test_spawners_not_paused_by_default(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        assert engine.spawners_paused is False

    def test_pause_spawners(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        engine.pause_spawners()
        assert engine.spawners_paused is True

    def test_resume_spawners(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        engine.pause_spawners()
        engine.resume_spawners()
        assert engine.spawners_paused is False

    def test_pause_resume_idempotent(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        engine.pause_spawners()
        engine.pause_spawners()
        assert engine.spawners_paused is True
        engine.resume_spawners()
        engine.resume_spawners()
        assert engine.spawners_paused is False


# ---------------------------------------------------------------------------
# Mode switching controls spawners
# ---------------------------------------------------------------------------


class TestModeSwitchingControlsSpawners:
    """Verify set_mode() pauses/resumes spawners via SimulationEngine."""

    def _make_engine(self):
        bus = SimpleEventBus()
        return SimulationEngine(bus)

    def test_live_mode_pauses_spawners(self):
        engine = self._make_engine()
        cmd = Commander(
            nodes={},
            use_listener=False,
            use_tts=False,
            simulation_engine=engine,
        )
        cmd.set_mode("live")
        assert engine.spawners_paused is True

    def test_sim_mode_resumes_spawners(self):
        engine = self._make_engine()
        cmd = Commander(
            nodes={},
            use_listener=False,
            use_tts=False,
            simulation_engine=engine,
        )
        cmd.set_mode("live")
        assert engine.spawners_paused is True
        cmd.set_mode("sim")
        assert engine.spawners_paused is False

    def test_mode_switch_without_engine(self):
        """Mode switching works even without a simulation engine."""
        cmd = Commander(
            nodes={},
            use_listener=False,
            use_tts=False,
            simulation_engine=None,
        )
        # Should not raise
        cmd.set_mode("live")
        assert cmd.mode == "live"
        cmd.set_mode("sim")
        assert cmd.mode == "sim"


# ---------------------------------------------------------------------------
# Thinking prompt includes mode context
# ---------------------------------------------------------------------------


class TestThinkingModeContext:
    """Verify the thinking prompt includes tactical mode context."""

    def test_sim_mode_in_battlespace(self):
        """In SIM mode, battlespace context includes SIMULATION MODE."""
        from amy.thinking import THINKING_SYSTEM_PROMPT

        # Format with sim mode prefix
        mode_prefix = "[SIMULATION MODE] Tactical data from simulated targets. Virtual neighborhood active."
        battlespace = f"{mode_prefix}\nFriendly units: 2"

        system = THINKING_SYSTEM_PROMPT.format(
            narrative="test narrative",
            battlespace=battlespace,
            memory="no memories",
            people="no people",
            self_model="no self-model",
            thoughts="none",
            goals="no goals",
            time_of_day="morning",
            war_mode="",
        )
        assert "SIMULATION MODE" in system
        assert "simulated targets" in system

    def test_live_mode_in_battlespace(self):
        """In LIVE mode, battlespace context includes LIVE SENSORS."""
        from amy.thinking import THINKING_SYSTEM_PROMPT

        mode_prefix = "[LIVE SENSORS] Tactical data from real cameras and sensors. Simulation spawners paused."
        battlespace = f"{mode_prefix}\nFriendly units: 2"

        system = THINKING_SYSTEM_PROMPT.format(
            narrative="test narrative",
            battlespace=battlespace,
            memory="no memories",
            people="no people",
            self_model="no self-model",
            thoughts="none",
            goals="no goals",
            time_of_day="morning",
            war_mode="",
        )
        assert "LIVE SENSORS" in system
        assert "real cameras" in system


# ---------------------------------------------------------------------------
# Config default
# ---------------------------------------------------------------------------


class TestConfigDefault:
    """Verify config has simulation_mode field."""

    def test_config_simulation_mode_default(self):
        from app.config import Settings
        s = Settings()
        assert s.simulation_mode == "sim"

    def test_config_simulation_mode_accepts_live(self):
        from app.config import Settings
        s = Settings(simulation_mode="live")
        assert s.simulation_mode == "live"


# ---------------------------------------------------------------------------
# create_amy applies initial mode from config
# ---------------------------------------------------------------------------


class TestCreateAmyMode:
    """Verify create_amy sets initial mode from settings."""

    def test_create_amy_default_sim(self):
        from amy import create_amy
        from app.config import Settings
        settings = Settings(
            amy_enabled=True,
            simulation_mode="sim",
        )
        cmd = create_amy(settings=settings, simulation_engine=None)
        assert cmd.mode == "sim"

    def test_create_amy_live_mode(self):
        from amy import create_amy
        from app.config import Settings
        settings = Settings(
            amy_enabled=True,
            simulation_mode="live",
        )
        cmd = create_amy(settings=settings, simulation_engine=None)
        assert cmd.mode == "live"

    def test_create_amy_invalid_mode_stays_sim(self):
        from amy import create_amy
        from app.config import Settings
        settings = Settings(
            amy_enabled=True,
            simulation_mode="hybrid",
        )
        cmd = create_amy(settings=settings, simulation_engine=None)
        # Invalid modes are not applied — stays at default
        assert cmd.mode == "sim"
