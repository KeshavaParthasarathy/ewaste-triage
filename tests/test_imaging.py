import numpy as np
from PIL import Image

from server.imaging import normalize_image, preprocess_array


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
