# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for BackstoryGenerator — distributed unit backstory generation.

TDD: These tests are written FIRST, before the implementation.
They should all fail until backstory.py is implemented.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Target under test (will fail on import until implemented)
from engine.simulation.backstory import BackstoryGenerator

from tritium_lib.sim_engine.core.entity import SimulationTarget
from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str = "t1",
    name: str = "Alpha",
    alliance: str = "friendly",
    asset_type: str = "turret",
    position: tuple[float, float] = (10.0, 20.0),
    is_combatant: bool = True,
    is_leader: bool = False,
    heading: float = 0.0,
) -> SimulationTarget:
    """Create a minimal SimulationTarget for testing."""
    return SimulationTarget(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        heading=heading,
        speed=0.0 if asset_type == "turret" else 2.0,
        is_combatant=is_combatant,
        is_leader=is_leader,
    )


def _make_fleet(response: str = "", has_model: bool = True) -> MagicMock:
    """Create a mock OllamaFleet."""
    fleet = MagicMock()
    host = MagicMock()
    host.url = "http://localhost:11434"
    host.name = "localhost"
    host.latency_ms = 10.0
    if has_model:
        fleet.hosts_with_model.return_value = [host]
    else:
        fleet.hosts_with_model.return_value = []
    fleet.generate.return_value = response
    return fleet


def _valid_defender_json() -> str:
    """Return a valid defender backstory JSON string."""
    return json.dumps({
        "name": "Sentinel-7",
        "background": "Deployed during the initial security buildup.",
        "motivation": "Protect the eastern perimeter at all costs.",
        "personality_traits": ["vigilant", "methodical"],
        "speech_pattern": "Clipped military radio jargon.",
        "neighborhood_relationship": "Silent guardian of Oak Street.",
        "tactical_preference": "Overlapping fields of fire.",
    })


def _valid_hostile_json() -> str:
    """Return a valid hostile backstory JSON string."""
    return json.dumps({
        "name": "Ghost",
        "background": "Former private security, gone rogue.",
        "motivation": "Hired to breach the perimeter defense.",
        "personality_traits": ["aggressive", "cunning"],
        "speech_pattern": "Terse hand signals and whispered orders.",
        "tactical_preference": "Flanking maneuvers under cover.",
    })


def _valid_neutral_json() -> str:
    """Return a valid neutral backstory JSON string."""
    return json.dumps({
        "name": "Maria Chen",
        "background": "Lives two blocks east. Works at the library.",
        "motivation": "Walking to the bus stop for her morning shift.",
        "personality_traits": ["friendly", "punctual"],
        "speech_pattern": "Cheerful greetings to familiar faces.",
        "daily_routine": "Leaves at 7:15am, returns at 4pm.",
        "neighborhood_relationship": "Known by all the dog walkers.",
    })


# ===========================================================================
# Priority Assignment (5 tests)
# ===========================================================================

class TestPriorityAssignment:
    """BackstoryGenerator._compute_priority() assigns correct priority + model."""

    def test_friendly_combatant_gets_priority_01(self):
        """Friendly turret/rover/drone -> priority 0.1, key model."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(alliance="friendly", asset_type="turret")
        pri, model = gen._compute_priority(target)
        assert pri == pytest.approx(0.1)
        assert model == gen._key_character_model

    def test_hostile_leader_gets_priority_03(self):
        """Hostile leader -> priority 0.3, key model."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(alliance="hostile", asset_type="person", is_leader=True)
        pri, model = gen._compute_priority(target)
        assert pri == pytest.approx(0.3)
        assert model == gen._key_character_model

    def test_hostile_tank_gets_priority_03(self):
        """Hostile tank -> priority 0.3, key model."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(alliance="hostile", asset_type="tank")
        pri, model = gen._compute_priority(target)
        assert pri == pytest.approx(0.3)
        assert model == gen._key_character_model

    def test_regular_hostile_gets_priority_05(self):
        """Regular hostile person -> priority 0.5, bulk model."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(alliance="hostile", asset_type="person", name="Hostile-1")
        pri, model = gen._compute_priority(target)
        assert pri == pytest.approx(0.5)
        assert model == gen._bulk_model

    def test_neutral_named_npc_gets_priority_07(self):
        """Named neutral NPC -> priority 0.7, bulk model."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(
            alliance="neutral", asset_type="person", name="Maria Chen",
            is_combatant=False,
        )
        pri, model = gen._compute_priority(target)
        assert pri == pytest.approx(0.7)
        assert model == gen._bulk_model

    def test_generic_neutral_gets_priority_09(self):
        """Generic neutral (animal, vehicle) -> priority 0.9, bulk model."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(
            alliance="neutral", asset_type="animal", name="Cat",
            is_combatant=False,
        )
        pri, model = gen._compute_priority(target)
        assert pri == pytest.approx(0.9)
        assert model == gen._bulk_model


# ===========================================================================
# Validation (5 tests)
# ===========================================================================

class TestValidation:
    """BackstoryGenerator._validate_backstory() checks required fields."""

    def test_valid_defender_backstory_passes(self):
        """All required defender fields present -> True."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        data = json.loads(_valid_defender_json())
        assert gen._validate_backstory(data, "friendly") is True

    def test_valid_hostile_backstory_passes(self):
        """All required hostile fields present -> True."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        data = json.loads(_valid_hostile_json())
        assert gen._validate_backstory(data, "hostile") is True

    def test_valid_neutral_backstory_passes(self):
        """All required neutral fields present -> True."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        data = json.loads(_valid_neutral_json())
        assert gen._validate_backstory(data, "neutral") is True

    def test_missing_required_field_returns_false(self):
        """Missing 'motivation' -> False."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        data = {"name": "X", "background": "Y", "personality_traits": ["a"], "speech_pattern": "b"}
        # Missing 'motivation'
        assert gen._validate_backstory(data, "hostile") is False

    def test_markdown_code_block_extraction(self):
        """JSON wrapped in markdown ```json ... ``` is correctly extracted."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        raw = "```json\n" + _valid_hostile_json() + "\n```"
        result = gen._parse_response(raw, "hostile")
        assert result is not None
        assert result["name"] == "Ghost"


# ===========================================================================
# Prompt Building (3 tests)
# ===========================================================================

class TestPromptBuilding:
    """BackstoryGenerator._build_prompt() produces correct prompts."""

    def test_defender_prompt_includes_position_and_schema(self):
        """Defender prompt includes position, asset_type, JSON schema fields."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(alliance="friendly", asset_type="turret", position=(50.0, 75.0))
        prompt = gen._build_prompt(target)
        assert "turret" in prompt
        assert "50" in prompt  # x position
        assert "75" in prompt  # y position
        assert "neighborhood_relationship" in prompt
        assert "tactical_preference" in prompt

    def test_hostile_prompt_includes_approach_direction(self):
        """Hostile prompt mentions approach direction."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(alliance="hostile", asset_type="person", heading=90.0)
        prompt = gen._build_prompt(target)
        assert "hostile" in prompt.lower() or "intruder" in prompt.lower() or "attacker" in prompt.lower()
        # Should include some indication of heading/direction
        assert "heading" in prompt.lower() or "approach" in prompt.lower() or "direction" in prompt.lower()

    def test_neutral_prompt_includes_daily_routine_schema(self):
        """Neutral prompt includes name, daily_routine in schema."""
        bus = EventBus()
        gen = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(
            alliance="neutral", asset_type="person", name="Bob Smith",
            is_combatant=False,
        )
        prompt = gen._build_prompt(target)
        assert "Bob Smith" in prompt
        assert "daily_routine" in prompt
        assert "neighborhood_relationship" in prompt


# ===========================================================================
# Cache (4 tests)
# ===========================================================================

class TestCache:
    """BackstoryGenerator disk cache operations."""

    def test_cache_hit_skips_llm(self):
        """When backstory is cached, no LLM call is made."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            fleet = _make_fleet(response=_valid_defender_json())
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(alliance="friendly", asset_type="turret", name="Alpha")

            # Pre-populate cache
            backstory = json.loads(_valid_defender_json())
            key = gen._cache_key(target)
            gen._save_to_cache(key, backstory)

            # Now generate — should use cache, not fleet
            result = gen._generate_backstory(target, gen._key_character_model)
            assert result is not None
            assert result["name"] == "Sentinel-7"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cache_write_on_success(self):
        """Successful generation writes to cache."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            fleet = _make_fleet(response=_valid_defender_json())
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(alliance="friendly", asset_type="turret", name="Bravo")

            # Generate — should write to cache
            result = gen._generate_backstory(target, gen._key_character_model)
            assert result is not None

            # Check that cache now has an entry
            key = gen._cache_key(target)
            assert key in gen._cache
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cache_key_stable_across_sessions(self):
        """Same (alliance, asset_type, name) produces same cache key."""
        bus = EventBus()
        gen1 = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        gen2 = BackstoryGenerator(fleet=_make_fleet(), event_bus=bus)
        target = _make_target(alliance="hostile", asset_type="person", name="Ghost")
        key1 = gen1._cache_key(target)
        key2 = gen2._cache_key(target)
        assert key1 == key2
        # Key should be deterministic
        assert isinstance(key1, str) and len(key1) > 0

    def test_clear_cache_removes_files(self):
        """clear_cache() empties both in-memory dict and disk."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            gen = BackstoryGenerator(
                fleet=_make_fleet(), event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(alliance="friendly", asset_type="rover", name="Test")
            backstory = json.loads(_valid_defender_json())
            key = gen._cache_key(target)
            gen._save_to_cache(key, backstory)

            assert key in gen._cache
            gen.clear_cache()
            assert key not in gen._cache
            # Index file should be gone or empty
            index_path = Path(tmp) / "index.json"
            if index_path.exists():
                data = json.loads(index_path.read_text())
                assert len(data) == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Integration (3 tests)
# ===========================================================================

class TestIntegration:
    """BackstoryGenerator integration with EventBus, targets, ThoughtRegistry."""

    def test_event_emitted_on_backstory_completion(self):
        """backstory_generated event is published to EventBus."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            q = bus.subscribe()
            fleet = _make_fleet(response=_valid_defender_json())
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(alliance="friendly", asset_type="turret")

            # Call _on_backstory_complete directly
            backstory = json.loads(_valid_defender_json())
            gen._on_backstory_complete(target.target_id, backstory)

            # Drain the queue looking for our event
            found = False
            while not q.empty():
                msg = q.get_nowait()
                if msg.get("type") == "backstory_generated":
                    found = True
                    assert msg["data"]["target_id"] == target.target_id
                    break
            assert found, "backstory_generated event not found on EventBus"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_target_name_updated_from_backstory(self):
        """If LLM provides a better name, target.name is updated."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            fleet = _make_fleet(response=_valid_defender_json())
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(
                alliance="friendly", asset_type="turret", name="Turret-1",
            )
            gen._targets = {target.target_id: target}

            backstory = json.loads(_valid_defender_json())
            gen._on_backstory_complete(target.target_id, backstory)

            # The backstory name "Sentinel-7" should replace "Turret-1"
            assert target.name == "Sentinel-7"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_thought_bubble_set_on_completion(self):
        """ThoughtRegistry.set_thought() is called with intro text."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            fleet = _make_fleet(response=_valid_defender_json())
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            thought_reg = MagicMock()
            gen._thought_registry = thought_reg

            backstory = json.loads(_valid_defender_json())
            gen._on_backstory_complete("t1", backstory)

            thought_reg.set_thought.assert_called_once()
            args, kwargs = thought_reg.set_thought.call_args
            assert args[0] == "t1"  # unit_id
            # Text should be from backstory motivation or background
            assert len(args[1]) > 0 or len(kwargs.get("text", "")) > 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Error Handling (3 tests)
# ===========================================================================

class TestErrorHandling:
    """BackstoryGenerator retry and fallback behavior."""

    def test_retry_on_malformed_response(self):
        """Malformed JSON triggers one retry."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            # First call returns garbage, second returns valid JSON
            fleet = _make_fleet()
            fleet.generate.side_effect = [
                "This is not JSON at all!",
                _valid_hostile_json(),
            ]
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(alliance="hostile", asset_type="person")
            result = gen._generate_backstory(target, gen._bulk_model)
            assert result is not None
            assert result["name"] == "Ghost"
            # fleet.generate should have been called twice (retry)
            assert fleet.generate.call_count == 2
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fallback_to_scripted_after_two_failures(self):
        """Two failures -> scripted fallback returned."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            fleet = _make_fleet()
            fleet.generate.side_effect = [
                "garbage",
                "more garbage",
            ]
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(alliance="hostile", asset_type="person", name="Hostile-X")
            result = gen._generate_backstory(target, gen._bulk_model)
            # Should return a scripted fallback (dict with at least 'name')
            assert result is not None
            assert "name" in result
            # Scripted fallbacks still have required keys
            assert "background" in result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_crash_when_fleet_unavailable(self):
        """No hosts available -> scripted fallback, no exception."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            fleet = _make_fleet(has_model=False)
            fleet.generate.return_value = ""
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
            )
            target = _make_target(alliance="friendly", asset_type="rover", name="Rover-1")
            result = gen._generate_backstory(target, gen._key_character_model)
            # Should get scripted fallback
            assert result is not None
            assert "name" in result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Host Selection (2 tests)
# ===========================================================================

class TestHostSelection:
    """BackstoryGenerator._select_host() weighted round-robin."""

    def test_select_host_returns_a_host(self):
        """With available hosts, _select_host returns one."""
        bus = EventBus()
        fleet = _make_fleet()
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus)
        host = gen._select_host("gemma3:1b")
        assert host is not None
        assert host.url == "http://localhost:11434"

    def test_select_host_none_when_no_hosts(self):
        """With no hosts having the model, returns None."""
        bus = EventBus()
        fleet = _make_fleet(has_model=False)
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus)
        host = gen._select_host("gemma3:1b")
        assert host is None


# ===========================================================================
# Concurrency / Stop (2 tests)
# ===========================================================================

class TestConcurrency:
    """BackstoryGenerator worker lifecycle."""

    def test_stop_drains_workers(self):
        """stop() sets running=False and workers exit."""
        bus = EventBus()
        fleet = _make_fleet()
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus, max_concurrent=2)
        gen.start()
        assert gen._running is True
        assert len(gen._workers) == 2
        gen.stop()
        assert gen._running is False
        # Workers should have exited
        for t in gen._workers:
            assert not t.is_alive()

    def test_enqueue_processes_target(self):
        """Enqueuing a target results in backstory generation."""
        tmp = tempfile.mkdtemp()
        try:
            bus = EventBus()
            q = bus.subscribe()
            fleet = _make_fleet(response=_valid_defender_json())
            gen = BackstoryGenerator(
                fleet=fleet, event_bus=bus, cache_dir=Path(tmp),
                max_concurrent=1,
            )
            target = _make_target(alliance="friendly", asset_type="turret")
            gen._targets = {target.target_id: target}
            gen.start()
            gen.enqueue(target)

            # Wait for processing (up to 5s)
            deadline = time.monotonic() + 5.0
            found = False
            while time.monotonic() < deadline:
                if not q.empty():
                    msg = q.get_nowait()
                    if msg.get("type") == "backstory_generated":
                        found = True
                        break
                time.sleep(0.1)
            gen.stop()
            assert found, "backstory_generated event not received within timeout"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Engine Wiring (5 tests)
# ===========================================================================

class TestEngineWiring:
    """Verify BackstoryGenerator is wired into SimulationEngine lifecycle."""

    def test_engine_has_backstory_generator_field(self):
        """Engine.__init__ creates _backstory_generator field (initially None)."""
        from engine.simulation.engine import SimulationEngine
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        assert hasattr(engine, '_backstory_generator')
        assert engine._backstory_generator is None

    def test_engine_start_creates_backstory_generator(self):
        """Engine.start() creates a BackstoryGenerator when backstory_enabled=True."""
        from engine.simulation.engine import SimulationEngine
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        mock_fleet = _make_fleet(response=_valid_defender_json())
        with patch('tritium_lib.inference.fleet.OllamaFleet', return_value=mock_fleet):
            with patch('app.config.settings') as mock_settings:
                mock_settings.backstory_enabled = True
                mock_settings.backstory_bulk_model = "gemma3:1b"
                mock_settings.backstory_key_model = "gemma3:4b"
                mock_settings.backstory_max_concurrent = 1
                mock_settings.backstory_cache_dir = "data/backstories"
                mock_settings.npc_max_vehicles = 0
                mock_settings.npc_max_pedestrians = 0
                mock_settings.npc_enabled = False
                engine.start()
        try:
            assert engine._backstory_generator is not None
            assert isinstance(engine._backstory_generator, BackstoryGenerator)
            assert engine._backstory_generator._running is True
        finally:
            engine.stop()

    def test_engine_stop_stops_backstory_generator(self):
        """Engine.stop() calls backstory_generator.stop()."""
        from engine.simulation.engine import SimulationEngine
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        mock_fleet = _make_fleet(response=_valid_defender_json())
        with patch('tritium_lib.inference.fleet.OllamaFleet', return_value=mock_fleet):
            with patch('app.config.settings') as mock_settings:
                mock_settings.backstory_enabled = True
                mock_settings.backstory_bulk_model = "gemma3:1b"
                mock_settings.backstory_key_model = "gemma3:4b"
                mock_settings.backstory_max_concurrent = 1
                mock_settings.backstory_cache_dir = "data/backstories"
                mock_settings.npc_max_vehicles = 0
                mock_settings.npc_max_pedestrians = 0
                mock_settings.npc_enabled = False
                engine.start()
        assert engine._backstory_generator is not None
        engine.stop()
        # After stop, generator should be None (cleaned up)
        assert engine._backstory_generator is None

    def test_engine_wires_backstory_to_unit_missions(self):
        """Engine.start() calls unit_missions.set_backstory_generator()."""
        from engine.simulation.engine import SimulationEngine
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        mock_fleet = _make_fleet(response=_valid_defender_json())
        with patch('tritium_lib.inference.fleet.OllamaFleet', return_value=mock_fleet):
            with patch('app.config.settings') as mock_settings:
                mock_settings.backstory_enabled = True
                mock_settings.backstory_bulk_model = "gemma3:1b"
                mock_settings.backstory_key_model = "gemma3:4b"
                mock_settings.backstory_max_concurrent = 1
                mock_settings.backstory_cache_dir = "data/backstories"
                mock_settings.npc_max_vehicles = 0
                mock_settings.npc_max_pedestrians = 0
                mock_settings.npc_enabled = False
                engine.start()
        try:
            # unit_missions should have the backstory generator wired
            assert engine.unit_missions._backstory_generator is engine._backstory_generator
        finally:
            engine.stop()

    def test_add_target_triggers_backstory_request(self):
        """Adding a target to the engine triggers request_llm_backstory which enqueues."""
        from engine.simulation.engine import SimulationEngine
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        mock_fleet = _make_fleet(response=_valid_defender_json())
        with patch('tritium_lib.inference.fleet.OllamaFleet', return_value=mock_fleet):
            with patch('app.config.settings') as mock_settings:
                mock_settings.backstory_enabled = True
                mock_settings.backstory_bulk_model = "gemma3:1b"
                mock_settings.backstory_key_model = "gemma3:4b"
                mock_settings.backstory_max_concurrent = 1
                mock_settings.backstory_cache_dir = "data/backstories"
                mock_settings.npc_max_vehicles = 0
                mock_settings.npc_max_pedestrians = 0
                mock_settings.npc_enabled = False
                engine.start()
        try:
            target = _make_target(
                target_id="test-turret-1",
                alliance="friendly",
                asset_type="turret",
                name="Turret Alpha",
            )
            engine.add_target(target)
            # The backstory generator should have a pending request
            # (either in queue or already processed)
            gen = engine._backstory_generator
            assert gen is not None
            # Give workers a brief moment to process
            time.sleep(0.5)
            # The target should either be pending or already have a backstory
            has_backstory = gen.get_backstory("test-turret-1") is not None
            in_pending = "test-turret-1" in gen._pending
            assert has_backstory or in_pending, \
                "Target should have a backstory or be pending generation"
        finally:
            engine.stop()
