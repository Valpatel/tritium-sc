# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for EntityFactory — graphling SimulationTarget management.

TDD: Written before implementation.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


def _make_mock_engine():
    """Create a mock SimulationEngine with add_target/remove_target."""
    engine = MagicMock()
    engine.add_target = MagicMock()
    engine.remove_target = MagicMock(return_value=True)
    return engine


class TestEntityFactory:
    """EntityFactory spawns and manages graphling SimulationTargets."""

    def test_spawn_creates_target(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        target_id = factory.spawn("soul_1", "Twilight", (100.0, 200.0))

        assert target_id is not None
        assert isinstance(target_id, str)
        engine.add_target.assert_called_once()

    def test_spawn_sets_graphling_asset_type(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        factory.spawn("soul_1", "Twilight", (100.0, 200.0))

        target = engine.add_target.call_args[0][0]
        assert target.asset_type == "graphling"

    def test_spawn_sets_non_combatant(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        factory.spawn("soul_1", "Twilight", (100.0, 200.0))

        target = engine.add_target.call_args[0][0]
        assert target.is_combatant is False

    def test_spawn_sets_friendly_alliance(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        factory.spawn("soul_1", "Twilight", (100.0, 200.0))

        target = engine.add_target.call_args[0][0]
        assert target.alliance == "friendly"

    def test_despawn_removes_target(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        factory.spawn("soul_1", "Twilight", (100.0, 200.0))
        result = factory.despawn("soul_1")

        assert result is True
        engine.remove_target.assert_called_once()

    def test_despawn_unknown_returns_false(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        result = factory.despawn("unknown_soul")

        assert result is False
        engine.remove_target.assert_not_called()

    def test_get_target_id_returns_correct_mapping(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        target_id = factory.spawn("soul_1", "Twilight", (100.0, 200.0))

        assert factory.get_target_id("soul_1") == target_id

    def test_get_target_id_unknown_returns_none(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)

        assert factory.get_target_id("unknown") is None

    def test_list_active_returns_all_spawned(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        factory.spawn("soul_1", "Twilight", (100.0, 200.0))
        factory.spawn("soul_2", "Moonrise", (50.0, 150.0))

        active = factory.list_active()
        assert len(active) == 2
        assert "soul_1" in active
        assert "soul_2" in active

    def test_despawn_removes_from_active(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        factory.spawn("soul_1", "Twilight", (100.0, 200.0))
        factory.spawn("soul_2", "Moonrise", (50.0, 150.0))
        factory.despawn("soul_1")

        active = factory.list_active()
        assert len(active) == 1
        assert "soul_2" in active

    def test_despawn_all_removes_all_targets(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)
        factory.spawn("soul_1", "Twilight", (100.0, 200.0))
        factory.spawn("soul_2", "Moonrise", (50.0, 150.0))
        factory.spawn("soul_3", "Dewdrop", (180.0, 220.0))

        factory.despawn_all()

        assert len(factory.list_active()) == 0
        assert engine.remove_target.call_count == 3

    def test_despawn_all_empty_is_noop(self):
        from graphlings.entity_factory import EntityFactory

        engine = _make_mock_engine()
        factory = EntityFactory(engine)

        # Should not raise
        factory.despawn_all()

        assert len(factory.list_active()) == 0
        engine.remove_target.assert_not_called()
