import numpy as np
import pytest
from PIL import Image

from server.explanations import occlusion_map


class BrightnessEngine:
    def probabilities(self, image):
        brightness = np.asarray(image, dtype=np.float32).mean() / 255.0
        return np.array([brightness, 1.0 - brightness], dtype=np.float32)

    probabilities_preprocessed = probabilities


class ConstantEngine:
    def probabilities(self, image):
        return np.array([0.5, 0.5], dtype=np.float32)

    probabilities_preprocessed = probabilities


class CropRecordingEngine:
    def __init__(self):
        self.seen = []

    def probabilities(self, image):
        raise AssertionError("release crops must not be passed through probabilities")

    def probabilities_preprocessed(self, image):
        self.seen.append(np.asarray(image).copy())
        return np.array([0.5, 0.5], dtype=np.float32)


def quadrant_image():
    pixels = np.zeros((224, 224, 3), dtype=np.uint8)
    pixels[:112, :112] = 255
    return Image.fromarray(pixels, "RGB")


def test_occlusion_map_is_normalized_and_stable():
    heat = occlusion_map(BrightnessEngine(), quadrant_image(), 0, grid_size=4)

    assert heat.shape == (4, 4)
    assert heat.min() >= 0.0
    assert heat.max() <= 1.0
    assert heat[0, 0] == pytest.approx(1.0)


def test_occlusion_map_returns_zeros_when_occlusion_never_reduces_score():
    heat = occlusion_map(ConstantEngine(), quadrant_image(), 0, grid_size=4)

    assert np.array_equal(heat, np.zeros((4, 4), dtype=np.float32))


@pytest.mark.parametrize("class_index", [-1, 2])
def test_occlusion_map_rejects_a_class_outside_the_probability_vector(class_index):
    with pytest.raises(ValueError, match="class_index"):
        occlusion_map(BrightnessEngine(), quadrant_image(), class_index)


@pytest.mark.parametrize("grid_size", [0, -1])
def test_occlusion_map_rejects_non_positive_grid_size(grid_size):
    with pytest.raises(ValueError, match="grid_size"):
        occlusion_map(BrightnessEngine(), quadrant_image(), 0, grid_size=grid_size)


def test_occlusion_map_passes_the_exact_non_square_release_crop_to_the_backend():
    pixels = np.zeros((256, 512, 3), dtype=np.uint8)
    pixels[16, 144] = [1, 2, 3]
    pixels[16, 367] = [4, 5, 6]
    pixels[239, 144] = [7, 8, 9]
    pixels[239, 367] = [10, 11, 12]
    engine = CropRecordingEngine()

    occlusion_map(engine, Image.fromarray(pixels, "RGB"), 0, grid_size=2)

    baseline, first_mask = engine.seen[:2]
    assert len(engine.seen) == 5
    assert baseline.shape == (224, 224, 3)
    assert baseline[0, 0].tolist() == [1, 2, 3]
    assert baseline[0, -1].tolist() == [4, 5, 6]
    assert baseline[-1, 0].tolist() == [7, 8, 9]
    assert baseline[-1, -1].tolist() == [10, 11, 12]
    assert first_mask[0, 0].tolist() == [124, 116, 104]
    assert first_mask[0, -1].tolist() == [4, 5, 6]
