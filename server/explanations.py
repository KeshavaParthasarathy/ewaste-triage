"""Transient, model-agnostic occlusion explanations for desktop scans."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
import time
from typing import Callable

import numpy as np
from PIL import Image

from server.imaging import MEAN, preprocess_image
from server.inference import InferenceEngine


IMAGENET_MEAN_RGB = tuple(round(channel * 255) for channel in MEAN)


def occlusion_map(
    engine: InferenceEngine,
    image: Image.Image,
    class_index: int,
    *,
    grid_size: int = 7,
) -> np.ndarray:
    """Return normalized probability drops for masked regions of an inference crop."""
    if isinstance(grid_size, bool) or not isinstance(grid_size, (int, np.integer)) or grid_size <= 0:
        raise ValueError("grid_size must be a positive integer")
    if isinstance(class_index, bool) or not isinstance(class_index, (int, np.integer)):
        raise ValueError("class_index must be an integer")

    cropped = preprocess_image(image.copy())
    baseline = np.asarray(engine.probabilities(cropped), dtype=np.float32)
    if baseline.ndim != 1 or class_index < 0 or class_index >= baseline.size:
        raise ValueError("class_index is outside the probability vector")

    heat = np.zeros((grid_size, grid_size), dtype=np.float32)
    baseline_score = float(baseline[class_index])
    for row in range(grid_size):
        top = row * cropped.height // grid_size
        bottom = (row + 1) * cropped.height // grid_size
        for column in range(grid_size):
            left = column * cropped.width // grid_size
            right = (column + 1) * cropped.width // grid_size
            occluded = cropped.copy()
            occluded.paste(IMAGENET_MEAN_RGB, (left, top, right, bottom))
            probabilities = np.asarray(engine.probabilities(occluded), dtype=np.float32)
            if probabilities.ndim != 1 or class_index >= probabilities.size:
                raise ValueError("probability vector changed during explanation")
            heat[row, column] = max(0.0, baseline_score - float(probabilities[class_index]))

    maximum_drop = float(heat.max())
    if maximum_drop > 0.0:
        heat /= maximum_drop
    return heat


@dataclass
class _ActiveImage:
    image: Image.Image
    class_index: int | None
    stored_at: float


class ActiveSourceImageStore:
    """Bounded, in-memory source images usable only during a short result session."""

    def __init__(
        self,
        *,
        max_entries: int = 32,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._images: OrderedDict[str, _ActiveImage] = OrderedDict()
        self._lock = threading.Lock()
        self._job_lock = threading.Lock()

    def _discard_expired(self, now: float) -> None:
        expired = [
            scan_id for scan_id, entry in self._images.items()
            if now - entry.stored_at >= self.ttl_seconds
        ]
        for scan_id in expired:
            self._images.pop(scan_id, None)

    def put(self, scan_id: str, image: Image.Image, *, class_index: int | None = None) -> None:
        """Store a detached normalized image and its predicted class temporarily."""
        with self._lock:
            now = self._clock()
            self._discard_expired(now)
            self._images.pop(scan_id, None)
            self._images[scan_id] = _ActiveImage(image.copy(), class_index, now)
            while len(self._images) > self.max_entries:
                self._images.popitem(last=False)

    def get(self, scan_id: str) -> Image.Image | None:
        """Return a detached source-image copy, or ``None`` after expiry/eviction."""
        entry = self._entry(scan_id)
        return entry.image.copy() if entry is not None else None

    def get_for_explanation(self, scan_id: str) -> tuple[Image.Image, int | None] | None:
        entry = self._entry(scan_id)
        if entry is None:
            return None
        return entry.image.copy(), entry.class_index

    def _entry(self, scan_id: str) -> _ActiveImage | None:
        with self._lock:
            self._discard_expired(self._clock())
            entry = self._images.get(scan_id)
            if entry is not None:
                self._images.move_to_end(scan_id)
            return entry

    def remove(self, scan_id: str) -> None:
        with self._lock:
            self._images.pop(scan_id, None)

    def clear(self) -> None:
        with self._lock:
            self._images.clear()

    def try_acquire(self) -> bool:
        """Reserve the single permitted explanation job without blocking a request."""
        return self._job_lock.acquire(blocking=False)

    def release(self) -> None:
        self._job_lock.release()
