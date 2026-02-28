# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Hardware tests for BCC950Node audio (microphone) functionality.

Requires a physical BCC950 ConferenceCam connected via USB.
Run with: pytest tests/amy/test_hw_audio.py -m hardware
"""

from __future__ import annotations

import numpy as np
import pytest

sd = pytest.importorskip("sounddevice", reason="sounddevice not installed")
bcc950_mod = pytest.importorskip("engine.nodes.bcc950", reason="bcc950 deps not installed")
BCC950Node = bcc950_mod.BCC950Node

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


def _find_bcc950_mic() -> int | None:
    """Find BCC950 mic device index using sounddevice directly.

    The BCC950's Conexant chip may report as 'CONEXANT USB AUDIO'
    rather than 'BCC950'.  PortAudio sometimes reports 0 input
    channels for it, so also check ALSA as a fallback.
    """
    for i, dev in enumerate(sd.query_devices()):
        name = dev.get("name", "")
        if dev["max_input_channels"] > 0 and ("BCC950" in name or "CONEXANT" in name.upper()):
            return i
    return None


def _bcc950_mic_available() -> bool:
    """Check if BCC950 mic is available via sounddevice or ALSA."""
    if _find_bcc950_mic() is not None:
        return True
    # Fall back to ALSA detection
    import subprocess
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
        return "BCC950" in r.stdout.upper() or "CONEXANT" in r.stdout.upper()
    except Exception:
        return False


@pytest.fixture(scope="module")
def bcc950_node():
    """Create, start, yield, and stop a BCC950Node for the test module."""
    node = BCC950Node()
    try:
        node.start()
    except RuntimeError as e:
        pytest.skip(f"BCC950 not available: {e}")
    yield node
    node.stop()


class TestBCC950Audio:
    def test_mic_found(self):
        """BCC950 mic can be found via sounddevice or ALSA."""
        assert _bcc950_mic_available(), "BCC950 microphone not found via sounddevice or ALSA"

    def test_record_audio_returns_float32(self, bcc950_node: BCC950Node):
        """record_audio() returns a numpy float32 array."""
        audio = bcc950_node.record_audio(1.0)
        assert audio is not None, "record_audio() returned None"
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32

    def test_record_audio_sample_count(self, bcc950_node: BCC950Node):
        """Recorded audio has approximately 16000 samples for 1s (within 10%)."""
        audio = bcc950_node.record_audio(1.0)
        assert audio is not None
        expected = 16000
        tolerance = expected * 0.10
        assert abs(len(audio) - expected) <= tolerance, (
            f"Expected ~{expected} samples, got {len(audio)}"
        )

    def test_audio_values_in_range(self, bcc950_node: BCC950Node):
        """Audio values are in [-1, 1] range."""
        audio = bcc950_node.record_audio(1.0)
        assert audio is not None
        assert audio.min() >= -1.0, f"Audio min {audio.min()} below -1.0"
        assert audio.max() <= 1.0, f"Audio max {audio.max()} above 1.0"

    def test_audio_not_all_zeros(self, bcc950_node: BCC950Node):
        """Audio is not all zeros (ambient noise should produce some signal)."""
        audio = bcc950_node.record_audio(1.0)
        assert audio is not None
        assert not np.allclose(audio, 0.0), "Audio is all zeros — mic may be dead"


def test_audio_report(bcc950_node: BCC950Node):
    """Print mic device info and noise floor."""
    device_index = _find_bcc950_mic()
    if device_index is not None:
        dev_info = sd.query_devices(device_index)
        device_name = dev_info.get("name", "unknown")
        native_rate = int(dev_info.get("default_samplerate", 0))
    elif getattr(bcc950_node, '_use_arecord', False):
        device_name = f"ALSA hw:{bcc950_node._alsa_card},0 (arecord)"
        native_rate = bcc950_node._listener_device_rate
    else:
        device_name = "NOT FOUND"
        native_rate = 0

    audio = bcc950_node.record_audio(1.0)
    if audio is not None:
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    else:
        rms = 0.0

    print("\n" + "=" * 50)
    print("BCC950 Audio Report")
    print("=" * 50)
    print(f"  Mic device    : {device_name}")
    print(f"  Native rate   : {native_rate} Hz")
    print(f"  Output rate   : 16000 Hz (resampled)")
    print(f"  Noise floor   : {rms:.6f} RMS")
    print("=" * 50)
