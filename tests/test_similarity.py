import numpy as np

from frame_sorter.similarity import mean_abs_diff


def test_mean_abs_diff():
    a = np.zeros((10, 10, 3), dtype=np.uint8)
    b = np.full((10, 10, 3), 10, dtype=np.uint8)
    assert mean_abs_diff(a, b) == 10.0
