from pathlib import Path

import cv2
import numpy as np

from frame_sorter.worker import imwrite_unicode


def test_imwrite_unicode(tmp_path: Path):
    out_path = tmp_path / "日本語フォルダ" / "画像テスト.jpg"
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    image[:, :, 1] = 200

    imwrite_unicode(out_path, image)

    assert out_path.exists()
    assert out_path.stat().st_size > 0

    data = np.fromfile(str(out_path), dtype=np.uint8)
    decoded = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[:2] == (20, 30)
