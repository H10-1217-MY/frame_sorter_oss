try:
    from . import fast_core
except Exception:
    fast_core = None

__all__ = ["fast_core"]
