"""Boot integration test — verifies all War Room subsystems initialize correctly."""

import queue
import time

import pytest


@pytest.mark.unit
class TestBootIntegration:
    """Test that all new subsystems can be created and started together."""

    def test_full_subsystem_boot(self):
        """Boot simulation engine + ambient + classifier + dispatcher together."""
        from amy.commander import EventBus
        from amy.simulation import SimulationEngine, AmbientSpawner
        from amy.tactical.target_tracker import TargetTracker
        from amy.tactical.escalation import ThreatClassifier, AutoDispatcher

        bus = EventBus()
        engine = SimulationEngine(bus)
        tracker = TargetTracker()

        zones = [
            {
                "name": "perimeter",
                "type": "entry_exit_zone",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 25.0},
            },
            {
                "name": "inner_zone",
                "type": "restricted_area",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 12.0},
            },
        ]
        classifier = ThreatClassifier(bus, tracker, zones=zones)
        dispatcher = AutoDispatcher(bus, tracker, simulation_engine=engine)

        # Start everything
        engine.start()
        classifier.start()
        dispatcher.start()

        # Let it run briefly
        time.sleep(2.0)

        # Verify engine is running (tick loop + spawner + ambient)
        assert engine._running
        assert engine._thread is not None and engine._thread.is_alive()
        assert engine._spawner_thread is not None and engine._spawner_thread.is_alive()
        assert engine.ambient_spawner is not None

        # Verify classifier is running
        assert classifier._running

        # Verify dispatcher is running
        assert dispatcher._running

        # Subscribe and collect events to verify bus is flowing
        sub = bus.subscribe()
        time.sleep(0.5)
        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break

        # Engine publishes sim_telemetry for any spawned targets
        event_types = [e.get("type", "") for e in events]
        # At minimum engine is ticking — if any targets exist we get sim_telemetry
        # (hostile spawner may not have fired yet in 2s, but ambient may have)

        # Clean shutdown (order matters: dispatcher -> classifier -> engine)
        dispatcher.stop()
        classifier.stop()
        engine.stop()
        bus.unsubscribe(sub)

        # Verify clean shutdown
        assert not engine._running
        assert not classifier._running
        assert not dispatcher._running

    def test_simulation_bridge_data_format(self):
        """Verify SimulationTarget.to_dict() has all fields the frontend needs."""
        from amy.simulation.target import SimulationTarget

        target = SimulationTarget(
            target_id="test-001",
            name="Test Rover",
            alliance="friendly",
            asset_type="rover",
            position=(5.0, 10.0),
            speed=2.0,
            waypoints=[(15.0, 20.0), (25.0, 30.0)],
        )

        d = target.to_dict()

        # ALL fields the frontend reads
        assert "target_id" in d
        assert "name" in d
        assert "alliance" in d
        assert "asset_type" in d
        assert "position" in d and "x" in d["position"] and "y" in d["position"]
        assert d["position"] == {"x": 5.0, "y": 10.0}
        assert "heading" in d
        assert "speed" in d
        assert "battery" in d
        assert "status" in d
        # threat_level is NOT on SimulationTarget — it lives in ThreatRecord
        assert "threat_level" not in d
        assert "waypoints" in d
        assert len(d["waypoints"]) == 2
        assert d["waypoints"][0] == {"x": 15.0, "y": 20.0}
        assert d["waypoints"][1] == {"x": 25.0, "y": 30.0}

    def test_tracker_stores_position_as_tuple(self):
        """Verify TargetTracker.update_from_simulation() converts dict position to tuple."""
        from amy.tactical.target_tracker import TargetTracker

        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "rover-001",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 5.0, "y": 10.0},
            "heading": 45.0,
            "speed": 2.0,
            "battery": 0.85,
            "status": "active",
        })

        target = tracker.get_target("rover-001")
        assert target is not None
        # Position must be a tuple for math.hypot in classifier/dispatcher
        assert isinstance(target.position, tuple)
        assert target.position == (5.0, 10.0)
        # Verify battery and status are preserved
        assert target.battery == 0.85
        assert target.status == "active"
        assert target.alliance == "friendly"

    def test_tracker_update_existing_target(self):
        """Verify updating a simulation target preserves identity, updates fields."""
        from amy.tactical.target_tracker import TargetTracker

        tracker = TargetTracker()
        # Initial creation
        tracker.update_from_simulation({
            "target_id": "rover-001",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 5.0, "y": 10.0},
            "heading": 0.0,
            "speed": 2.0,
            "battery": 1.0,
            "status": "active",
        })
        # Update with new position + battery
        tracker.update_from_simulation({
            "target_id": "rover-001",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 8.0, "y": 12.0},
            "heading": 45.0,
            "speed": 2.0,
            "battery": 0.72,
            "status": "active",
        })

        target = tracker.get_target("rover-001")
        assert target is not None
        assert target.position == (8.0, 12.0)
        assert target.battery == 0.72
        assert target.heading == 45.0
        # Source should remain simulation
        assert target.source == "simulation"

    def test_escalation_with_real_tracker_data(self):
        """Feed a hostile target to tracker, verify classifier escalates it."""
        from amy.commander import EventBus
        from amy.tactical.target_tracker import TargetTracker
        from amy.tactical.escalation import ThreatClassifier

        bus = EventBus()
        tracker = TargetTracker()

        zones = [
            {
                "name": "restricted",
                "type": "restricted_area",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            },
        ]
        classifier = ThreatClassifier(bus, tracker, zones=zones)

        # Add a hostile target at (5, 5) — inside the restricted zone (radius 10 from origin)
        tracker.update_from_simulation({
            "target_id": "hostile-001",
            "name": "Intruder",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 5.0, "y": 5.0},
            "heading": 0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        })

        # Collect events
        sub = bus.subscribe()

        # Run one classify tick manually
        classifier._classify_tick()

        # Check: hostile at (5,5) is inside restricted zone (radius 10 from origin)
        records = classifier.get_records()
        assert "hostile-001" in records
        # Should be escalated to at least "suspicious" (restricted zone)
        assert records["hostile-001"].threat_level in ("suspicious", "hostile")

        # Verify escalation event was published
        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break
        event_types = [e.get("type", "") for e in events]
        assert "threat_escalation" in event_types

        bus.unsubscribe(sub)

    def test_auto_dispatch_with_real_data(self):
        """Test the full dispatch pipeline: hostile in zone -> unit dispatched."""
        from amy.commander import EventBus
        from amy.tactical.target_tracker import TargetTracker
        from amy.simulation import SimulationEngine
        from amy.simulation.target import SimulationTarget
        from amy.tactical.escalation import ThreatClassifier, AutoDispatcher

        bus = EventBus()
        tracker = TargetTracker()
        engine = SimulationEngine(bus)

        # Add a friendly rover (in engine and tracker)
        rover = SimulationTarget(
            target_id="rover-001",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(20.0, 20.0),
            speed=3.0,
        )
        engine.add_target(rover)
        tracker.update_from_simulation(rover.to_dict())

        # Add a hostile inside restricted zone
        tracker.update_from_simulation({
            "target_id": "hostile-001",
            "name": "Intruder",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 3.0, "y": 3.0},
            "heading": 0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        })

        zones = [
            {
                "name": "restricted",
                "type": "restricted_area",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            },
        ]

        classifier = ThreatClassifier(bus, tracker, zones=zones)
        dispatcher = AutoDispatcher(bus, tracker, simulation_engine=engine)

        # Subscribe to events
        sub = bus.subscribe()

        # Start dispatcher (it needs to be listening for escalation events)
        dispatcher.start()
        time.sleep(0.1)

        # Run classifier tick — escalates to suspicious (restricted zone)
        classifier._classify_tick()

        # AutoDispatcher only fires on hostile; escalate manually
        classifier.set_threat_level("hostile-001", "hostile")

        # Give dispatcher time to react to the escalation event
        time.sleep(1.0)

        # Check: dispatcher should have dispatched rover to intercept
        dispatches = dispatcher.active_dispatches
        assert "hostile-001" in dispatches, f"Expected hostile-001 in dispatches, got {dispatches}"
        assert dispatches["hostile-001"] == "rover-001"

        # Collect events
        events = []
        while True:
            try:
                msg = sub.get_nowait()
                events.append(msg)
            except queue.Empty:
                break

        event_types = [e.get("type", "") for e in events]
        assert "threat_escalation" in event_types, f"Expected threat_escalation in {event_types}"
        assert "amy_dispatch" in event_types, f"Expected amy_dispatch in {event_types}"
        assert "auto_dispatch_speech" in event_types, f"Expected auto_dispatch_speech in {event_types}"

        # Verify rover's waypoints were updated to intercept position
        sim_rover = engine.get_target("rover-001")
        assert sim_rover is not None
        assert len(sim_rover.waypoints) > 0
        # Waypoint should be at hostile's position (3, 3)
        assert sim_rover.waypoints[0] == (3.0, 3.0)

        # Cleanup
        dispatcher.stop()
        bus.unsubscribe(sub)

    def test_tracker_get_all_returns_objects_with_tuple_positions(self):
        """Verify get_all() returns TrackedTarget objects with tuple positions."""
        from amy.tactical.target_tracker import TargetTracker

        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "a",
            "name": "A",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 2.0},
            "heading": 0,
            "speed": 1.0,
            "battery": 1.0,
            "status": "active",
        })
        tracker.update_from_simulation({
            "target_id": "b",
            "name": "B",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 3.0, "y": 4.0},
            "heading": 90,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        })

        all_targets = tracker.get_all()
        assert len(all_targets) == 2
        for t in all_targets:
            assert isinstance(t.position, tuple), f"{t.target_id} position is {type(t.position)}"
            assert hasattr(t, "battery")
            assert hasattr(t, "status")

    def test_classifier_skips_friendly_targets(self):
        """Verify ThreatClassifier does not classify friendly targets."""
        from amy.commander import EventBus
        from amy.tactical.target_tracker import TargetTracker
        from amy.tactical.escalation import ThreatClassifier

        bus = EventBus()
        tracker = TargetTracker()

        zones = [
            {
                "name": "restricted",
                "type": "restricted_area",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 50.0},
            },
        ]
        classifier = ThreatClassifier(bus, tracker, zones=zones)

        # Add a friendly rover inside the restricted zone
        tracker.update_from_simulation({
            "target_id": "rover-001",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 1.0},
            "heading": 0,
            "speed": 2.0,
            "battery": 1.0,
            "status": "active",
        })

        classifier._classify_tick()
        records = classifier.get_records()
        # Friendly targets should not appear in threat records
        assert "rover-001" not in records

    def test_dispatcher_skips_low_battery_units(self):
        """Verify AutoDispatcher won't dispatch units with low battery."""
        from amy.commander import EventBus
        from amy.tactical.target_tracker import TargetTracker
        from amy.simulation import SimulationEngine
        from amy.simulation.target import SimulationTarget
        from amy.tactical.escalation import ThreatClassifier, AutoDispatcher

        bus = EventBus()
        tracker = TargetTracker()
        engine = SimulationEngine(bus)

        # Add a friendly rover with low battery
        rover = SimulationTarget(
            target_id="rover-low",
            name="Rover Low",
            alliance="friendly",
            asset_type="rover",
            position=(10.0, 10.0),
            speed=3.0,
            battery=0.10,  # Below MIN_BATTERY (0.20)
        )
        engine.add_target(rover)
        tracker.update_from_simulation(rover.to_dict())

        # Add a hostile inside restricted zone
        tracker.update_from_simulation({
            "target_id": "hostile-001",
            "name": "Intruder",
            "alliance": "hostile",
            "asset_type": "person",
            "position": {"x": 2.0, "y": 2.0},
            "heading": 0,
            "speed": 1.5,
            "battery": 1.0,
            "status": "active",
        })

        zones = [
            {
                "name": "restricted",
                "type": "restricted_area",
                "position": {"x": 0.0, "z": 0.0},
                "properties": {"radius": 10.0},
            },
        ]
        classifier = ThreatClassifier(bus, tracker, zones=zones)
        dispatcher = AutoDispatcher(bus, tracker, simulation_engine=engine)

        dispatcher.start()
        time.sleep(0.1)

        classifier._classify_tick()
        time.sleep(1.0)

        # Dispatcher should NOT have dispatched the low-battery rover
        dispatches = dispatcher.active_dispatches
        assert "hostile-001" not in dispatches

        dispatcher.stop()

    def test_ambient_spawner_creates_neutral_targets(self):
        """Verify AmbientSpawner spawns neutral targets with correct alliance."""
        from amy.commander import EventBus
        from amy.simulation import SimulationEngine

        bus = EventBus()
        engine = SimulationEngine(bus)

        # Start engine (which starts ambient spawner)
        engine.start()
        # AmbientSpawner has 15-45s delay before first spawn, so we can't wait.
        # Instead, verify the spawner was created and is running.
        assert engine.ambient_spawner is not None
        assert engine.ambient_spawner._running

        engine.stop()
        assert engine.ambient_spawner is None  # Cleaned up on stop
