"""FakeRobotAdapter — bridges FakeRobot to the MQTT pipeline without a real broker.

Provides bidirectional in-process message routing:
  - Outbound: FakeRobot.get_telemetry() -> callback (simulating MQTT publish)
  - Inbound: receive_command() -> FakeRobot.receive_command()

FakeRobotFleetAdapter manages multiple adapters for integration testing.

Usage:
    from engine.simulation.robot_adapter import FakeRobotAdapter, FakeRobotFleetAdapter

    # Single robot
    adapter = FakeRobotAdapter.create(robot_id="rover-01", asset_type="rover")
    adapter.connect_to_bridge(mqtt_bridge)  # wires into MQTTBridge._on_robot_telemetry
    adapter.tick(0.1)                       # advances robot, auto-publishes telemetry

    # Fleet
    fleet = FakeRobotFleetAdapter()
    fleet.add_robot("rover-01")
    fleet.add_robot("drone-01", robot_type="drone")
    fleet.connect_to_bridge(mqtt_bridge)
    fleet.tick_all(0.1)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from engine.simulation.fake_robot import FakeRobot

if TYPE_CHECKING:
    from engine.comms.mqtt_bridge import MQTTBridge


class FakeRobotAdapter:
    """Wraps a FakeRobot and provides bidirectional message passing.

    Does NOT require a real MQTT broker. Uses in-process callbacks to
    simulate the telemetry publish / command receive cycle.
    """

    def __init__(
        self,
        robot: FakeRobot,
        telemetry_interval: float = 1.0,
    ) -> None:
        self._robot = robot
        self.telemetry_interval: float = telemetry_interval
        self._accumulated_time: float = 0.0

        # Telemetry callback: (robot_id, telemetry_dict) -> None
        # Set by connect_to_bridge() or manually for testing.
        self.on_telemetry: Callable[[str, dict], None] | None = None

    @classmethod
    def create(cls, robot_id: str, **kwargs) -> FakeRobotAdapter:
        """Factory: create an adapter with a new FakeRobot inline.

        Args:
            robot_id: Robot identifier.
            **kwargs: Passed to FakeRobot constructor (asset_type, lat, lng, etc.).

        Returns:
            A new FakeRobotAdapter wrapping the created FakeRobot.
        """
        # Map robot_type -> asset_type if provided
        if "robot_type" in kwargs:
            kwargs["asset_type"] = kwargs.pop("robot_type")
        robot = FakeRobot(robot_id=robot_id, **kwargs)
        return cls(robot)

    @property
    def robot(self) -> FakeRobot:
        """The underlying FakeRobot."""
        return self._robot

    @property
    def robot_id(self) -> str:
        """Robot identifier."""
        return self._robot.robot_id

    def publish_telemetry(self) -> dict:
        """Get current telemetry and route it to the callback.

        Returns:
            The telemetry dict (same format as FakeRobot.get_telemetry()).
        """
        telem = self._robot.get_telemetry()
        if self.on_telemetry is not None:
            self.on_telemetry(self._robot.robot_id, telem)
        return telem

    def receive_command(self, command: str, params: dict | None = None) -> None:
        """Route a command to the underlying FakeRobot.

        Args:
            command: "dispatch", "patrol", or "recall".
            params: Command parameters (lat/lng for dispatch, waypoints for patrol).
        """
        self._robot.receive_command(command, params)

    def tick(self, dt: float) -> dict:
        """Advance the FakeRobot and auto-publish telemetry at interval.

        Args:
            dt: Time step in seconds.

        Returns:
            The telemetry dict from FakeRobot.tick().
        """
        telem = self._robot.tick(dt)

        # Accumulate time and auto-publish when interval reached.
        # Use small epsilon (1e-9) to handle floating-point accumulation
        # (e.g. 0.1 added 10 times = 0.9999999999999999, not 1.0).
        self._accumulated_time += dt
        if self._accumulated_time >= self.telemetry_interval - 1e-9:
            self._accumulated_time -= self.telemetry_interval
            if self.on_telemetry is not None:
                self.on_telemetry(self._robot.robot_id, telem)

        return telem

    def connect_to_bridge(self, bridge: MQTTBridge) -> None:
        """Wire this adapter into an MQTTBridge's inbound telemetry handler.

        After calling this, publish_telemetry() and tick()'s auto-publish
        will call bridge._on_robot_telemetry() directly, bypassing actual
        MQTT network transport.

        Args:
            bridge: The MQTTBridge to connect to.
        """
        self.on_telemetry = lambda robot_id, data: bridge._on_robot_telemetry(
            robot_id, data
        )


class FakeRobotFleetAdapter:
    """Manages multiple FakeRobotAdapters for fleet integration testing."""

    def __init__(self) -> None:
        self._adapters: dict[str, FakeRobotAdapter] = {}

    def add_robot(
        self,
        robot_id: str,
        robot_type: str = "rover",
        **kwargs,
    ) -> FakeRobotAdapter:
        """Create and track a new fake robot adapter.

        Args:
            robot_id: Robot identifier.
            robot_type: Asset type (rover, drone, etc.).
            **kwargs: Passed to FakeRobot (lat, lng, battery, etc.).

        Returns:
            The created FakeRobotAdapter.
        """
        adapter = FakeRobotAdapter.create(
            robot_id=robot_id,
            robot_type=robot_type,
            **kwargs,
        )
        self._adapters[robot_id] = adapter
        return adapter

    def tick_all(self, dt: float) -> list[dict]:
        """Tick all robots and return telemetry list.

        Args:
            dt: Time step in seconds.

        Returns:
            List of telemetry dicts, one per robot.
        """
        return [adapter.tick(dt) for adapter in self._adapters.values()]

    def dispatch(self, robot_id: str, lat: float = 0.0, lng: float = 0.0) -> None:
        """Send dispatch command to a specific robot.

        Args:
            robot_id: Target robot ID.
            lat: Destination latitude.
            lng: Destination longitude.
        """
        adapter = self._adapters.get(robot_id)
        if adapter is not None:
            adapter.receive_command("dispatch", {"lat": lat, "lng": lng})

    def get_adapter(self, robot_id: str) -> FakeRobotAdapter | None:
        """Get adapter by robot ID, or None if not found."""
        return self._adapters.get(robot_id)

    def connect_to_bridge(self, bridge: MQTTBridge) -> None:
        """Wire all fleet robots into the given MQTTBridge.

        Args:
            bridge: The MQTTBridge to connect all adapters to.
        """
        for adapter in self._adapters.values():
            adapter.connect_to_bridge(bridge)

    def __len__(self) -> int:
        return len(self._adapters)
