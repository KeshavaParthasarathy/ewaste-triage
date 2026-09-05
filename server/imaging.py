"""Shared image decoding and release-model preprocessing."""
import numpy as np
from PIL import Image, ImageOps
from torchvision import transforms


MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]
SUPPORTED_PREPROCESSING_VERSION = "rgb-224-v1"
RELEASE_IMAGE_TRANSFORM = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
])
RELEASE_TRANSFORM = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])


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
    tensor = RELEASE_TRANSFORM(preprocess_image(image)).unsqueeze(0)
    return tensor.numpy().astype(np.float32, copy=False)


def preprocess_image(image: Image.Image) -> Image.Image:
    """Return the upright RGB image after the release model's geometry transform."""
    return RELEASE_IMAGE_TRANSFORM(normalize_image(image))
