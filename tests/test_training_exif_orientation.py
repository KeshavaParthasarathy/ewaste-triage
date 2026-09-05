import torch
from PIL import Image, ImageDraw, ImageOps

from scripts.train_classifier import build_transforms
from server.imaging import preprocess_array


def test_evaluation_transform_applies_exif_orientation_before_cropping():
    image = Image.new("RGB", (360, 240), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 120, 240), fill="red")
    draw.rectangle((240, 0, 360, 240), fill="blue")
    image.getexif()[274] = 6
    upright = ImageOps.exif_transpose(image)

    transformed_from_metadata = build_transforms(False)(image)
    transformed_from_upright_pixels = build_transforms(False)(upright)

    assert torch.equal(transformed_from_metadata, transformed_from_upright_pixels)


def test_evaluation_transform_matches_the_release_preprocessing_values():
    image = Image.new("RGB", (360, 240), "purple")

    transformed = build_transforms(False)(image)

    assert torch.equal(transformed, torch.from_numpy(preprocess_array(image))[0])
