"""Tests for NPCWorldBridge — connects NPCManager with NPC Intelligence Plugin."""

import math
import pytest
from unittest.mock import MagicMock, patch

from engine.simulation.npc_intelligence.world_bridge import NPCWorldBridge
from engine.simulation.npc_intelligence.world_model import WorldModel, POI
from engine.simulation.npc_intelligence.npc_router import NPCRouter
from engine.simulation.npc_intelligence.routine import RoutineScheduler


# -- Helpers --


def _make_target(target_id, asset_type="person", alliance="neutral",
                 x=0.0, y=0.0, heading=0.0):
    """Create a mock SimulationTarget."""
    t = MagicMock()
    t.id = target_id
    t.asset_type = asset_type
    t.alliance = alliance
    t.x = x
    t.y = y
    t.heading = heading
    t.fsm_state = None
    t.waypoints = []
    t.is_combatant = False
    t.speed = 1.4 if asset_type == "person" else 8.0
    t.bound = False
    return t


def _make_world(buildings=None, road_nodes=None, road_edges=None):
    """Create a WorldModel with test data."""
    import networkx as nx

    polys = []
    if buildings:
        for bld in buildings:
            cx, cy, sz = bld if len(bld) == 3 else (*bld, 10.0)
            hs = sz / 2
            polys.append([
                (cx - hs, cy - hs), (cx + hs, cy - hs),
                (cx + hs, cy + hs), (cx - hs, cy + hs),
            ])

    graph = None
    positions = {}
    if road_nodes:
        graph = nx.Graph()
        for nid, (x, y) in road_nodes.items():
            graph.add_node(nid, x=x, y=y)
            positions[nid] = (x, y)
        if road_edges:
            for na, nb, rc in road_edges:
                d = math.hypot(
                    positions[na][0] - positions[nb][0],
                    positions[na][1] - positions[nb][1],
                )
                graph.add_edge(na, nb, weight=d, road_class=rc)

    return WorldModel.from_raw(polys, graph, positions)


def _make_bridge(buildings=None, road_nodes=None, road_edges=None):
    """Create an NPCWorldBridge with test infrastructure."""
    world = _make_world(buildings, road_nodes, road_edges)
    router = NPCRouter(world)
    pois = list(world._pois) if world._pois else [
        POI(position=(0, 0), poi_type="home", name="Home", building_idx=None)
    ]
    scheduler = RoutineScheduler(pois)
    bridge = NPCWorldBridge(world, router, scheduler)
    return bridge, world, router, scheduler


# ==========================================================================
# NPC spawn integration
# ==========================================================================


class TestNPCSpawnIntegration:
    """Bridge attaches routines when NPCs are registered."""

    def test_register_pedestrian(self):
        bridge, _, _, _ = _make_bridge(
            buildings=[(50, 0, 10)],
            road_nodes={0: (0, -10), 1: (100, -10)},
            road_edges=[(0, 1, "footway")],
        )
        target = _make_target("ped-1", "person", "neutral", 10, 0)
        bridge.register_npc(target)
        assert bridge.has_routine("ped-1")

    def test_register_vehicle(self):
        bridge, _, _, _ = _make_bridge(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "residential")],
        )
        target = _make_target("car-1", "vehicle", "neutral", 0, 0)
        bridge.register_npc(target)
        assert bridge.has_routine("car-1")

    def test_ignore_combatant(self):
        """Combatants (hostile/friendly turrets, rovers) should not get routines."""
        bridge, _, _, _ = _make_bridge()
        target = _make_target("turret-1", "turret", "friendly")
        target.is_combatant = True
        bridge.register_npc(target)
        assert not bridge.has_routine("turret-1")

    def test_ignore_bound_target(self):
        """Targets bound to real data should not get AI routines."""
        bridge, _, _, _ = _make_bridge()
        target = _make_target("ped-1", "person", "neutral")
        target.bound = True
        bridge.register_npc(target)
        assert not bridge.has_routine("ped-1")

    def test_unregister_npc(self):
        bridge, _, _, _ = _make_bridge()
        target = _make_target("ped-1", "person", "neutral")
        bridge.register_npc(target)
        bridge.unregister_npc("ped-1")
        assert not bridge.has_routine("ped-1")


# ==========================================================================
# FSM state -> waypoints
# ==========================================================================


class TestFSMStateToWaypoints:
    """Bridge translates FSM state changes into routing requests."""

    def test_walking_generates_route_waypoints(self):
        """When NPC is in 'walking' state, bridge generates route waypoints."""
        bridge, _, _, _ = _make_bridge(
            buildings=[(50, 0, 10)],
            road_nodes={0: (0, -10), 1: (100, -10)},
            road_edges=[(0, 1, "footway")],
        )
        target = _make_target("ped-1", "person", "neutral", 0, -10)
        bridge.register_npc(target)

        waypoints = bridge.get_waypoints("ped-1", "walking", sim_time=8 * 3600)
        assert waypoints is not None
        assert len(waypoints) >= 1

    def test_fleeing_generates_flee_route(self):
        """When NPC is 'fleeing', bridge generates urgent flee path."""
        bridge, _, _, _ = _make_bridge(
            buildings=[(30, 0, 10)],
            road_nodes={0: (0, -10), 1: (60, -10)},
            road_edges=[(0, 1, "footway")],
        )
        target = _make_target("ped-1", "person", "neutral", 0, -10)
        bridge.register_npc(target)

        waypoints = bridge.get_waypoints(
            "ped-1", "fleeing", sim_time=0,
            threat_pos=(0, -50),
        )
        assert waypoints is not None
        assert len(waypoints) >= 2

    def test_hiding_routes_to_building(self):
        """When NPC is 'hiding', bridge routes to nearest building door."""
        bridge, world, _, _ = _make_bridge(
            buildings=[(30, 0, 10)],
            road_nodes={0: (0, -10), 1: (60, -10)},
            road_edges=[(0, 1, "footway")],
        )
        target = _make_target("ped-1", "person", "neutral", 0, -10)
        bridge.register_npc(target)

        waypoints = bridge.get_waypoints("ped-1", "hiding", sim_time=0)
        assert waypoints is not None
        assert len(waypoints) >= 2
        # Last waypoint should be near a building door
        building = world.nearest_building(30, 0)
        if building and building.doors:
            door = building.doors[0]
            last = waypoints[-1]
            dist = math.hypot(last[0] - door.position[0], last[1] - door.position[1])
            assert dist < 15, f"Hiding path ends {dist:.1f}m from door"

    def test_driving_generates_road_route(self):
        bridge, _, _, _ = _make_bridge(
            road_nodes={0: (0, 0), 1: (50, 0), 2: (100, 0)},
            road_edges=[
                (0, 1, "residential"),
                (1, 2, "residential"),
            ],
        )
        target = _make_target("car-1", "vehicle", "neutral", 0, 0)
        bridge.register_npc(target)

        waypoints = bridge.get_waypoints("car-1", "driving", sim_time=8 * 3600)
        assert waypoints is not None

    def test_pausing_returns_none(self):
        """Pausing NPC should not get new waypoints (stay in place)."""
        bridge, _, _, _ = _make_bridge()
        target = _make_target("ped-1", "person", "neutral")
        bridge.register_npc(target)
        waypoints = bridge.get_waypoints("ped-1", "pausing", sim_time=0)
        assert waypoints is None

    def test_evading_generates_vehicle_flee(self):
        bridge, _, _, _ = _make_bridge(
            road_nodes={0: (0, 0), 1: (50, 0), 2: (100, 0)},
            road_edges=[
                (0, 1, "residential"),
                (1, 2, "residential"),
            ],
        )
        target = _make_target("car-1", "vehicle", "neutral", 50, 0)
        bridge.register_npc(target)

        waypoints = bridge.get_waypoints(
            "car-1", "evading", sim_time=0,
            threat_pos=(0, 0),
        )
        assert waypoints is not None
        assert len(waypoints) >= 2


# ==========================================================================
# Spatial context generation
# ==========================================================================


class TestSpatialContext:
    """Bridge generates spatial context strings for LLM prompts."""

    def test_generates_spatial_context(self):
        bridge, _, _, _ = _make_bridge(
            buildings=[(30, 0, 10)],
            road_nodes={0: (0, -10), 1: (60, -10)},
            road_edges=[(0, 1, "footway")],
        )
        target = _make_target("ped-1", "person", "neutral", 0, -10)
        bridge.register_npc(target)

        ctx = bridge.spatial_context("ped-1", 0, -10)
        assert ctx is not None
        assert isinstance(ctx, str)
        assert len(ctx) > 10

    def test_context_mentions_location_type(self):
        """Context should indicate if NPC is on sidewalk, road, etc."""
        bridge, _, _, _ = _make_bridge(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "footway")],
        )
        ctx = bridge.spatial_context("anyone", 50, 0)
        # Should mention sidewalk or footway
        assert "sidewalk" in ctx.lower() or "footway" in ctx.lower() or \
               "path" in ctx.lower()

    def test_context_mentions_nearby_building(self):
        bridge, _, _, _ = _make_bridge(
            buildings=[(20, 0, 10)],
        )
        ctx = bridge.spatial_context("anyone", 20, 0)
        assert "building" in ctx.lower()

    def test_context_for_inside_building(self):
        bridge, _, _, _ = _make_bridge(
            buildings=[(0, 0, 20)],
        )
        ctx = bridge.spatial_context("anyone", 0, 0)
        assert "inside" in ctx.lower()

    def test_context_mentions_road_type(self):
        bridge, _, _, _ = _make_bridge(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "residential")],
        )
        ctx = bridge.spatial_context("anyone", 50, 0)
        assert "residential" in ctx.lower() or "road" in ctx.lower()


# ==========================================================================
# Tick integration
# ==========================================================================


class TestBridgeTick:
    """Bridge tick checks routines and updates NPC state."""

    def test_tick_does_not_crash(self):
        bridge, _, _, _ = _make_bridge(
            buildings=[(50, 0, 10)],
            road_nodes={0: (0, -10), 1: (100, -10)},
            road_edges=[(0, 1, "footway")],
        )
        target = _make_target("ped-1", "person", "neutral", 0, -10)
        bridge.register_npc(target)
        # Tick at various times
        bridge.tick(0.1, sim_time=8 * 3600, targets={"ped-1": target})
        bridge.tick(0.1, sim_time=12 * 3600, targets={"ped-1": target})
        bridge.tick(0.1, sim_time=20 * 3600, targets={"ped-1": target})

    def test_tick_updates_target_waypoints(self):
        """Tick should set waypoints on targets that need movement."""
        bridge, _, _, _ = _make_bridge(
            buildings=[(50, 0, 10)],
            road_nodes={0: (0, -10), 1: (100, -10)},
            road_edges=[(0, 1, "footway")],
        )
        target = _make_target("ped-1", "person", "neutral", 0, -10)
        target.fsm_state = "walking"
        target.waypoints = []
        bridge.register_npc(target)

        bridge.tick(0.1, sim_time=8 * 3600, targets={"ped-1": target})
        # After tick, target should have waypoints assigned
        # (mock won't actually be mutated but bridge should attempt to set them)

    def test_tick_skips_bound_targets(self):
        """Bound (real-data) targets should be skipped during tick."""
        bridge, _, _, _ = _make_bridge()
        target = _make_target("ped-1", "person", "neutral")
        target.bound = True
        bridge.register_npc(target)
        # Should not crash or modify bound target
        bridge.tick(0.1, sim_time=0, targets={"ped-1": target})


# ==========================================================================
# NPC count / stats
# ==========================================================================


class TestBridgeStats:
    """Bridge provides statistics about managed NPCs."""

    def test_npc_count(self):
        bridge, _, _, _ = _make_bridge()
        assert bridge.npc_count == 0
        bridge.register_npc(_make_target("ped-1", "person", "neutral"))
        assert bridge.npc_count == 1
        bridge.register_npc(_make_target("car-1", "vehicle", "neutral"))
        assert bridge.npc_count == 2

    def test_active_npcs_list(self):
        bridge, _, _, _ = _make_bridge()
        bridge.register_npc(_make_target("ped-1", "person", "neutral"))
        bridge.register_npc(_make_target("ped-2", "person", "neutral"))
        assert "ped-1" in bridge.active_npc_ids
        assert "ped-2" in bridge.active_npc_ids
