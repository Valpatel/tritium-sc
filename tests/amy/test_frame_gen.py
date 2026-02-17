"""Tests for frame generation."""
import pytest
import numpy as np

from amy.scenarios.frame_gen import FrameGenerator
from amy.scenarios.schema import Position2D


@pytest.mark.unit
class TestFrameGenerator:
    def test_frame_dimensions(self):
        gen = FrameGenerator(320, 240)
        state = {"people": []}
        frame = gen.generate_frame(state)
        assert frame.shape == (240, 320, 3)
        assert frame.dtype == np.uint8

    def test_custom_dimensions(self):
        gen = FrameGenerator(640, 480)
        frame = gen.generate_frame({"people": []})
        assert frame.shape == (480, 640, 3)

    def test_background_not_uniform(self):
        """Background should have noise/texture, not solid color."""
        gen = FrameGenerator()
        frame = gen.generate_frame({"people": []})
        # Check variance — noise means not all same color
        assert np.std(frame) > 1.0

    def test_person_rendered(self):
        """Pixels should change where person is drawn."""
        gen = FrameGenerator()
        empty = gen.generate_frame({"people": []})
        with_person = gen.generate_frame({
            "people": [{
                "position": Position2D(x=0.5, y=0.5),
                "height_ratio": 0.6,
                "color": (60, 60, 180),
            }]
        })
        # Frames should differ in the center area where person is
        h, w = empty.shape[:2]
        center_region = (slice(h//4, 3*h//4), slice(w//4, 3*w//4))
        diff = np.abs(with_person[center_region].astype(int) - empty[center_region].astype(int))
        assert diff.sum() > 1000  # Substantial pixel change

    def test_multiple_people(self):
        gen = FrameGenerator()
        frame = gen.generate_frame({
            "people": [
                {"position": Position2D(x=0.3, y=0.5), "height_ratio": 0.5, "color": (60, 60, 180)},
                {"position": Position2D(x=0.7, y=0.5), "height_ratio": 0.5, "color": (180, 60, 60)},
            ]
        })
        assert frame is not None
        assert frame.shape == (240, 320, 3)

    def test_person_at_edge(self):
        """Person at frame edge should not cause errors."""
        gen = FrameGenerator()
        frame = gen.generate_frame({
            "people": [
                {"position": Position2D(x=0.05, y=0.5), "height_ratio": 0.6, "color": (60, 60, 180)},
                {"position": Position2D(x=0.95, y=0.5), "height_ratio": 0.6, "color": (180, 60, 60)},
            ]
        })
        assert frame is not None

    def test_empty_people_list(self):
        gen = FrameGenerator()
        frame = gen.generate_frame({"people": []})
        assert frame is not None

    def test_height_ratio_affects_size(self):
        """Taller person should affect more pixels."""
        gen = FrameGenerator()
        small = gen.generate_frame({
            "people": [{"position": Position2D(x=0.5, y=0.5), "height_ratio": 0.3, "color": (100, 100, 200)}]
        })
        large = gen.generate_frame({
            "people": [{"position": Position2D(x=0.5, y=0.5), "height_ratio": 0.8, "color": (100, 100, 200)}]
        })
        bg = gen.generate_frame({"people": []})
        # Large person should modify more pixels than small person
        # (Use threshold to account for noise)
        diff_small = np.sum(np.abs(small.astype(int) - bg.astype(int)) > 20)
        diff_large = np.sum(np.abs(large.astype(int) - bg.astype(int)) > 20)
        assert diff_large > diff_small
