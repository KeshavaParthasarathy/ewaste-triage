import numpy as np
import pytest
from PIL import Image
from torchvision.transforms import functional as vision_functional

import server.imaging as imaging
from server.imaging import (ImageTooLarge, normalize_image, preprocess_array,
                            preprocess_image, register_image_formats)


def test_normalize_applies_exif_orientation():
    image = Image.new("RGB", (40, 20), "red")
    image.getexif()[274] = 6

    normalized = normalize_image(image)

    assert normalized.size == (20, 40)
    assert normalized.mode == "RGB"


def test_preprocess_array_has_release_shape_and_dtype():
    value = preprocess_array(Image.new("RGB", (400, 300), "blue"))

    assert value.shape == (1, 3, 224, 224)
    assert value.dtype == np.float32


def test_preprocess_image_has_release_crop_dimensions():
    value = preprocess_image(Image.new("RGB", (400, 300), "blue"))

    assert value.size == (224, 224)
    assert value.mode == "RGB"


def test_release_preprocessing_matches_the_training_transform_contract():
    pixels = np.arange(317 * 241 * 3, dtype=np.uint32).reshape(241, 317, 3)
    source = Image.fromarray((pixels % 256).astype(np.uint8), mode="RGB")
    expected_crop = vision_functional.center_crop(
        vision_functional.resize(source, 256),
        [224, 224],
    )
    expected_tensor = vision_functional.normalize(
        vision_functional.to_tensor(expected_crop),
        imaging.MEAN,
        imaging.STD,
    ).unsqueeze(0)

    assert np.array_equal(np.asarray(preprocess_image(source)), np.asarray(expected_crop))
    assert preprocess_array(source) == pytest.approx(expected_tensor.numpy(), abs=1e-7)


def test_normalize_converts_non_rgb_images_to_rgb():
    normalized = normalize_image(Image.new("L", (20, 40), 128))

    assert normalized.mode == "RGB"


def test_normalize_rejects_images_over_the_pixel_limit():
    with pytest.raises(ImageTooLarge, match="image exceeds 99 pixels"):
        normalize_image(Image.new("RGB", (10, 10)), max_pixels=99)


def test_register_image_formats_registers_heif_opener_once(monkeypatch):
    registrations = []

    class Heif:
        @staticmethod
        def register_heif_opener():
            registrations.append(True)

    monkeypatch.setattr(imaging, "_heif_registered", False)
    monkeypatch.setitem(__import__("sys").modules, "pillow_heif", Heif)

    register_image_formats()
    register_image_formats()

    assert registrations == [True]
