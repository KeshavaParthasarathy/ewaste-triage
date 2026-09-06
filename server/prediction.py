"""Framework-neutral formatting for product inference results."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def prediction_from_probabilities(
    probabilities,
    classes: Sequence[str],
    confidence_floor: float,
) -> dict:
    """Build the stable prediction response shared by every inference backend."""
    probabilities = np.asarray(probabilities)
    order = np.argsort(-probabilities, kind="stable")[:min(3, len(classes))]
    top_index = int(order[0])
    top = classes[top_index]
    top_confidence = float(probabilities[top_index])
    key = top.split("_")[0]
    return {
        "class_name": top,
        "unu_key": key if (key.isdigit() and len(key) == 4) else None,
        "confidence": round(top_confidence, 4),
        "low_confidence": top_confidence < confidence_floor,
        "topk": [
            {
                "class_name": classes[int(index)],
                "confidence": round(float(probabilities[index]), 4),
            }
            for index in order
        ],
    }
