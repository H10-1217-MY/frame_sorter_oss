from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QKeyEvent, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .similarity import native_available
from .worker import VideoWorker


class ImageView(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setText("動画を開いてください")
        self._frame_size: tuple[int, int] | None = None
        self._roi: tuple[int, int, int, int] | None = None

    def set_frame(self, frame: np.ndarray) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(
            rgb.data,
            w,
            h,
            ch * w,
            QImage.Format.Format_RGB888,
        ).copy()
        self._frame_size = (w, h)
        self.setPixmap(QPixmap.fromImage(image))
        self._rescale_pixmap()

    def set_roi(self, x: int, y: int, w: int, h: int) -> None:
        self._roi = (x, y, w, h)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale_pixmap()

    def _rescale_pixmap(self) -> None:
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return
        # 現在表示中の pixmap からの再縮小を避けるため、
        # QLabel 側の拡大縮小はここでは最小限にする。
        self.setScaledContents(False)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._roi or not self._frame_size:
            return

        pix = self.pixmap()
        if pix is None or pix.isNull():
            return

        frame_w, frame_h = self._frame_size
        x, y, rw, rh = self._roi
        if rw <= 0 or rh <= 0:
            return

        scaled = pix.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        sx = scaled.width() / frame_w
        sy = scaled.height() / frame_h
        offset_x = (self.width() - scaled.width()) / 2
        offset_y = (self.height() - scaled.height()) / 2

        painter = QPainter(self)
        pen = QPen(Qt.GlobalColor.red)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(
            int(offset_x + x * sx),
            int(offset_y + y * sy),
            int(rw * sx),
            int(rh * sy),
        )


class MainWindow(QMainWindow):
    open_requested = Signal(str, int, str)
    interval_requested = Signal(int)
    next_requested = Signal()
    classify_requested = Signal(str, int, int, int, int, bool)
    undo_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Frame Sorter")
        self.resize(1200, 820)

        self._current_video: Path | None = None
        self._output_dir: Path | None = None
        self._busy = False

        self.image_view = ImageView()
        self.frame_label = QLabel("Frame: -")
        self.video_info_label = QLabel("Video: -")
        self.native_label = QLabel(
            f"C++ acceleration: {'ON' if native_available() else 'OFF (NumPy fallback)'}"
        )

        self._total_frames = 0
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("0 / 0 frames (0.0%)")

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1_000_000)
        self.interval_spin.setValue(30)

        self.roi_x = self._roi_spin()
        self.roi_y = self._roi_spin()
        self.roi_w = self._roi_spin()
        self.roi_h = self._roi_spin()
        self.crop_roi = QCheckBox("ROI のみ保存")

        for spin in (self.roi_x, self.roi_y, self.roi_w, self.roi_h):
            spin.valueChanged.connect(self._update_roi_overlay)

        open_btn = QPushButton("動画を開く")
        open_btn.clicked.connect(self._open_video)

        output_btn = QPushButton("出力フォルダ")
        output_btn.clicked.connect(self._choose_output)

        next_btn = QPushButton("次へ (Space)")
        next_btn.clicked.connect(self.next_requested.emit)

        undo_btn = QPushButton("Undo (Backspace)")
        undo_btn.clicked.connect(self.undo_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(open_btn)
        buttons.addWidget(output_btn)
        buttons.addWidget(next_btn)
        buttons.addWidget(undo_btn)

        form = QFormLayout()
        form.addRow("表示間隔 (N frame)", self.interval_spin)
        form.addRow("ROI X", self.roi_x)
        form.addRow("ROI Y", self.roi_y)
        form.addRow("ROI W", self.roi_w)
        form.addRow("ROI H", self.roi_h)
        form.addRow("", self.crop_roi)

        help_label = QLabel(
            "1: OK    2: NG    3: Unknown    S: Skip    Backspace: Undo    Space: Next"
        )

        right = QVBoxLayout()
        right.addWidget(self.video_info_label)
        right.addWidget(self.frame_label)
        right.addWidget(self.native_label)
        right.addLayout(form)
        right.addWidget(help_label)
        right.addStretch(1)

        body = QHBoxLayout()
        body.addWidget(self.image_view, 1)
        body.addLayout(right)

        root = QVBoxLayout()
        root.addLayout(buttons)
        root.addLayout(body, 1)
        root.addWidget(self.progress_bar)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self._thread = QThread(self)
        self._worker = VideoWorker()
        self._worker.moveToThread(self._thread)

        self.open_requested.connect(self._worker.open_video)
        self.interval_requested.connect(self._worker.set_interval)
        self.next_requested.connect(self._worker.next_frame)
        self.classify_requested.connect(self._worker.classify)
        self.undo_requested.connect(self._worker.undo)

        self._worker.frame_ready.connect(self._on_frame)
        self._worker.video_opened.connect(self._on_video_opened)
        self._worker.status.connect(self.statusBar().showMessage)
        self._worker.error.connect(self._on_error)
        self._worker.busy_changed.connect(self._set_busy)

        self.interval_spin.valueChanged.connect(self.interval_requested.emit)

        # Register window-level shortcuts so child widgets such as QSpinBox
        # cannot consume Backspace / Space before MainWindow sees them.
        self._undo_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        self._undo_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._undo_shortcut.activated.connect(self.undo_requested.emit)

        self._next_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._next_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._next_shortcut.activated.connect(self.next_requested.emit)

        self._thread.start()

    def _roi_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 100_000)
        return spin

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "出力フォルダを選択")
        if selected:
            self._output_dir = Path(selected)
            self.statusBar().showMessage(f"Output: {selected}")

    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "動画を開く",
            "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.m4v);;All Files (*)",
        )
        if not path:
            return

        self._current_video = Path(path)
        if self._output_dir is None:
            self._output_dir = self._current_video.parent / f"{self._current_video.stem}_dataset"

        self.open_requested.emit(
            str(self._current_video),
            self.interval_spin.value(),
            str(self._output_dir),
        )

    def _on_video_opened(self, info: dict) -> None:
        fps = info.get("fps", 0.0)
        frames = int(info.get("frames", 0) or 0)
        duration = frames / fps if fps > 0 else 0.0
        self._total_frames = frames

        if frames > 0:
            self.progress_bar.setRange(0, max(1, frames - 1))
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(f"0 / {frames:,} frames (0.0%)")
        else:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Frame position unavailable")

        self.video_info_label.setText(
            f"{info['width']}x{info['height']}  "
            f"{fps:.2f} fps  "
            f"{frames} frames  "
            f"{duration:.1f} sec"
        )

    def _on_frame(self, index: int, frame: object, width: int, height: int) -> None:
        frame_np = frame

        if self._total_frames > 0:
            current_display = min(index + 1, self._total_frames)
            percent = (current_display / self._total_frames) * 100.0
            self.progress_bar.setValue(min(index, self.progress_bar.maximum()))
            self.progress_bar.setFormat(
                f"{current_display:,} / {self._total_frames:,} frames ({percent:.1f}%)"
            )
            self.frame_label.setText(
                f"Frame: {index:,} / {max(0, self._total_frames - 1):,}"
            )
        else:
            self.frame_label.setText(f"Frame: {index:,}")

        self.image_view.set_frame(frame_np)
        self._update_roi_overlay()

        self.roi_x.setMaximum(width)
        self.roi_y.setMaximum(height)
        self.roi_w.setMaximum(width)
        self.roi_h.setMaximum(height)

    def _update_roi_overlay(self) -> None:
        self.image_view.set_roi(
            self.roi_x.value(),
            self.roi_y.value(),
            self.roi_w.value(),
            self.roi_h.value(),
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _on_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _classify(self, label: str) -> None:
        if self._busy:
            return
        self.classify_requested.emit(
            label,
            self.roi_x.value(),
            self.roi_y.value(),
            self.roi_w.value(),
            self.roi_h.value(),
            self.crop_roi.isChecked(),
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_1:
            self._classify("OK")
            return
        if event.key() == Qt.Key.Key_2:
            self._classify("NG")
            return
        if event.key() == Qt.Key.Key_3:
            self._classify("Unknown")
            return
        if event.key() == Qt.Key.Key_S:
            self._classify("__SKIP__")
            return
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Space):
            # Handled by QShortcut so they also work while child widgets have focus.
            event.ignore()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._thread.quit()
        self._thread.wait(3000)
        super().closeEvent(event)
