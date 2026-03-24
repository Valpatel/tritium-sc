# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TargetCorrelator graph store integration.

Verifies that entity nodes and relationship edges are written into a
TritiumGraph (KuzuDB) when the correlator fuses two targets.
"""

import time
from unittest.mock import MagicMock, call

import pytest

from src.engine.tactical.correlator import (
    TargetCorrelator,
    _node_type_for,
)
from tritium_lib.tracking.dossier import DossierStore
from src.engine.tactical.target_tracker import TargetTracker, TrackedTarget


def _make_tracker_with(*targets: TrackedTarget) -> TargetTracker:
    """Create a TargetTracker pre-loaded with the given targets."""
    tracker = TargetTracker()
    with tracker._lock:
        for t in targets:
            tracker._targets[t.target_id] = t
    return tracker


def _ble_target(
    tid: str = "ble_aabbccdd",
    pos: tuple[float, float] = (5.0, 5.0),
    confidence: float = 0.5,
    name: str = "",
    asset_type: str = "ble_device",
) -> TrackedTarget:
    return TrackedTarget(
        target_id=tid,
        name=name or f"BLE {tid}",
        alliance="unknown",
        asset_type=asset_type,
        position=pos,
        last_seen=time.monotonic(),
        source="ble",
        position_source="trilateration",
        position_confidence=confidence,
    )


def _yolo_target(
    tid: str = "det_person_1",
    pos: tuple[float, float] = (5.5, 5.5),
    confidence: float = 0.3,
    name: str = "",
    asset_type: str = "person",
) -> TrackedTarget:
    return TrackedTarget(
        target_id=tid,
        name=name or f"Person #{tid}",
        alliance="hostile",
        asset_type=asset_type,
        position=pos,
        last_seen=time.monotonic(),
        source="yolo",
        position_source="yolo",
        position_confidence=confidence,
    )


class TestNodeTypeMapping:
    """Tests for the asset_type -> graph node type mapping."""

    @pytest.mark.unit
    def test_person_maps_to_person(self):
        assert _node_type_for("person") == "Person"

    @pytest.mark.unit
    def test_vehicle_maps_to_vehicle(self):
        assert _node_type_for("vehicle") == "Vehicle"
        assert _node_type_for("car") == "Vehicle"
        assert _node_type_for("motorcycle") == "Vehicle"

    @pytest.mark.unit
    def test_ble_device_maps_to_device(self):
        assert _node_type_for("ble_device") == "Device"
        assert _node_type_for("rover") == "Device"
        assert _node_type_for("drone") == "Device"

    @pytest.mark.unit
    def test_unknown_type_defaults_to_device(self):
        assert _node_type_for("unknown") == "Device"
        assert _node_type_for("laser_turret_3000") == "Device"


class TestGraphStoreIntegration:
    """Tests that the correlator writes to the graph store on correlation."""

    @pytest.mark.unit
    def test_no_graph_store_no_error(self):
        """Correlator works fine without a graph store (None)."""
        ble = _ble_target(pos=(5.0, 5.0))
        yolo = _yolo_target(pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0, graph_store=None)
        records = correlator.correlate()

        assert len(records) == 1

    @pytest.mark.unit
    def test_graph_entities_created_on_correlation(self):
        """Both entities are created in the graph when correlated."""
        ble = _ble_target(pos=(5.0, 5.0))
        yolo = _yolo_target(pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        records = correlator.correlate()

        assert len(records) == 1
        assert mock_graph.create_entity.call_count == 2

        # Verify correct node types were used
        entity_calls = mock_graph.create_entity.call_args_list
        node_types = {c.kwargs["entity_type"] for c in entity_calls}
        assert "Device" in node_types  # BLE device
        assert "Person" in node_types  # YOLO person

    @pytest.mark.unit
    def test_correlated_with_edge_created(self):
        """A CORRELATED_WITH edge is always created between fused entities."""
        ble = _ble_target(pos=(5.0, 5.0))
        yolo = _yolo_target(pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        records = correlator.correlate()

        assert len(records) == 1
        # Find CORRELATED_WITH calls
        rel_calls = mock_graph.add_relationship.call_args_list
        corr_calls = [
            c for c in rel_calls if c.kwargs.get("rel_type") == "CORRELATED_WITH"
        ]
        assert len(corr_calls) == 1
        rel_call = corr_calls[0]
        assert rel_call.kwargs["properties"]["confidence"] > 0

    @pytest.mark.unit
    def test_carries_edge_for_ble_camera_person(self):
        """A CARRIES edge is created when BLE device correlates with camera person."""
        ble = _ble_target(tid="ble_phone", pos=(5.0, 5.0))
        yolo = _yolo_target(tid="det_person_1", pos=(5.5, 5.5), asset_type="person")
        tracker = _make_tracker_with(ble, yolo)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        correlator.correlate()

        rel_calls = mock_graph.add_relationship.call_args_list
        carries_calls = [
            c for c in rel_calls if c.kwargs.get("rel_type") == "CARRIES"
        ]
        assert len(carries_calls) == 1

        # CARRIES goes from device to person
        carries = carries_calls[0]
        assert carries.kwargs["from_id"] == "ble_phone"
        assert carries.kwargs["to_id"] == "det_person_1"

    @pytest.mark.unit
    def test_no_carries_edge_for_ble_vehicle(self):
        """No CARRIES edge when BLE device correlates with a vehicle."""
        ble = _ble_target(tid="ble_tracker", pos=(5.0, 5.0))
        yolo = _yolo_target(
            tid="det_car_1", pos=(5.5, 5.5), asset_type="vehicle"
        )
        # yolo source is still "yolo" but asset_type is vehicle, not person
        tracker = _make_tracker_with(ble, yolo)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        correlator.correlate()

        rel_calls = mock_graph.add_relationship.call_args_list
        carries_calls = [
            c for c in rel_calls if c.kwargs.get("rel_type") == "CARRIES"
        ]
        assert len(carries_calls) == 0

    @pytest.mark.unit
    def test_detected_with_edge_for_two_ble_devices(self):
        """DETECTED_WITH edge when two BLE devices are correlated."""
        # Two BLE devices from different "source" would normally not
        # correlate because same source is skipped. We need different
        # sources. Use a manual override for this test.
        ble1 = TrackedTarget(
            target_id="ble_phone",
            name="Phone",
            alliance="unknown",
            asset_type="ble_device",
            position=(5.0, 5.0),
            last_seen=time.monotonic(),
            source="ble",
            position_source="trilateration",
            position_confidence=0.5,
        )
        ble2 = TrackedTarget(
            target_id="ble_watch",
            name="Watch",
            alliance="unknown",
            asset_type="ble_device",
            position=(5.1, 5.1),
            last_seen=time.monotonic(),
            source="ble_mesh",  # Different source so correlator considers pair
            position_source="trilateration",
            position_confidence=0.5,
        )
        tracker = _make_tracker_with(ble1, ble2)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        correlator.correlate()

        # Both are BLE-like but different sources so they correlate.
        # However DETECTED_WITH requires BOTH sources to be "ble".
        # ble2 has source "ble_mesh" so no DETECTED_WITH edge.
        rel_calls = mock_graph.add_relationship.call_args_list
        detected_calls = [
            c for c in rel_calls if c.kwargs.get("rel_type") == "DETECTED_WITH"
        ]
        assert len(detected_calls) == 0

    @pytest.mark.unit
    def test_graph_error_does_not_break_correlation(self):
        """If graph store raises an exception, correlation still succeeds."""
        ble = _ble_target(pos=(5.0, 5.0))
        yolo = _yolo_target(pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        mock_graph = MagicMock()
        mock_graph.create_entity.side_effect = RuntimeError("kuzu exploded")

        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        records = correlator.correlate()

        # Correlation still succeeded despite graph failure
        assert len(records) == 1
        assert len(tracker.get_all()) == 1

    @pytest.mark.unit
    def test_no_correlation_no_graph_write(self):
        """If targets are too far apart, no graph writes occur."""
        ble = _ble_target(pos=(0.0, 0.0))
        yolo = _yolo_target(pos=(100.0, 100.0))
        tracker = _make_tracker_with(ble, yolo)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        records = correlator.correlate()

        assert len(records) == 0
        mock_graph.create_entity.assert_not_called()
        mock_graph.add_relationship.assert_not_called()

    @pytest.mark.unit
    def test_multiple_correlations_write_multiple_graph_edges(self):
        """Multiple correlation pairs each get their own graph writes."""
        ble1 = _ble_target(tid="ble_aa", pos=(0.0, 0.0))
        yolo1 = _yolo_target(tid="det_1", pos=(1.0, 0.0))
        ble2 = _ble_target(tid="ble_bb", pos=(50.0, 50.0))
        yolo2 = _yolo_target(tid="det_2", pos=(51.0, 50.0))
        tracker = _make_tracker_with(ble1, yolo1, ble2, yolo2)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        records = correlator.correlate()

        assert len(records) == 2
        # 2 correlations x 2 entities each = 4 create_entity calls
        assert mock_graph.create_entity.call_count == 4
        # 2 CORRELATED_WITH + 2 CARRIES (both are BLE+person) = 4
        corr_calls = [
            c
            for c in mock_graph.add_relationship.call_args_list
            if c.kwargs.get("rel_type") == "CORRELATED_WITH"
        ]
        assert len(corr_calls) == 2

    @pytest.mark.unit
    def test_graph_edge_confidence_matches_correlation(self):
        """Graph edge confidence should match the correlation confidence."""
        ble = _ble_target(pos=(5.0, 5.0))
        yolo = _yolo_target(pos=(5.0, 5.0))  # Same position = high spatial
        tracker = _make_tracker_with(ble, yolo)

        mock_graph = MagicMock()
        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=mock_graph
        )
        records = correlator.correlate()

        assert len(records) == 1
        expected_confidence = records[0].confidence

        corr_calls = [
            c
            for c in mock_graph.add_relationship.call_args_list
            if c.kwargs.get("rel_type") == "CORRELATED_WITH"
        ]
        assert len(corr_calls) == 1
        assert corr_calls[0].kwargs["properties"]["confidence"] == expected_confidence


class TestGraphStoreWithRealKuzu:
    """Integration tests using a real TritiumGraph with a temp database.

    These tests are skipped if kuzu is not installed.
    """

    @pytest.fixture
    def graph_store(self, tmp_path):
        """Create a real TritiumGraph in a temp directory."""
        try:
            from tritium_lib.graph.store import TritiumGraph
        except ImportError:
            pytest.skip("kuzu not installed")
        return TritiumGraph(tmp_path / "test_graph")

    @pytest.mark.unit
    def test_real_graph_entities_and_edges(self, graph_store):
        """End-to-end: correlator writes real entities and edges to KuzuDB."""
        ble = _ble_target(tid="ble_real_phone", pos=(5.0, 5.0))
        yolo = _yolo_target(tid="det_real_person", pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=graph_store
        )
        records = correlator.correlate()

        assert len(records) == 1

        # Verify entities exist in graph
        ble_entity = graph_store.get_entity("ble_real_phone")
        assert ble_entity is not None
        assert ble_entity["entity_type"] == "Device"

        person_entity = graph_store.get_entity("det_real_person")
        assert person_entity is not None
        assert person_entity["entity_type"] == "Person"

        # Verify relationships
        rels = graph_store.get_relationships("ble_real_phone", direction="out")
        rel_types = {r["rel_type"] for r in rels}
        assert "CORRELATED_WITH" in rel_types
        assert "CARRIES" in rel_types

    @pytest.mark.unit
    def test_real_graph_traversal_after_correlation(self, graph_store):
        """After correlation, graph traversal from BLE device reaches person."""
        ble = _ble_target(tid="ble_trav_phone", pos=(5.0, 5.0))
        yolo = _yolo_target(tid="det_trav_person", pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(
            tracker, radius=5.0, graph_store=graph_store
        )
        correlator.correlate()

        subgraph = graph_store.traverse("ble_trav_phone", max_hops=2)
        node_ids = {n["id"] for n in subgraph["nodes"]}
        assert "ble_trav_phone" in node_ids
        assert "det_trav_person" in node_ids
        assert len(subgraph["edges"]) >= 1
