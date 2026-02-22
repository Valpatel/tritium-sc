"""ScenarioRunner — creates Commander + SyntheticNode, runs a scenario end-to-end."""

from __future__ import annotations

import tempfile
import threading
import time
import uuid

from .schema import Scenario, ScenarioResult, ScenarioScore
from .synthetic_node import SyntheticSensorNode
from .recorder import ActionRecorder
from .scorer import Scorer


class ScenarioRunner:
    """Runs a scenario through Amy's full Commander pipeline.

    Creates a SyntheticSensorNode from the scenario, wires it into a
    Commander with fast timing params, records all actions, and scores
    the results.
    """

    def __init__(
        self,
        scenario: Scenario,
        chat_model: str = "gemma3:4b",
        deep_model: str = "llava:7b",
        system_prompt_override: str | None = None,
        use_listener: bool = False,
    ):
        self._scenario = scenario
        self._chat_model = chat_model
        self._deep_model = deep_model
        self._system_prompt_override = system_prompt_override
        self._use_listener = use_listener
        self._result: ScenarioResult | None = None
        # Live state — accessible during runs for streaming
        self._node: SyntheticSensorNode | None = None
        self._recorder: ActionRecorder | None = None
        self._commander = None
        self._running = False

    def run(self) -> ScenarioResult:
        """Execute the scenario and return scored results."""
        from amy.commander import Commander

        run_id = f"run-{uuid.uuid4().hex[:8]}"
        result = ScenarioResult(
            scenario_name=self._scenario.name,
            run_id=run_id,
            status="running",
            config={
                "chat_model": self._chat_model,
                "deep_model": self._deep_model,
                "time_scale": self._scenario.time_scale,
                "think_interval": self._scenario.think_interval,
                "use_listener": self._use_listener,
                "system_prompt_override": self._system_prompt_override,
            },
        )

        # Create synthetic node
        node = SyntheticSensorNode(self._scenario, width=640, height=480)
        self._node = node

        # Create Commander with fast timing — zero boot delay and short
        # think initial delay so Amy reacts quickly in compressed time.
        # Use a temp memory file so scenario runs don't pollute Amy's real memory.
        tmp_memory = tempfile.NamedTemporaryFile(
            suffix=".json", prefix="amy_scenario_mem_", delete=False,
        )
        tmp_memory.close()

        commander = Commander(
            nodes={"synthetic": node},
            deep_model=self._deep_model,
            chat_model=self._chat_model,
            use_tts=False,
            wake_word=None,
            think_interval=self._scenario.think_interval,
            curiosity_min=10.0,
            curiosity_max=20.0,
            use_listener=self._use_listener,
            boot_delay=0.0,
            think_initial_delay=1.0,
            memory_path=tmp_memory.name,
        )

        self._commander = commander

        # Start action recorder
        recorder = ActionRecorder(commander.event_bus)
        self._recorder = recorder
        recorder.start()
        self._running = True

        # Run Commander in background thread
        commander_thread = threading.Thread(
            target=commander.run, daemon=True, name="scenario-commander",
        )

        t0 = time.monotonic()

        try:
            commander_thread.start()

            # Calculate real-world timeout
            scenario_real_time = self._scenario.duration * self._scenario.time_scale
            timeout = scenario_real_time + 30.0  # Buffer for boot + shutdown

            # Inject transcripts if not using listener
            if not self._use_listener:
                inject_thread = threading.Thread(
                    target=self._inject_transcripts,
                    args=(node, commander),
                    daemon=True,
                )
                inject_thread.start()

            # Inject detection events (bypass YOLO for synthetic people)
            detect_thread = threading.Thread(
                target=self._inject_detections,
                args=(node, commander),
                daemon=True,
            )
            detect_thread.start()

            # Inject ambient/environmental observations into sensorium
            ambient_thread = threading.Thread(
                target=self._inject_ambient,
                args=(node, commander),
                daemon=True,
            )
            ambient_thread.start()

            # Wait for scenario to finish or timeout
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if node.finished:
                    # Give Amy more time to react to final events
                    time.sleep(min(5.0, self._scenario.time_scale * 10))
                    break
                time.sleep(0.5)

            result.duration_actual = time.monotonic() - t0

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
        finally:
            # Shutdown
            self._running = False
            recorder.stop()
            commander.shutdown()
            commander_thread.join(timeout=5)
            # Clean up temp memory file
            import os
            try:
                os.unlink(tmp_memory.name)
            except OSError:
                pass

        # Score
        result.actions = recorder.all_actions
        scorer = Scorer()
        result.score = scorer.score(
            result.actions, self._scenario.expected,
            time_scale=self._scenario.time_scale,
            duration=self._scenario.duration * self._scenario.time_scale,
        )
        result.status = "completed"

        self._result = result
        return result

    def get_jpeg(self) -> bytes | None:
        """Get current JPEG frame from the synthetic camera (for MJPEG streaming)."""
        if self._node is not None and self._running:
            return self._node.get_jpeg()
        return None

    def get_live_actions(self, since_index: int = 0) -> list:
        """Get new actions since a given index (for live SSE streaming)."""
        if self._recorder is None:
            return []
        with self._recorder._lock:
            return [a.model_dump() for a in self._recorder.actions[since_index:]]

    @property
    def is_running(self) -> bool:
        return self._running

    def _inject_transcripts(
        self,
        node: SyntheticSensorNode,
        commander,
    ) -> None:
        """Poll SyntheticSensorNode for pending transcripts and inject into Commander."""
        from amy.commander import Event, EventType

        while not node.finished:
            transcripts = node.get_pending_transcripts()
            for text in transcripts:
                commander.event_bus.publish(
                    "transcript", {"speaker": "user", "text": text},
                )
                commander._event_queue.put(
                    Event(EventType.TRANSCRIPT_READY, data=text),
                )
            time.sleep(0.2)

    def _inject_detections(
        self,
        node: SyntheticSensorNode,
        commander,
    ) -> None:
        """Inject person detection events from the synthetic world state.

        YOLO cannot detect the simple geometric silhouettes, so we inject
        PERSON_ARRIVED / PERSON_LEFT events directly from the world state.
        This tests Amy's full behavioral pipeline (greeting, tracking,
        thinking) without depending on YOLO recognising drawn shapes.
        """
        from amy.commander import Event, EventType

        prev_count = 0

        # Wait for Commander to finish booting
        while not commander._running and not node.finished:
            time.sleep(0.1)

        while not node.finished:
            snap = node.world.snapshot()
            current_count = len(snap.get("people", []))

            arrived = current_count > prev_count
            departed = current_count < prev_count

            if arrived:
                # Publish detections EventBus event (ActionRecorder captures this)
                commander.event_bus.publish("detections", {
                    "summary": f"{current_count} person(s) detected",
                    "people": current_count,
                    "boxes": [{"cls": "person", "conf": 0.95}] * current_count,
                })
                # Publish person arrival event
                commander.event_bus.publish("event", {
                    "text": f"[YOLO: {current_count} person(s) detected]",
                })
                # Queue PERSON_ARRIVED for Commander event loop
                commander._event_queue.put(
                    Event(EventType.PERSON_ARRIVED, data=current_count),
                )
                # Push to sensorium
                commander.sensorium.push(
                    "yolo", f"{current_count} person(s) detected", importance=0.8,
                )

            if departed and current_count == 0:
                commander.event_bus.publish("event", {
                    "text": "[everyone left]",
                })
                commander._event_queue.put(Event(EventType.PERSON_LEFT))
                commander.sensorium.push(
                    "yolo", "Everyone left", importance=0.7,
                )

            prev_count = current_count
            time.sleep(0.3)

    def _inject_ambient(
        self,
        node: SyntheticSensorNode,
        commander,
    ) -> None:
        """Push ambient/environmental observations into the sensorium."""
        while not node.finished:
            observations = node.get_pending_ambient()
            for text in observations:
                commander.sensorium.push("environment", text, importance=0.7)
                commander.event_bus.publish("event", {"text": f"[environment: {text}]"})
            time.sleep(0.3)
