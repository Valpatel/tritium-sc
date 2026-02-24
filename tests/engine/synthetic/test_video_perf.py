"""Performance metrics for synthetic video and audio generation.

Measures frame generation time, batch throughput, memory stability,
video clip generation, audio effect generation, concurrent rendering,
and MJPEG stream rate. Outputs a structured JSON report.

All thresholds have 2x headroom from production targets.
"""

from __future__ import annotations

import gc
import json
import os
import resource
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine.synthetic.video_gen import (
    render_battle_scene,
    render_bird_eye,
    render_neighborhood,
    render_street_cam,
)
from engine.synthetic.video_library import SyntheticVideoLibrary
from engine.audio.sound_effects import SoundEffectGenerator
from app.routers.synthetic_feed import SyntheticFeedConfig, SyntheticFeedManager


pytestmark = pytest.mark.unit

RESOLUTION = (640, 480)
SEED = 42

_RENDERERS = {
    "bird_eye": render_bird_eye,
    "street_cam": render_street_cam,
    "battle": render_battle_scene,
    "neighborhood": render_neighborhood,
}

# Output directory for perf report
_RESULTS_DIR = Path(__file__).parent.parent / ".test-results"


def _get_rss_mb() -> float:
    """Get current RSS in megabytes."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return ru.ru_maxrss / 1024.0  # Linux: KB -> MB


@pytest.fixture(scope="module")
def perf_results():
    """Collect performance metrics for reporting."""
    results: dict[str, dict] = {}
    yield results

    # Write report after all tests
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _RESULTS_DIR / "perf-report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)


# ===========================================================================
# Frame generation time
# ===========================================================================


class TestFrameGenerationTime:
    """Each renderer should produce a 640x480 frame in <100ms (2x headroom from 50ms)."""

    @pytest.mark.parametrize("scene", ["bird_eye", "street_cam", "battle", "neighborhood"])
    def test_single_frame_under_100ms(self, scene, perf_results):
        renderer = _RENDERERS[scene]
        kwargs = {"resolution": RESOLUTION, "seed": SEED}
        if scene == "street_cam":
            kwargs["camera_name"] = "PERF"
        elif scene == "neighborhood":
            kwargs["camera_name"] = "PERF"

        # Warmup
        renderer(**kwargs)

        # Measure
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            frame = renderer(**kwargs)
            elapsed = (time.perf_counter() - t0) * 1000
            times.append(elapsed)
            assert frame.shape == (480, 640, 3)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)
        p95_ms = sorted(times)[int(len(times) * 0.95)]

        perf_results[f"frame_time_{scene}"] = {
            "avg_ms": round(avg_ms, 2),
            "max_ms": round(max_ms, 2),
            "p95_ms": round(p95_ms, 2),
            "samples": len(times),
        }

        assert max_ms < 100, (
            f"{scene}: max frame time {max_ms:.1f}ms > 100ms threshold"
        )


# ===========================================================================
# Batch throughput
# ===========================================================================


class TestBatchThroughput:
    """100 frames in <6s per scene type (2x headroom from 3s)."""

    @pytest.mark.parametrize("scene", ["bird_eye", "street_cam", "battle", "neighborhood"])
    def test_100_frames_under_6s(self, scene, perf_results):
        renderer = _RENDERERS[scene]
        kwargs = {"resolution": RESOLUTION}
        if scene in ("street_cam", "neighborhood"):
            kwargs["camera_name"] = "BATCH"

        t0 = time.perf_counter()
        for i in range(100):
            kwargs["seed"] = SEED + i
            frame = renderer(**kwargs)
            assert frame is not None
        elapsed = time.perf_counter() - t0

        fps = 100.0 / elapsed
        perf_results[f"batch_{scene}"] = {
            "total_s": round(elapsed, 3),
            "fps": round(fps, 1),
            "frames": 100,
        }

        assert elapsed < 6.0, (
            f"{scene}: 100 frames took {elapsed:.2f}s, exceeds 6s threshold"
        )


# ===========================================================================
# Memory stability
# ===========================================================================


class TestMemoryStability:
    """Generate 500 frames, check RSS doesn't grow unbounded."""

    def test_rss_stable_over_500_frames(self, perf_results):
        gc.collect()
        rss_start = _get_rss_mb()

        for i in range(500):
            scene = list(_RENDERERS.keys())[i % 4]
            renderer = _RENDERERS[scene]
            kwargs = {"resolution": RESOLUTION, "seed": SEED + i}
            if scene in ("street_cam", "neighborhood"):
                kwargs["camera_name"] = "MEM"
            frame = renderer(**kwargs)
            # Don't accumulate refs
            del frame

        gc.collect()
        rss_end = _get_rss_mb()
        growth = rss_end - rss_start

        perf_results["memory_stability"] = {
            "rss_start_mb": round(rss_start, 1),
            "rss_end_mb": round(rss_end, 1),
            "growth_mb": round(growth, 1),
            "frames": 500,
        }

        # Allow up to 100MB growth (generous, should be much less)
        assert growth < 100, (
            f"RSS grew {growth:.1f}MB over 500 frames (start={rss_start:.1f}, end={rss_end:.1f})"
        )


# ===========================================================================
# Video library clip generation
# ===========================================================================


class TestVideoLibraryPerf:
    """generate_clip(5s, 10fps) should complete in <4s (2x headroom from 2s)."""

    def test_generate_clip_5s(self, tmp_path, perf_results):
        lib = SyntheticVideoLibrary(library_path=str(tmp_path / "video"))

        t0 = time.perf_counter()
        clip_dir = lib.generate_clip(
            scene_type="bird_eye", duration=5.0, fps=10,
            resolution=RESOLUTION, seed=SEED,
        )
        elapsed = time.perf_counter() - t0

        perf_results["clip_generation_5s_10fps"] = {
            "elapsed_s": round(elapsed, 3),
            "clip_dir": str(clip_dir),
        }

        assert elapsed < 4.0, f"Clip generation took {elapsed:.2f}s, exceeds 4s threshold"
        assert (clip_dir / "clip.mp4").exists()
        assert (clip_dir / "metadata.json").exists()


# ===========================================================================
# Audio generation performance
# ===========================================================================


class TestAudioGenerationPerf:
    """Each effect in <40ms (2x from 20ms), all 19 in <1s (2x from 500ms)."""

    def test_individual_effects(self, perf_results):
        gen = SoundEffectGenerator()
        effects = [
            ("nerf_shot", 0.3),
            ("projectile_whoosh", 0.5),
            ("impact_hit", 0.2),
            ("explosion", 1.0),
            ("turret_rotate", 0.8),
            ("drone_buzz", 2.0),
            ("footstep", 0.15),
            ("alert_tone", 0.5),
            ("escalation_siren", 2.0),
            ("dispatch_ack", 0.3),
            ("wave_start", 1.5),
            ("victory_fanfare", 3.0),
            ("defeat_sting", 2.0),
            ("ambient_wind", 5.0),
            ("ambient_birds", 5.0),
        ]

        times = {}
        for name, dur in effects:
            t0 = time.perf_counter()
            audio = getattr(gen, name)(duration=dur)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            times[name] = round(elapsed_ms, 2)
            assert audio.dtype == np.float32
            assert elapsed_ms < 40, f"{name} took {elapsed_ms:.1f}ms, exceeds 40ms"

        perf_results["audio_individual_ms"] = times

    def test_all_effects_total_time(self, perf_results):
        gen = SoundEffectGenerator()
        effects = [
            ("nerf_shot", 0.3, {}),
            ("projectile_whoosh", 0.5, {}),
            ("impact_hit", 0.2, {}),
            ("explosion", 1.0, {}),
            ("turret_rotate", 0.8, {}),
            ("drone_buzz", 2.0, {}),
            ("footstep", 0.15, {}),
            ("alert_tone", 0.5, {}),
            ("escalation_siren", 2.0, {}),
            ("dispatch_ack", 0.3, {}),
            ("wave_start", 1.5, {}),
            ("victory_fanfare", 3.0, {}),
            ("defeat_sting", 2.0, {}),
            ("elimination_streak", 1.5, {"streak_name": "ON A STREAK"}),
            ("elimination_streak", 1.5, {"streak_name": "RAMPAGE"}),
            ("elimination_streak", 1.5, {"streak_name": "DOMINATING"}),
            ("elimination_streak", 1.5, {"streak_name": "GODLIKE"}),
            ("ambient_wind", 5.0, {}),
            ("ambient_birds", 5.0, {}),
        ]

        t0 = time.perf_counter()
        for name, dur, kwargs in effects:
            getattr(gen, name)(duration=dur, **kwargs)
        total = (time.perf_counter() - t0) * 1000

        perf_results["audio_total_19_effects_ms"] = round(total, 2)
        assert total < 1000, f"All 19 effects took {total:.1f}ms, exceeds 1000ms"


# ===========================================================================
# Concurrent frame generation
# ===========================================================================


class TestConcurrentGeneration:
    """4 threads generating different scene types simultaneously."""

    def test_four_threads_concurrent(self, perf_results):
        results_dict: dict[str, float] = {}
        errors: list[str] = []

        def _generate(scene: str, n_frames: int):
            renderer = _RENDERERS[scene]
            t0 = time.perf_counter()
            for i in range(n_frames):
                kwargs = {"resolution": RESOLUTION, "seed": SEED + i}
                if scene in ("street_cam", "neighborhood"):
                    kwargs["camera_name"] = f"CONC-{scene}"
                try:
                    frame = renderer(**kwargs)
                    assert frame.shape == (480, 640, 3)
                except Exception as e:
                    errors.append(f"{scene}: {e}")
            elapsed = time.perf_counter() - t0
            results_dict[scene] = elapsed

        threads = []
        for scene in _RENDERERS:
            t = threading.Thread(target=_generate, args=(scene, 25))
            threads.append(t)

        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        wall_time = time.perf_counter() - t0

        perf_results["concurrent_4_threads"] = {
            "wall_time_s": round(wall_time, 3),
            "per_thread_s": {k: round(v, 3) for k, v in results_dict.items()},
            "frames_per_thread": 25,
            "errors": errors,
        }

        assert not errors, f"Concurrent errors: {errors}"
        # 4 threads x 25 frames should complete faster than sequential
        assert wall_time < 20, f"Concurrent generation took {wall_time:.2f}s"


# ===========================================================================
# MJPEG stream rate
# ===========================================================================


class TestMJPEGStreamRate:
    """SyntheticFeedManager maintains >5 FPS for a duration of frames."""

    def test_mjpeg_rate(self, perf_results):
        mgr = SyntheticFeedManager()
        config = SyntheticFeedConfig(
            feed_id="perf-test",
            scene_type="bird_eye",
            fps=10,
            width=640,
            height=480,
        )
        mgr.create_feed(config)

        # Generate frames directly (skip the sleep-based mjpeg_frames generator)
        n_frames = 50
        t0 = time.perf_counter()
        for _ in range(n_frames):
            frame = mgr.generate_frame("perf-test")
            assert frame.shape == (480, 640, 3)
        elapsed = time.perf_counter() - t0

        actual_fps = n_frames / elapsed

        perf_results["mjpeg_stream_rate"] = {
            "frames": n_frames,
            "elapsed_s": round(elapsed, 3),
            "fps": round(actual_fps, 1),
        }

        # Target: >5 FPS with 2x headroom -> test at >2.5 FPS
        assert actual_fps > 2.5, (
            f"MJPEG rate {actual_fps:.1f} FPS < 2.5 FPS threshold"
        )

    def test_snapshot_jpeg_valid(self, perf_results):
        mgr = SyntheticFeedManager()
        config = SyntheticFeedConfig(feed_id="snap-test", scene_type="street_cam")
        mgr.create_feed(config)

        t0 = time.perf_counter()
        jpeg = mgr.get_snapshot("snap-test")
        elapsed_ms = (time.perf_counter() - t0) * 1000

        perf_results["snapshot_jpeg"] = {
            "elapsed_ms": round(elapsed_ms, 2),
            "size_bytes": len(jpeg),
        }

        assert jpeg[:2] == b"\xff\xd8", "Not a valid JPEG"
        assert elapsed_ms < 200, f"Snapshot took {elapsed_ms:.1f}ms"
