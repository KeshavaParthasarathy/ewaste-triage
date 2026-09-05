import random

import numpy as np
import torch

from scripts.train_classifier import seed_everything


def test_seed_everything_repeats_python_numpy_and_torch_sequences():
    seed_everything(20260821)
    first = (random.random(), np.random.random(), torch.rand(3))

    seed_everything(20260821)
    second = (random.random(), np.random.random(), torch.rand(3))

    assert first[0] == second[0]
    assert first[1] == second[1]
    assert torch.equal(first[2], second[2])
