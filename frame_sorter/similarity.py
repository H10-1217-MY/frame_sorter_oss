from __future__ import annotations

import numpy as np

try:
    from .native_ext import fast_core
except Exception:
    fast_core = None


def native_available() -> bool:
    return fast_core is not None


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Return mean absolute pixel difference in range [0, 255]."""
    if a.shape != b.shape:
        raise ValueError("Input images must have the same shape")

    a = np.ascontiguousarray(a, dtype=np.uint8)
    b = np.ascontiguousarray(b, dtype=np.uint8)

    if fast_core is not None:
        return float(fast_core.mean_abs_diff(a, b))

    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return float(diff.mean())
