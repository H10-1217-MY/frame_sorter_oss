from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from .config import Roi



def imwrite_unicode(path: Path, image: np.ndarray) -> None:
    """Write an image safely even when the path contains Unicode characters."""
    suffix = path.suffix.lower() or ".jpg"
    supported = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    if suffix not in supported:
        suffix = ".jpg"

    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise RuntimeError(f"画像のエンコードに失敗しました: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        encoded.tofile(str(path))
    except Exception as exc:
        raise RuntimeError(f"画像の保存に失敗しました: {path}\n{exc}") from exc


@dataclass
class Action:
    frame_index: int
    label: str | None
    saved_path: str | None
    roi: tuple[int, int, int, int] | None


class VideoWorker(QObject):
    frame_ready = Signal(int, object, int, int)
    video_opened = Signal(object)
    status = Signal(str)
    error = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._cap: cv2.VideoCapture | None = None
        self._path: Path | None = None
        self._interval = 30
        self._next_index = 0
        self._current_index = -1
        self._current_frame: np.ndarray | None = None
        self._history: list[Action] = []
        self._output_dir: Path | None = None
        self._busy = False

    def _set_busy(self, value: bool) -> None:
        self._busy = value
        self.busy_changed.emit(value)

    @Slot(str, int, str)
    def open_video(self, path: str, interval: int, output_dir: str) -> None:
        try:
            self._set_busy(True)

            if self._cap is not None:
                self._cap.release()

            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise RuntimeError(f"動画を開けませんでした: {path}")

            self._cap = cap
            self._path = Path(path)
            self._interval = max(1, int(interval))
            self._next_index = 0
            self._current_index = -1
            self._current_frame = None
            self._history.clear()
            self._output_dir = Path(output_dir)
            self._output_dir.mkdir(parents=True, exist_ok=True)

            info = {
                "path": str(self._path),
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
                "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
            }
            self.video_opened.emit(info)
            self._read_index(self._next_index)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._set_busy(False)


    @Slot(str)
    def set_output_dir(self, output_dir: str) -> None:
        """Update save destination without reopening the video."""
        try:
            path = Path(output_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._output_dir = path
            self.status.emit(f"Output: {self._output_dir}")
        except Exception as exc:
            self.error.emit(str(exc))

    @Slot(int)
    def set_interval(self, interval: int) -> None:
        self._interval = max(1, int(interval))

    def _read_index(self, frame_index: int) -> None:
        if self._cap is None:
            return

        self._set_busy(True)
        try:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
            ok, frame = self._cap.read()
            if not ok or frame is None:
                self.status.emit("動画の末尾に到達しました")
                return

            self._current_index = int(frame_index)
            self._current_frame = frame
            self._next_index = self._current_index + self._interval

            h, w = frame.shape[:2]
            self.frame_ready.emit(self._current_index, frame, w, h)
            self.status.emit(f"Frame {self._current_index}")
        finally:
            self._set_busy(False)

    @Slot()
    def next_frame(self) -> None:
        if self._busy:
            return
        try:
            self._read_index(self._next_index)
        except Exception as exc:
            self.error.emit(str(exc))

    @Slot(str, int, int, int, int, bool)
    def classify(
        self,
        label: str,
        roi_x: int,
        roi_y: int,
        roi_w: int,
        roi_h: int,
        crop_to_roi: bool,
    ) -> None:
        if self._busy or self._current_frame is None or self._path is None:
            return

        try:
            self._set_busy(True)

            frame = self._current_frame
            h, w = frame.shape[:2]
            roi = Roi(roi_x, roi_y, roi_w, roi_h).clamp(w, h)

            image_to_save = frame
            roi_tuple = None

            if roi.enabled:
                roi_tuple = (roi.x, roi.y, roi.w, roi.h)
                if crop_to_roi:
                    image_to_save = frame[
                        roi.y : roi.y + roi.h,
                        roi.x : roi.x + roi.w,
                    ]

            saved_path = None
            if label != "__SKIP__":
                if self._output_dir is None:
                    raise RuntimeError("出力フォルダが設定されていません")

                label_dir = self._output_dir / label
                label_dir.mkdir(parents=True, exist_ok=True)

                filename = f"{self._path.stem}_f{self._current_index:09d}.jpg"
                out_path = label_dir / filename

                imwrite_unicode(out_path, image_to_save)

                saved_path = str(out_path)
                self.status.emit(f"Saved: {out_path}")

            action = Action(
                frame_index=self._current_index,
                label=None if label == "__SKIP__" else label,
                saved_path=saved_path,
                roi=roi_tuple,
            )
            self._history.append(action)
            self._append_log(action, event="classify" if label != "__SKIP__" else "skip")

        except Exception as exc:
            self.error.emit(str(exc))
            self._set_busy(False)
            return

        self._set_busy(False)
        self.next_frame()

    def _append_log(self, action: Action, event: str) -> None:
        if self._output_dir is None:
            return
        record = {
            "time_unix": time.time(),
            "event": event,
            "frame_index": action.frame_index,
            "label": action.label,
            "saved_path": action.saved_path,
            "roi": action.roi,
        }
        with (self._output_dir / "session.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @Slot()
    def undo(self) -> None:
        if self._busy or not self._history:
            self.status.emit("Undo できる操作がありません")
            return

        try:
            action = self._history.pop()

            if action.saved_path:
                path = Path(action.saved_path)
                if path.exists():
                    path.unlink()

            self._append_log(action, event="undo")

            # Undo 対象フレームを再表示し、再分類できるようにする
            self._read_index(action.frame_index)
            self.status.emit(f"Undo: Frame {action.frame_index}")
        except Exception as exc:
            self.error.emit(str(exc))
