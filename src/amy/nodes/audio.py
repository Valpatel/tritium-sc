"""Standalone mic/speaker sensor node.

Phase 2 stub — any USB mic or ALSA audio device, no camera.
"""

from __future__ import annotations

from .base import SensorNode


class AudioNode(SensorNode):
    """Standalone microphone + optional speaker, no camera.

    TODO Phase 2: Implement audio recording/playback for arbitrary
    USB mics and ALSA devices.
    """

    def __init__(
        self,
        node_id: str,
        name: str,
        input_device: int | None = None,
        output_device: str | None = None,
    ):
        super().__init__(node_id, name)
        self.input_device = input_device
        self.output_device = output_device

    @property
    def has_mic(self) -> bool:
        return True

    @property
    def has_speaker(self) -> bool:
        return self.output_device is not None
