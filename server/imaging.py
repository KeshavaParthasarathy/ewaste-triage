"""Shared image decoding and release-model preprocessing."""
import numpy as np
from PIL import Image, ImageOps


MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]
SUPPORTED_PREPROCESSING_VERSION = "rgb-224-v1"
INFERENCE_CROP_SIZE = (224, 224)
_RESIZE_SHORT_EDGE = 256
_MEAN_ARRAY = np.asarray(MEAN, dtype=np.float32).reshape(3, 1, 1)
_STD_ARRAY = np.asarray(STD, dtype=np.float32).reshape(3, 1, 1)


class ImageTooLarge(ValueError):
    """Raised when an upload is too large to process safely."""


_heif_registered = False


def register_image_formats() -> None:
    """Register optional image decoders once before opening uploaded images."""
    global _heif_registered
    if not _heif_registered:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True


def normalize_image(image: Image.Image, *, max_pixels: int = 40_000_000) -> Image.Image:
    """Apply phone orientation metadata and return an RGB image within the size limit."""
    if image.width * image.height > max_pixels:
        raise ImageTooLarge(f"image exceeds {max_pixels:,} pixels")
    return ImageOps.exif_transpose(image).convert("RGB")


def preprocess_array(image: Image.Image) -> np.ndarray:
    """Return the release model's normalized NCHW float32 input array."""
    return preprocess_crop_array(preprocess_image(image))


def preprocess_crop_array(image: Image.Image) -> np.ndarray:
    """Normalize an already-prepared 224×224 RGB release crop for inference."""
    if image.mode != "RGB" or image.size != INFERENCE_CROP_SIZE:
        raise ValueError("inference crop must be a 224x224 RGB image")
    channels_first = np.asarray(image, dtype=np.float32).transpose(2, 0, 1)
    normalized = (channels_first / np.float32(255.0) - _MEAN_ARRAY) / _STD_ARRAY
    return np.ascontiguousarray(normalized[np.newaxis, ...], dtype=np.float32)


def inference_crop(image: Image.Image) -> Image.Image:
    """Return the release geometry crop from an already-normalized source image."""
    width, height = image.size
    if width <= height:
        resized_width = _RESIZE_SHORT_EDGE
        resized_height = int(_RESIZE_SHORT_EDGE * height / width)
    else:
        resized_height = _RESIZE_SHORT_EDGE
        resized_width = int(_RESIZE_SHORT_EDGE * width / height)
    resized = image.resize(
        (resized_width, resized_height),
        resample=Image.Resampling.BILINEAR,
    )
    crop_width, crop_height = INFERENCE_CROP_SIZE
    left = int(round((resized_width - crop_width) / 2.0))
    top = int(round((resized_height - crop_height) / 2.0))
    return resized.crop((left, top, left + crop_width, top + crop_height))


def preprocess_image(image: Image.Image) -> Image.Image:
    """Return the upright RGB image after the release model's geometry transform."""
    return inference_crop(normalize_image(image))
