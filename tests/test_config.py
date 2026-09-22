from frame_sorter.config import Roi


def test_roi_clamp():
    roi = Roi(-10, 50, 500, 500).clamp(320, 240)
    assert roi.x == 0
    assert roi.y == 50
    assert roi.w == 320
    assert roi.h == 190
