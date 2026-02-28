# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""LLMThinkScheduler — rate-limited, prioritized NPC thinking queue.

Manages a pool of worker threads that call the LLM for NPC decisions.
Rate-limits calls to avoid overwhelming the inference server, and
prioritizes NPCs in danger.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from engine.perception.vision import ollama_chat
from .prompts import build_npc_prompt, parse_npc_response

log = logging.getLogger(__name__)

# Queue limits
_MAX_QUEUE_SIZE = 50


@dataclass(order=True)
class _ThinkRequest:
    """A queued NPC thinking request. Lower priority value = higher priority."""

    priority: float
    timestamp: float = field(compare=False)
    brain: Any = field(compare=False)  # NPCBrain
    nearby_entities: list[dict] | None = field(compare=False, default=None)
    callback: Callable | None = field(compare=False, default=None)


class LLMThinkScheduler:
    """Rate-limited scheduler for NPC LLM thinking.

    Features:
    - Rate-limits LLM calls (min 0.5s between calls per worker)
    - Max concurrent workers (default 2)
    - Priority queue: NPCs in danger think first
    - Queue max size: 50 (drops oldest when full)
    - Graceful error handling: marks brain for fallback on LLM failure
    """

    def __init__(
        self,
        model: str = "gemma3:4b",
        max_concurrent: int = 2,
    ) -> None:
        self._model = model
        self._max_concurrent = max_concurrent
        self._min_interval = 0.5  # seconds between LLM calls

        self._queue: list[_ThinkRequest] = []
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()

        self._running = False
        self._workers: list[threading.Thread] = []
        self._last_call_time = 0.0
        self._call_lock = threading.Lock()

    @property
    def pending_count(self) -> int:
        """Number of pending think requests."""
        with self._queue_lock:
            return len(self._queue)

    @property
    def healthy(self) -> bool:
        """True when the queue is not overflowing."""
        with self._queue_lock:
            return len(self._queue) < _MAX_QUEUE_SIZE

    def start(self) -> None:
        """Start worker threads."""
        if self._running:
            return
        self._running = True
        self._workers = []
        for i in range(self._max_concurrent):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"npc-thinker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def stop(self) -> None:
        """Stop worker threads."""
        self._running = False
        self._queue_event.set()  # Wake up workers so they can exit
        for t in self._workers:
            t.join(timeout=2.0)
        self._workers = []

    def schedule(
        self,
        brain: Any,
        nearby_entities: list[dict] | None,
        callback: Callable[[str, str], None],
    ) -> None:
        """Enqueue an NPC brain for thinking.

        Args:
            brain: NPCBrain instance.
            nearby_entities: Nearby entities for context.
            callback: Called with (target_id, action_string) on success.
        """
        # Priority: lower = more urgent. Danger level inverted (high danger = low priority number).
        danger = brain.memory.danger_level()
        priority = 1.0 - danger  # 0.0 = most urgent, 1.0 = least

        req = _ThinkRequest(
            priority=priority,
            timestamp=time.monotonic(),
            brain=brain,
            nearby_entities=nearby_entities,
            callback=callback,
        )

        with self._queue_lock:
            self._queue.append(req)
            self._queue.sort()  # Priority sort

            # Enforce max queue size — drop oldest (highest priority value = least urgent)
            while len(self._queue) > _MAX_QUEUE_SIZE:
                self._queue.pop()  # Remove last (least urgent)

        self._queue_event.set()

    def _worker_loop(self) -> None:
        """Worker thread main loop."""
        while self._running:
            req = self._dequeue()
            if req is None:
                # Wait for new items or shutdown
                self._queue_event.wait(timeout=1.0)
                self._queue_event.clear()
                continue

            self._process_request(req)

    def _dequeue(self) -> _ThinkRequest | None:
        """Pop the highest-priority request from the queue."""
        with self._queue_lock:
            if not self._queue:
                return None
            return self._queue.pop(0)  # Lowest priority value = first

    def _process_request(self, req: _ThinkRequest) -> None:
        """Process a single think request with rate limiting."""
        # Rate limiting
        with self._call_lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                wait = self._min_interval - elapsed
                time.sleep(wait)
            self._last_call_time = time.monotonic()

        # Build prompt and call LLM
        try:
            prompt = build_npc_prompt(req.brain, req.nearby_entities)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "What do you do? Respond with one action word."},
            ]
            response = ollama_chat(model=self._model, messages=messages)
            response_text = response.get("message", {}).get("content", "").strip()
            action = parse_npc_response(response_text)

            # Mark thought on the brain
            req.brain.mark_thought()

            # Invoke callback
            try:
                if req.callback is not None:
                    req.callback(req.brain.target_id, action)
            except Exception:
                log.exception("Callback error for NPC %s", req.brain.target_id)

        except Exception:
            log.exception("LLM call failed for NPC %s", req.brain.target_id)
            # Mark brain as needing fallback
            req.brain._needs_fallback = True
