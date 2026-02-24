"""Unit tests for StreetGraph.to_polylines() and BuildingObstacles serialization.

Tests:
- StreetGraph.to_polylines(): edge walking, road_class extraction, empty graph
- BuildingObstacles.load_from_overture(): polygon loading, validation, filtering
- BuildingObstacles.to_dicts(): serialization format, default_height parameter
"""
from __future__ import annotations

import pytest
import networkx as nx

from engine.tactical.street_graph import StreetGraph
from engine.tactical.obstacles import BuildingObstacles

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_street_graph(
    edges: list[tuple[int, int, dict]],
    positions: dict[int, tuple[float, float]],
) -> StreetGraph:
    """Build a StreetGraph with a manually constructed NetworkX graph.

    Args:
        edges: list of (node_a, node_b, edge_data_dict) where edge_data_dict
               should contain at least 'weight' and optionally 'road_class'.
        positions: mapping of node_id -> (x, y) in local meters.
    """
    sg = StreetGraph()
    G = nx.Graph()
    for nid, pos in positions.items():
        G.add_node(nid, x=pos[0], y=pos[1])
    for n1, n2, data in edges:
        G.add_edge(n1, n2, **data)
    sg.graph = G
    sg._node_positions = positions
    return sg


# ---------------------------------------------------------------------------
# StreetGraph.to_polylines() — empty/None graph
# ---------------------------------------------------------------------------

class TestToPolylinesEmpty:
    """to_polylines() behavior when graph is None or empty."""

    def test_none_graph_returns_empty_list(self) -> None:
        sg = StreetGraph()
        assert sg.graph is None
        result = sg.to_polylines()
        assert result == []

    def test_empty_graph_returns_empty_list(self) -> None:
        sg = StreetGraph()
        sg.graph = nx.Graph()
        sg._node_positions = {}
        result = sg.to_polylines()
        assert result == []


# ---------------------------------------------------------------------------
# StreetGraph.to_polylines() — single edge
# ---------------------------------------------------------------------------

class TestToPolylinesSingleEdge:
    """to_polylines() with a simple two-node, one-edge graph."""

    def test_single_edge_produces_one_polyline(self) -> None:
        sg = _make_street_graph(
            edges=[(0, 1, {"weight": 10.0, "road_class": "residential"})],
            positions={0: (0.0, 0.0), 1: (10.0, 0.0)},
        )
        result = sg.to_polylines()
        assert len(result) == 1

    def test_single_edge_has_two_points(self) -> None:
        sg = _make_street_graph(
            edges=[(0, 1, {"weight": 10.0, "road_class": "residential"})],
            positions={0: (0.0, 0.0), 1: (10.0, 0.0)},
        )
        line = sg.to_polylines()[0]
        assert len(line["points"]) == 2

    def test_single_edge_point_values(self) -> None:
        sg = _make_street_graph(
            edges=[(0, 1, {"weight": 10.0, "road_class": "residential"})],
            positions={0: (5.0, 3.0), 1: (15.0, 7.0)},
        )
        line = sg.to_polylines()[0]
        # Points are lists (not tuples) — the source does list(p1), list(p2)
        assert line["points"][0] == [5.0, 3.0]
        assert line["points"][1] == [15.0, 7.0]

    def test_single_edge_road_class(self) -> None:
        sg = _make_street_graph(
            edges=[(0, 1, {"weight": 10.0, "road_class": "secondary"})],
            positions={0: (0.0, 0.0), 1: (10.0, 0.0)},
        )
        line = sg.to_polylines()[0]
        assert line["class"] == "secondary"

    def test_missing_road_class_defaults_to_residential(self) -> None:
        """When edge has no road_class data, default to 'residential'."""
        sg = _make_street_graph(
            edges=[(0, 1, {"weight": 10.0})],
            positions={0: (0.0, 0.0), 1: (10.0, 0.0)},
        )
        line = sg.to_polylines()[0]
        assert line["class"] == "residential"


# ---------------------------------------------------------------------------
# StreetGraph.to_polylines() — multi-edge graph
# ---------------------------------------------------------------------------

class TestToPolylinesMultiEdge:
    """to_polylines() with multiple edges and road classes."""

    def _build_three_edge_graph(self) -> StreetGraph:
        """Build a simple 4-node chain: 0--1--2--3 with different road classes."""
        return _make_street_graph(
            edges=[
                (0, 1, {"weight": 10.0, "road_class": "residential"}),
                (1, 2, {"weight": 15.0, "road_class": "secondary"}),
                (2, 3, {"weight": 8.0, "road_class": "service"}),
            ],
            positions={
                0: (0.0, 0.0),
                1: (10.0, 0.0),
                2: (25.0, 0.0),
                3: (33.0, 0.0),
            },
        )

    def test_edge_count_matches_polyline_count(self) -> None:
        sg = self._build_three_edge_graph()
        result = sg.to_polylines()
        assert len(result) == 3

    def test_all_road_classes_present(self) -> None:
        sg = self._build_three_edge_graph()
        result = sg.to_polylines()
        classes = {line["class"] for line in result}
        assert classes == {"residential", "secondary", "service"}

    def test_each_polyline_has_two_points(self) -> None:
        sg = self._build_three_edge_graph()
        for line in sg.to_polylines():
            assert len(line["points"]) == 2

    def test_branching_graph(self) -> None:
        """Graph with a junction: node 1 connects to 0, 2, and 3."""
        sg = _make_street_graph(
            edges=[
                (0, 1, {"weight": 10.0, "road_class": "residential"}),
                (1, 2, {"weight": 12.0, "road_class": "residential"}),
                (1, 3, {"weight": 8.0, "road_class": "footway"}),
            ],
            positions={
                0: (0.0, 0.0),
                1: (10.0, 0.0),
                2: (20.0, 5.0),
                3: (10.0, -8.0),
            },
        )
        result = sg.to_polylines()
        assert len(result) == 3

    def test_various_road_types(self) -> None:
        """All common OSM road types are preserved in output."""
        road_types = [
            "motorway", "trunk", "primary", "secondary", "tertiary",
            "residential", "service", "living_street", "pedestrian",
            "footway", "cycleway", "path",
        ]
        edges = []
        positions = {}
        for i, rtype in enumerate(road_types):
            n1 = i * 2
            n2 = i * 2 + 1
            edges.append((n1, n2, {"weight": 5.0, "road_class": rtype}))
            positions[n1] = (float(i * 10), 0.0)
            positions[n2] = (float(i * 10 + 5), 0.0)

        sg = _make_street_graph(edges=edges, positions=positions)
        result = sg.to_polylines()
        assert len(result) == len(road_types)
        output_classes = {line["class"] for line in result}
        assert output_classes == set(road_types)


# ---------------------------------------------------------------------------
# StreetGraph.to_polylines() — edge cases
# ---------------------------------------------------------------------------

class TestToPolylinesEdgeCases:
    """Edge cases in to_polylines()."""

    def test_node_missing_from_positions(self) -> None:
        """If a node has no position, its edge is skipped."""
        sg = StreetGraph()
        G = nx.Graph()
        G.add_node(0, x=0.0, y=0.0)
        G.add_node(1, x=10.0, y=0.0)
        G.add_node(2, x=20.0, y=0.0)
        G.add_edge(0, 1, weight=10.0, road_class="residential")
        G.add_edge(1, 2, weight=10.0, road_class="residential")
        sg.graph = G
        # Only give positions for nodes 0 and 1, not 2
        sg._node_positions = {0: (0.0, 0.0), 1: (10.0, 0.0)}
        result = sg.to_polylines()
        # Edge (1,2) should be skipped because node 2 has no position
        assert len(result) == 1

    def test_negative_coordinates(self) -> None:
        """Negative local coordinates are handled correctly."""
        sg = _make_street_graph(
            edges=[(0, 1, {"weight": 14.14, "road_class": "residential"})],
            positions={0: (-5.0, -3.0), 1: (5.0, 7.0)},
        )
        result = sg.to_polylines()
        assert result[0]["points"][0] == [-5.0, -3.0]

    def test_self_loop_excluded(self) -> None:
        """A self-loop edge (n1==n2) is skipped by NetworkX iteration but
        if somehow present, both points would be the same node position.
        This test verifies no crash occurs."""
        sg = StreetGraph()
        G = nx.Graph()
        G.add_node(0, x=0.0, y=0.0)
        G.add_node(1, x=10.0, y=0.0)
        G.add_edge(0, 1, weight=10.0, road_class="residential")
        # NetworkX undirected graph ignores self-loops by default
        G.add_edge(0, 0, weight=0.0, road_class="residential")
        sg.graph = G
        sg._node_positions = {0: (0.0, 0.0), 1: (10.0, 0.0)}
        result = sg.to_polylines()
        # Self-loop may or may not appear; just verify no crash
        assert isinstance(result, list)

    def test_polyline_dict_keys(self) -> None:
        """Each polyline dict has exactly 'points' and 'class' keys."""
        sg = _make_street_graph(
            edges=[(0, 1, {"weight": 10.0, "road_class": "residential"})],
            positions={0: (0.0, 0.0), 1: (10.0, 0.0)},
        )
        line = sg.to_polylines()[0]
        assert set(line.keys()) == {"points", "class"}


# ---------------------------------------------------------------------------
# BuildingObstacles.load_from_overture()
# ---------------------------------------------------------------------------

class TestLoadFromOverture:
    """BuildingObstacles.load_from_overture() polygon ingestion."""

    def test_loads_valid_polygons(self) -> None:
        obs = BuildingObstacles()
        data = [
            {"polygon": [(0, 0), (10, 0), (10, 10), (0, 10)]},
            {"polygon": [(20, 20), (30, 20), (30, 30)]},
        ]
        obs.load_from_overture(data)
        assert len(obs.polygons) == 2

    def test_polygon_converted_to_tuples(self) -> None:
        """Input coordinates are converted to (x, y) tuples."""
        obs = BuildingObstacles()
        obs.load_from_overture([{"polygon": [(1.5, 2.5), (3.5, 4.5), (5.5, 6.5)]}])
        assert obs.polygons[0][0] == (1.5, 2.5)
        assert obs.polygons[0][1] == (3.5, 4.5)
        assert obs.polygons[0][2] == (5.5, 6.5)

    def test_skips_polygon_with_fewer_than_3_points(self) -> None:
        """Polygons with < 3 points are invalid and should be skipped."""
        obs = BuildingObstacles()
        data = [
            {"polygon": [(0, 0), (10, 0)]},  # 2 points — invalid
            {"polygon": [(0, 0)]},  # 1 point — invalid
            {"polygon": []},  # empty — invalid
            {"polygon": [(0, 0), (5, 0), (5, 5)]},  # 3 points — valid
        ]
        obs.load_from_overture(data)
        assert len(obs.polygons) == 1

    def test_missing_polygon_key_skipped(self) -> None:
        """Dicts without a 'polygon' key produce an empty list, which is < 3."""
        obs = BuildingObstacles()
        obs.load_from_overture([{"no_polygon_here": True}])
        assert len(obs.polygons) == 0

    def test_empty_input_list(self) -> None:
        obs = BuildingObstacles()
        obs.load_from_overture([])
        assert obs.polygons == []

    def test_replaces_existing_polygons(self) -> None:
        """Calling load_from_overture replaces any previously loaded data."""
        obs = BuildingObstacles()
        obs.polygons = [[(0, 0), (1, 0), (1, 1)]]
        obs.load_from_overture([{"polygon": [(10, 10), (20, 10), (20, 20)]}])
        assert len(obs.polygons) == 1
        assert obs.polygons[0][0] == (10, 10)

    def test_accepts_list_coordinates(self) -> None:
        """Input can use lists instead of tuples for coordinate pairs."""
        obs = BuildingObstacles()
        obs.load_from_overture([{"polygon": [[0, 0], [5, 0], [5, 5]]}])
        assert len(obs.polygons) == 1
        # Coordinates are converted to tuples internally
        assert obs.polygons[0][0] == (0, 0)

    def test_large_polygon(self) -> None:
        """A polygon with many vertices is accepted."""
        # Approximate a circle with 100 vertices
        import math
        poly = [
            (10 * math.cos(2 * math.pi * i / 100),
             10 * math.sin(2 * math.pi * i / 100))
            for i in range(100)
        ]
        obs = BuildingObstacles()
        obs.load_from_overture([{"polygon": poly}])
        assert len(obs.polygons) == 1
        assert len(obs.polygons[0]) == 100

    def test_height_key_ignored_by_loader(self) -> None:
        """load_from_overture only reads 'polygon', ignores other keys."""
        obs = BuildingObstacles()
        obs.load_from_overture([
            {"polygon": [(0, 0), (5, 0), (5, 5)], "height": 15.0, "name": "HQ"},
        ])
        assert len(obs.polygons) == 1


# ---------------------------------------------------------------------------
# BuildingObstacles.to_dicts()
# ---------------------------------------------------------------------------

class TestToDicts:
    """BuildingObstacles.to_dicts() serialization."""

    def test_empty_polygons(self) -> None:
        obs = BuildingObstacles()
        assert obs.to_dicts() == []

    def test_single_polygon_structure(self) -> None:
        obs = BuildingObstacles()
        obs.polygons = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
        result = obs.to_dicts()
        assert len(result) == 1
        assert "polygon" in result[0]
        assert "height" in result[0]

    def test_polygon_points_are_lists(self) -> None:
        """Polygon points are serialized as [x, y] lists, not tuples."""
        obs = BuildingObstacles()
        obs.polygons = [[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]]
        result = obs.to_dicts()
        for pt in result[0]["polygon"]:
            assert isinstance(pt, list)
            assert len(pt) == 2

    def test_polygon_coordinate_values(self) -> None:
        obs = BuildingObstacles()
        obs.polygons = [[(1.5, 2.5), (3.5, 4.5), (5.5, 6.5)]]
        result = obs.to_dicts()
        assert result[0]["polygon"][0] == [1.5, 2.5]
        assert result[0]["polygon"][1] == [3.5, 4.5]
        assert result[0]["polygon"][2] == [5.5, 6.5]

    def test_default_height_is_8(self) -> None:
        obs = BuildingObstacles()
        obs.polygons = [[(0, 0), (5, 0), (5, 5)]]
        result = obs.to_dicts()
        assert result[0]["height"] == 8.0

    def test_custom_default_height(self) -> None:
        obs = BuildingObstacles()
        obs.polygons = [[(0, 0), (5, 0), (5, 5)]]
        result = obs.to_dicts(default_height=12.0)
        assert result[0]["height"] == 12.0

    def test_zero_height(self) -> None:
        obs = BuildingObstacles()
        obs.polygons = [[(0, 0), (5, 0), (5, 5)]]
        result = obs.to_dicts(default_height=0.0)
        assert result[0]["height"] == 0.0

    def test_multiple_polygons(self) -> None:
        obs = BuildingObstacles()
        obs.polygons = [
            [(0, 0), (10, 0), (10, 10)],
            [(20, 20), (30, 20), (30, 30), (20, 30)],
            [(50, 50), (60, 50), (55, 60)],
        ]
        result = obs.to_dicts()
        assert len(result) == 3
        # All share the same default height
        assert all(d["height"] == 8.0 for d in result)
        # Polygon vertex counts preserved
        assert len(result[0]["polygon"]) == 3
        assert len(result[1]["polygon"]) == 4
        assert len(result[2]["polygon"]) == 3

    def test_dict_keys(self) -> None:
        """Each dict has exactly 'polygon' and 'height' keys."""
        obs = BuildingObstacles()
        obs.polygons = [[(0, 0), (5, 0), (5, 5)]]
        result = obs.to_dicts()
        assert set(result[0].keys()) == {"polygon", "height"}


# ---------------------------------------------------------------------------
# Round-trip: load_from_overture -> to_dicts
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Verify data survives a load -> serialize round-trip."""

    def test_roundtrip_preserves_polygon_count(self) -> None:
        input_data = [
            {"polygon": [(0, 0), (10, 0), (10, 10), (0, 10)]},
            {"polygon": [(20, 20), (30, 20), (30, 30)]},
        ]
        obs = BuildingObstacles()
        obs.load_from_overture(input_data)
        output = obs.to_dicts()
        assert len(output) == 2

    def test_roundtrip_preserves_coordinates(self) -> None:
        input_data = [{"polygon": [(1.5, 2.5), (3.5, 4.5), (5.5, 6.5)]}]
        obs = BuildingObstacles()
        obs.load_from_overture(input_data)
        output = obs.to_dicts()
        assert output[0]["polygon"] == [[1.5, 2.5], [3.5, 4.5], [5.5, 6.5]]

    def test_roundtrip_filters_invalid(self) -> None:
        """Invalid polygons are dropped during load, not during to_dicts."""
        input_data = [
            {"polygon": [(0, 0), (10, 0)]},  # invalid — 2 points
            {"polygon": [(0, 0), (10, 0), (10, 10)]},  # valid
        ]
        obs = BuildingObstacles()
        obs.load_from_overture(input_data)
        output = obs.to_dicts()
        assert len(output) == 1

    def test_roundtrip_with_custom_height(self) -> None:
        input_data = [{"polygon": [(0, 0), (5, 0), (5, 5)]}]
        obs = BuildingObstacles()
        obs.load_from_overture(input_data)
        output = obs.to_dicts(default_height=20.0)
        assert output[0]["height"] == 20.0

    def test_double_load_replaces(self) -> None:
        """A second load_from_overture call fully replaces the first."""
        obs = BuildingObstacles()
        obs.load_from_overture([{"polygon": [(0, 0), (5, 0), (5, 5)]}])
        assert len(obs.polygons) == 1
        obs.load_from_overture([
            {"polygon": [(10, 10), (20, 10), (20, 20)]},
            {"polygon": [(30, 30), (40, 30), (40, 40)]},
        ])
        assert len(obs.polygons) == 2
        output = obs.to_dicts()
        assert len(output) == 2
        # First polygon should be the new one, not the old
        assert output[0]["polygon"][0] == [10, 10]
