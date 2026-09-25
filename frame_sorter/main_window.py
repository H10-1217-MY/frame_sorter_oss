from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QThread, Signal
from PySide6.QtGui import QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .label_config import LabelConfig, LabelDefinition, RESERVED_KEYS
from .similarity import native_available
from .worker import VideoWorker


class LabelDialog(QDialog):
    def __init__(self, parent=None, initial=None, used_keys=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("分類を追加" if initial is None else "分類を編集")
        self.used_keys = {k.upper() for k in (used_keys or set())}

        self.name_edit = QLineEdit(initial.name if initial else "")
        self.folder_edit = QLineEdit(initial.folder if initial else "")
        self.key_edit = QLineEdit(initial.key if initial else "")
        self.key_edit.setMaxLength(1)

        form = QFormLayout()
        form.addRow("表示名", self.name_edit)
        form.addRow("保存フォルダ名", self.folder_edit)
        form.addRow("キー", self.key_edit)

        note = QLabel("キーは1文字。Space / Backspace は予約済みです。")
        note.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        folder = LabelConfig.sanitize_folder_name(self.folder_edit.text())
        key = self.key_edit.text().strip().upper()

        if not name:
            QMessageBox.warning(self, "入力エラー", "表示名を入力してください。")
            return
        if not key or len(key) != 1:
            QMessageBox.warning(self, "入力エラー", "キーは1文字で入力してください。")
            return
        if key in RESERVED_KEYS:
            QMessageBox.warning(self, "入力エラー", f"{key} は予約済みです。")
            return
        if key in self.used_keys:
            QMessageBox.warning(self, "入力エラー", f"キー {key} は既に使われています。")
            return

        self.folder_edit.setText(folder)
        self.key_edit.setText(key)
        self.accept()

    def value(self) -> LabelDefinition:
        return LabelDefinition(
            name=self.name_edit.text().strip(),
            folder=LabelConfig.sanitize_folder_name(self.folder_edit.text()),
            key=self.key_edit.text().strip().upper(),
        )


class ImageView(QLabel):
    roi_changed = Signal(int, int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setText("動画を開いてください")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._frame_size = None
        self._roi = None
        self._source_pixmap = None
        self._dragging = False
        self._drag_start = None
        self._drag_end = None

    def set_frame(self, frame: np.ndarray) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        self._frame_size = (w, h)
        self._source_pixmap = QPixmap.fromImage(image)
        self._update_scaled_pixmap()

    def set_roi(self, x: int, y: int, w: int, h: int) -> None:
        self._roi = (x, y, w, h) if w > 0 and h > 0 else None
        self.update()

    def clear_roi(self) -> None:
        self._roi = None
        self._dragging = False
        self._drag_start = None
        self._drag_end = None
        self.roi_changed.emit(0, 0, 0, 0)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        scaled = self._source_pixmap.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.update()

    def _pixmap_rect(self):
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return None
        x = (self.width() - pix.width()) // 2
        y = (self.height() - pix.height()) // 2
        return QRect(x, y, pix.width(), pix.height())

    def _clamp_to_pixmap(self, point: QPoint):
        rect = self._pixmap_rect()
        if rect is None:
            return None
        x = max(rect.left(), min(point.x(), rect.right()))
        y = max(rect.top(), min(point.y(), rect.bottom()))
        return QPoint(x, y)

    def _widget_rect_to_source_roi(self, rect: QRect):
        pix_rect = self._pixmap_rect()
        if pix_rect is None or self._frame_size is None:
            return None
        clipped = rect.normalized().intersected(pix_rect)
        if clipped.width() < 2 or clipped.height() < 2:
            return None
        frame_w, frame_h = self._frame_size
        sx = frame_w / pix_rect.width()
        sy = frame_h / pix_rect.height()
        x = int(round((clipped.left() - pix_rect.left()) * sx))
        y = int(round((clipped.top() - pix_rect.top()) * sy))
        w = int(round(clipped.width() * sx))
        h = int(round(clipped.height() * sy))
        x = max(0, min(x, frame_w - 1))
        y = max(0, min(y, frame_h - 1))
        w = max(1, min(w, frame_w - x))
        h = max(1, min(h, frame_h - y))
        return x, y, w, h

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            pix_rect = self._pixmap_rect()
            if pix_rect is not None and pix_rect.contains(point):
                self._dragging = True
                self._drag_start = self._clamp_to_pixmap(point)
                self._drag_end = self._drag_start
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_start is not None:
            self._drag_end = self._clamp_to_pixmap(event.position().toPoint())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging and self._drag_start is not None:
            self._drag_end = self._clamp_to_pixmap(event.position().toPoint())
            self._dragging = False
            if self._drag_end is not None:
                roi = self._widget_rect_to_source_roi(QRect(self._drag_start, self._drag_end).normalized())
                if roi is not None:
                    self._roi = roi
                    self.roi_changed.emit(*roi)
            self._drag_start = None
            self._drag_end = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        pen = QPen(Qt.GlobalColor.red)
        pen.setWidth(2)
        painter.setPen(pen)
        if self._dragging and self._drag_start is not None and self._drag_end is not None:
            painter.drawRect(QRect(self._drag_start, self._drag_end).normalized())
            return
        if not self._roi or not self._frame_size:
            return
        pix_rect = self._pixmap_rect()
        if pix_rect is None:
            return
        frame_w, frame_h = self._frame_size
        x, y, rw, rh = self._roi
        if rw <= 0 or rh <= 0:
            return
        sx = pix_rect.width() / frame_w
        sy = pix_rect.height() / frame_h
        painter.drawRect(
            int(pix_rect.left() + x * sx),
            int(pix_rect.top() + y * sy),
            max(1, int(rw * sx)),
            max(1, int(rh * sy)),
        )


class MainWindow(QMainWindow):
    open_requested = Signal(str, int, str)
    interval_requested = Signal(int)
    next_requested = Signal()
    classify_requested = Signal(str, int, int, int, int, bool)
    output_dir_requested = Signal(str)
    undo_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Frame Sorter")
        self.resize(1280, 840)

        self._current_video = None
        self._output_dir = None
        self._busy = False
        self._total_frames = 0
        self._label_shortcuts = []
        self._label_config = None

        self.image_view = ImageView()
        self.frame_label = QLabel("Frame: -")
        self.video_info_label = QLabel("Video: -")
        self.native_label = QLabel(
            f"C++ acceleration: {'ON' if native_available() else 'OFF (NumPy fallback)'}"
        )

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1_000_000)
        self.interval_spin.setValue(30)

        self.roi_x = self._roi_spin()
        self.roi_y = self._roi_spin()
        self.roi_w = self._roi_spin()
        self.roi_h = self._roi_spin()
        for spin in (self.roi_x, self.roi_y, self.roi_w, self.roi_h):
            spin.setReadOnly(True)
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            spin.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.crop_roi = QCheckBox("ROI のみ保存")
        self.clear_roi_btn = QPushButton("ROIをクリア")
        self.clear_roi_btn.clicked.connect(self.image_view.clear_roi)
        self.image_view.roi_changed.connect(self._on_roi_changed)

        open_btn = QPushButton("動画を開く")
        open_btn.clicked.connect(self._open_video)
        output_btn = QPushButton("プロジェクト/出力先")
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
        form.addRow("", self.clear_roi_btn)
        roi_help = QLabel("画像上を左ドラッグしてROIを指定します。")
        roi_help.setWordWrap(True)

        self.label_list = QListWidget()
        self.label_list.setMinimumHeight(180)

        add_label_btn = QPushButton("＋ 分類を追加")
        add_label_btn.clicked.connect(self._add_label)
        edit_label_btn = QPushButton("編集")
        edit_label_btn.clicked.connect(self._edit_selected_label)
        delete_label_btn = QPushButton("削除")
        delete_label_btn.clicked.connect(self._delete_selected_label)

        label_buttons = QHBoxLayout()
        label_buttons.addWidget(add_label_btn)
        label_buttons.addWidget(edit_label_btn)
        label_buttons.addWidget(delete_label_btn)

        label_help = QLabel(
            "キーを押すと、その分類フォルダへ保存します。\n"
            "設定は annotation_config.json に保存されます。"
        )
        label_help.setWordWrap(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0 / 0 frames (0.0%)")

        right = QVBoxLayout()
        right.addWidget(self.video_info_label)
        right.addWidget(self.frame_label)
        right.addWidget(self.native_label)
        right.addLayout(form)
        right.addWidget(roi_help)
        right.addWidget(QLabel("分類 / 保存先"))
        right.addWidget(self.label_list)
        right.addLayout(label_buttons)
        right.addWidget(label_help)
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
        self.output_dir_requested.connect(self._worker.set_output_dir)
        self.undo_requested.connect(self._worker.undo)

        self._worker.frame_ready.connect(self._on_frame)
        self._worker.video_opened.connect(self._on_video_opened)
        self._worker.status.connect(self.statusBar().showMessage)
        self._worker.error.connect(self._on_error)
        self._worker.busy_changed.connect(self._set_busy)
        self.interval_spin.valueChanged.connect(self.interval_requested.emit)

        self._undo_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        self._undo_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._undo_shortcut.activated.connect(self.undo_requested.emit)
        self._next_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._next_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._next_shortcut.activated.connect(self.next_requested.emit)

        self._thread.start()

    def _roi_spin(self):
        spin = QSpinBox()
        spin.setRange(0, 100_000)
        return spin

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "プロジェクト/出力先フォルダを選択")
        if selected:
            self._set_project_dir(Path(selected))

    def _set_project_dir(self, path: Path) -> None:
        self._output_dir = path
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._label_config = LabelConfig(self._output_dir / "annotation_config.json")
        try:
            self._label_config.load()
        except Exception as exc:
            QMessageBox.warning(self, "設定読込エラー", f"annotation_config.json を読み込めませんでした。\n{exc}")
            self._label_config.labels = []
        self._ensure_label_folders()
        self._refresh_labels()

        # Keep the worker-side save destination synchronized even when
        # the project folder is changed after a video has already been opened.
        self.output_dir_requested.emit(str(self._output_dir))
        self.statusBar().showMessage(f"Project: {self._output_dir}")

    def _ensure_label_folders(self) -> None:
        if self._output_dir is None or self._label_config is None:
            return
        for label in self._label_config.labels:
            (self._output_dir / label.folder).mkdir(parents=True, exist_ok=True)

    def _refresh_labels(self) -> None:
        self.label_list.clear()
        for shortcut in self._label_shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._label_shortcuts.clear()

        if self._label_config is None:
            return

        for idx, label in enumerate(self._label_config.labels):
            item = QListWidgetItem(f"[{label.key}]  {label.name}  →  {label.folder}/")
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.label_list.addItem(item)

            shortcut = QShortcut(QKeySequence(label.key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(
                lambda folder=label.folder, name=label.name, key=label.key:
                self._classify(folder, name, key)
            )
            shortcut.activatedAmbiguously.connect(
                lambda key=label.key: self.statusBar().showMessage(
                    f"Shortcut [{key}] is ambiguous", 3000
                )
            )
            self._label_shortcuts.append(shortcut)

    def _save_label_config(self) -> None:
        if self._label_config is None:
            return
        self._label_config.save()
        self._ensure_label_folders()
        self._refresh_labels()

    def _add_label(self) -> None:
        if self._output_dir is None:
            QMessageBox.information(self, "出力先未設定", "先に「プロジェクト/出力先」を選択してください。")
            return
        if self._label_config is None:
            self._set_project_dir(self._output_dir)

        used = {label.normalized_key() for label in self._label_config.labels}
        dialog = LabelDialog(self, used_keys=used)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        label = dialog.value()

        if any(existing.folder == label.folder for existing in self._label_config.labels):
            QMessageBox.warning(self, "重複エラー", f"保存フォルダ {label.folder} は既に使われています。")
            return

        self._label_config.labels.append(label)
        self._save_label_config()

    def _selected_label_index(self):
        item = self.label_list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _edit_selected_label(self) -> None:
        if self._label_config is None:
            return
        idx = self._selected_label_index()
        if idx is None:
            return

        current = self._label_config.labels[idx]
        used = {label.normalized_key() for i, label in enumerate(self._label_config.labels) if i != idx}
        dialog = LabelDialog(self, initial=current, used_keys=used)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.value()

        if any(i != idx and existing.folder == updated.folder for i, existing in enumerate(self._label_config.labels)):
            QMessageBox.warning(self, "重複エラー", f"保存フォルダ {updated.folder} は既に使われています。")
            return

        old_dir = self._output_dir / current.folder if self._output_dir else None
        new_dir = self._output_dir / updated.folder if self._output_dir else None
        self._label_config.labels[idx] = updated
        self._save_label_config()

        if old_dir and new_dir and current.folder != updated.folder and old_dir.exists() and not any(old_dir.iterdir()):
            old_dir.rmdir()

    def _delete_selected_label(self) -> None:
        if self._label_config is None:
            return
        idx = self._selected_label_index()
        if idx is None:
            return
        label = self._label_config.labels[idx]
        answer = QMessageBox.question(
            self, "分類を削除",
            f"「{label.name}」を分類一覧から削除しますか？\n保存済み画像フォルダは削除しません。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._label_config.labels[idx]
        self._save_label_config()

    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "動画を開く", "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.m4v);;All Files (*)",
        )
        if not path:
            return

        self._current_video = Path(path)
        if self._output_dir is None:
            self._set_project_dir(self._current_video.parent / f"{self._current_video.stem}_frame_sorter")

        self.open_requested.emit(
            str(self._current_video), self.interval_spin.value(), str(self._output_dir)
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
            f"{info['width']}x{info['height']}  {fps:.2f} fps  {frames} frames  {duration:.1f} sec"
        )

    def _on_frame(self, index: int, frame: object, width: int, height: int) -> None:
        if self._total_frames > 0:
            current_display = min(index + 1, self._total_frames)
            percent = (current_display / self._total_frames) * 100.0
            self.progress_bar.setValue(min(index, self.progress_bar.maximum()))
            self.progress_bar.setFormat(f"{current_display:,} / {self._total_frames:,} frames ({percent:.1f}%)")
            self.frame_label.setText(f"Frame: {index:,} / {max(0, self._total_frames - 1):,}")
        else:
            self.frame_label.setText(f"Frame: {index:,}")

        self.image_view.set_frame(frame)
        self.roi_x.setMaximum(width)
        self.roi_y.setMaximum(height)
        self.roi_w.setMaximum(width)
        self.roi_h.setMaximum(height)
        self.image_view.set_roi(
            self.roi_x.value(), self.roi_y.value(), self.roi_w.value(), self.roi_h.value()
        )

    def _on_roi_changed(self, x: int, y: int, w: int, h: int) -> None:
        self.roi_x.setValue(x)
        self.roi_y.setValue(y)
        self.roi_w.setValue(w)
        self.roi_h.setValue(h)
        if w > 0 and h > 0:
            self.statusBar().showMessage(f"ROI: x={x}, y={y}, w={w}, h={h}")
        else:
            self.statusBar().showMessage("ROIをクリアしました")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _on_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _classify(self, folder: str, name: str | None = None, key: str | None = None) -> None:
        if self._busy:
            return
        if self._output_dir is None:
            QMessageBox.information(
                self,
                "出力先未設定",
                "先に「プロジェクト/出力先」を選択してください。",
            )
            return

        # Make sure the destination exists, even if it was removed externally.
        destination = self._output_dir / folder
        destination.mkdir(parents=True, exist_ok=True)

        display = name or folder
        prefix = f"[{key}] " if key else ""
        self.statusBar().showMessage(
            f"{prefix}{display} → {destination}", 2500
        )
        self.classify_requested.emit(
            folder,
            self.roi_x.value(), self.roi_y.value(), self.roi_w.value(), self.roi_h.value(),
            self.crop_roi.isChecked(),
        )

    def closeEvent(self, event) -> None:
        self._thread.quit()
        self._thread.wait(3000)
        super().closeEvent(event)
