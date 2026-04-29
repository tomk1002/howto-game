"""Modal dialog: play the video and let the user drag a crop rectangle on it.

Uses QGraphicsView with a QGraphicsVideoItem so the crop overlay composes
cleanly on top of native video playback. Scene coordinates equal source
video pixel coordinates, so selections need no extra mapping before being
fed to ffmpeg's crop filter.
"""

import os

from PyQt6.QtCore import Qt, QRectF, QPointF, QSizeF, QUrl, pyqtSignal
from PyQt6.QtGui import QPen, QColor, QBrush, QPainter
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsView,
    QGraphicsScene,
)


class _CropView(QGraphicsView):
    """Plays a video and lets the user drag a crop rectangle on it.

    The graphics scene is sized to the source video resolution, so the
    rect coordinates returned by ``selection()`` are already in video
    pixels. Resizing the view re-fits the scene letterboxed.
    """

    selection_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor('#000'))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(640, 360)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._scene.addItem(self.video_item)

        # Dimming rectangles (4 around the crop) — added before crop border so border draws on top.
        self._dim_brush = QBrush(QColor(0, 0, 0, 140))
        self._dim_items = []
        for _ in range(4):
            r = self._scene.addRect(QRectF(), QPen(Qt.PenStyle.NoPen), self._dim_brush)
            r.setZValue(10)
            self._dim_items.append(r)

        # Crop rect border
        self._crop_pen = QPen(QColor('#7ee787'), 0)  # cosmetic 2px
        self._crop_pen.setCosmetic(True)
        self._crop_pen.setWidth(2)
        self._crop_item = self._scene.addRect(QRectF(), self._crop_pen, QBrush(Qt.BrushStyle.NoBrush))
        self._crop_item.setZValue(20)

        self._crop_rect = QRectF()
        self._drag_start = None
        self._video_size = QSizeF(1920, 1080)
        self._set_scene_to_video_size()

        self.video_item.nativeSizeChanged.connect(self._on_native_size)

    # -- size / fit ---

    def _set_scene_to_video_size(self):
        w = max(2.0, self._video_size.width())
        h = max(2.0, self._video_size.height())
        self.video_item.setSize(QSizeF(w, h))
        self.video_item.setPos(0, 0)
        self._scene.setSceneRect(QRectF(0, 0, w, h))
        self._update_overlay()
        self._fit()

    def _fit(self):
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def set_video_size(self, w, h):
        if w <= 0 or h <= 0:
            return
        self._video_size = QSizeF(w, h)
        self._set_scene_to_video_size()

    def _on_native_size(self, size):
        if size.width() > 0 and size.height() > 0:
            self.set_video_size(size.width(), size.height())

    # -- selection ---

    def set_selection(self, x, y, w, h):
        self._crop_rect = QRectF(float(x), float(y), float(w), float(h))
        self._clamp_rect()
        self._update_overlay()
        self.selection_changed.emit()

    def _clamp_rect(self):
        full = QRectF(0, 0, self._video_size.width(), self._video_size.height())
        if self._crop_rect.isNull():
            return
        x = max(0.0, min(full.right() - 2, self._crop_rect.x()))
        y = max(0.0, min(full.bottom() - 2, self._crop_rect.y()))
        w = max(0.0, min(full.width() - x, self._crop_rect.width()))
        h = max(0.0, min(full.height() - y, self._crop_rect.height()))
        self._crop_rect = QRectF(x, y, w, h)

    def selection(self):
        """Returns (x, y, w, h) integer pixels in source video coords, or None."""
        if self._crop_rect.isNull():
            return None
        x = int(round(max(0.0, self._crop_rect.x())))
        y = int(round(max(0.0, self._crop_rect.y())))
        w = int(round(self._crop_rect.width()))
        h = int(round(self._crop_rect.height()))
        if w < 16 or h < 16:
            return None
        # libx264 yuv420p needs even
        w -= w % 2
        h -= h % 2
        return (x, y, w, h)

    def _update_overlay(self):
        self._crop_item.setRect(self._crop_rect)
        full = QRectF(0, 0, self._video_size.width(), self._video_size.height())
        if self._crop_rect.isNull() or self._crop_rect.width() <= 0 or self._crop_rect.height() <= 0:
            # darken everything as a hint (no crop yet)
            self._dim_items[0].setRect(full)
            for r in self._dim_items[1:]:
                r.setRect(QRectF())
            return
        sel = self._crop_rect.intersected(full)
        # top
        self._dim_items[0].setRect(QRectF(full.left(), full.top(), full.width(), sel.top() - full.top()))
        # bottom
        self._dim_items[1].setRect(QRectF(full.left(), sel.bottom(), full.width(), full.bottom() - sel.bottom()))
        # left
        self._dim_items[2].setRect(QRectF(full.left(), sel.top(), sel.left() - full.left(), sel.height()))
        # right
        self._dim_items[3].setRect(QRectF(sel.right(), sel.top(), full.right() - sel.right(), sel.height()))

    # -- mouse: drag to define rectangle ---

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = self.mapToScene(e.position().toPoint())
            x = max(0.0, min(self._video_size.width(), self._drag_start.x()))
            y = max(0.0, min(self._video_size.height(), self._drag_start.y()))
            self._drag_start = QPointF(x, y)
            self._crop_rect = QRectF(self._drag_start, self._drag_start)
            self._update_overlay()
            self.selection_changed.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_start is not None:
            cur = self.mapToScene(e.position().toPoint())
            cx = max(0.0, min(self._video_size.width(), cur.x()))
            cy = max(0.0, min(self._video_size.height(), cur.y()))
            self._crop_rect = QRectF(self._drag_start, QPointF(cx, cy)).normalized()
            self._update_overlay()
            self.selection_changed.emit()
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag_start is not None:
            self._drag_start = None
            e.accept()
            return
        super().mouseReleaseEvent(e)


class CropDialog(QDialog):
    def __init__(self, video_path, video_size=None, initial_crop=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('영상 크롭 영역 선택')
        self.resize(900, 660)

        self._video_path = video_path
        if video_size and len(video_size) >= 2:
            self._video_size = (int(video_size[0]), int(video_size[1]))
        else:
            self._video_size = (1920, 1080)

        self._build_ui()

        self.view.set_video_size(*self._video_size)
        self.view.selection_changed.connect(self._update_spinboxes_from_view)

        # set up player + start looped playback
        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        try:
            self._audio.setVolume(0.0)
        except Exception:
            pass
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self.view.video_item)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(self._video_path)))
        self._player.play()

        if initial_crop and len(initial_crop) == 4:
            self.view.set_selection(*initial_crop)

        self._update_spinboxes_from_view()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.view = _CropView()
        layout.addWidget(self.view, 1)

        # transport row
        transport = QHBoxLayout()
        self.btn_play = QPushButton('⏸ 일시정지')
        self.btn_play.clicked.connect(self._toggle_play)
        transport.addWidget(self.btn_play)
        transport.addStretch(1)
        self.lbl_hint = QLabel('영상 위에서 드래그해 크롭 영역 선택 — 숫자로도 미세 조정 가능')
        self.lbl_hint.setStyleSheet('color: #6b7280;')
        transport.addWidget(self.lbl_hint)
        layout.addLayout(transport)

        # numeric inputs
        form_row = QHBoxLayout()
        form = QFormLayout()
        self.spin_x = QSpinBox()
        self.spin_y = QSpinBox()
        self.spin_w = QSpinBox()
        self.spin_h = QSpinBox()
        for sb in (self.spin_x, self.spin_y, self.spin_w, self.spin_h):
            sb.setRange(0, 99999)
            sb.valueChanged.connect(self._on_spin_changed)
        form.addRow('X', self.spin_x)
        form.addRow('Y', self.spin_y)
        form.addRow('W', self.spin_w)
        form.addRow('H', self.spin_h)
        form_row.addLayout(form, 1)

        side = QVBoxLayout()
        self.lbl_video_size = QLabel(
            f'원본 해상도: {self._video_size[0]} × {self._video_size[1]}'
        )
        self.lbl_video_size.setStyleSheet('color: #6b7280;')
        side.addWidget(self.lbl_video_size)
        self.btn_full = QPushButton('전체로 초기화')
        self.btn_full.clicked.connect(self._reset_full)
        side.addWidget(self.btn_full)
        side.addStretch(1)
        form_row.addLayout(side, 1)

        layout.addLayout(form_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- play/pause / reset --

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.btn_play.setText('▶ 재생')
        else:
            self._player.play()
            self.btn_play.setText('⏸ 일시정지')

    def _reset_full(self):
        w, h = self._video_size
        self.view.set_selection(0, 0, w, h)

    # -- spinbox <-> view sync --

    def _on_spin_changed(self, _v):
        self.view.set_selection(
            self.spin_x.value(), self.spin_y.value(),
            self.spin_w.value(), self.spin_h.value(),
        )

    def _update_spinboxes_from_view(self):
        sel = self.view.selection()
        if not sel:
            return
        x, y, w, h = sel
        for sb, val, m in (
            (self.spin_x, x, self._video_size[0] - 2),
            (self.spin_y, y, self._video_size[1] - 2),
            (self.spin_w, w, self._video_size[0]),
            (self.spin_h, h, self._video_size[1]),
        ):
            sb.blockSignals(True)
            sb.setMaximum(m)
            sb.setValue(val)
            sb.blockSignals(False)

    def selected_crop(self):
        x = self.spin_x.value()
        y = self.spin_y.value()
        w = self.spin_w.value()
        h = self.spin_h.value()
        if w < 16 or h < 16:
            return None
        if x == 0 and y == 0 and w == self._video_size[0] and h == self._video_size[1]:
            return None
        w -= w % 2
        h -= h % 2
        return (x, y, w, h)

    def closeEvent(self, e):
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass
        super().closeEvent(e)
