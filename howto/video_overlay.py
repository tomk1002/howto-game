"""Always-on-top video window. The QMediaPlayer it owns is exposed so the
sequence overlay can subscribe to its position/state and stay in sync.

A QGraphicsView+QGraphicsVideoItem pair lets us show only a sub-region of
the source video (the JSON's ``video_meta.crop_view``) without re-encoding.
The scene coordinate space equals source video pixels, so the crop rect
loaded from JSON is fed directly to ``fitInView``.
"""

import os
from PyQt6.QtCore import Qt, QPointF, QRectF, QSizeF, QTimer, QUrl
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QGraphicsView,
    QGraphicsScene,
)

from .frameless import handle_resize_press, handle_resize_move


class VideoOverlayWindow(QWidget):
    def __init__(self, video_path, title='Video', crop_rect=None):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self._drag_pos = None
        self._video_native = QSizeF(1920, 1080)
        if crop_rect and len(crop_rect) == 4:
            self._crop_rect = QRectF(*[float(v) for v in crop_rect])
        else:
            self._crop_rect = None
        self._auto_fit_done = False  # one-shot resize-to-aspect on first frame
        self.setMouseTracking(True)
        self._build_ui(title)

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_item)
        # Auto-loop so the user can keep practicing without alt-tabbing back.
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.video_item.nativeSizeChanged.connect(self._on_native_size)

        if video_path and os.path.exists(video_path):
            self.player.setSource(QUrl.fromLocalFile(os.path.abspath(video_path)))
            self.player.pause()

        self.resize(560, 340)
        self.move(440, 60)

    def _build_ui(self, title):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.frame = QFrame()
        self.frame.setObjectName('container')
        self.frame.setStyleSheet(
            """
            #container {
                background: rgba(11, 13, 16, 230);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 8px;
            }
            QPushButton {
                background: rgba(255,255,255,15);
                border: 1px solid rgba(255,255,255,30);
                border-radius: 4px;
                color: #d7dae0;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
            QPushButton:hover { background: rgba(126,231,135,40); border-color: rgba(126,231,135,120); color: #7ee787; }
            QLabel { color: #d7dae0; font-family: Consolas, monospace; }
            """
        )
        outer.addWidget(self.frame)

        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(8, 6, 8, 8)
        inner.setSpacing(6)

        # header (drag + close)
        header = QHBoxLayout()
        self.lbl_title = QLabel(f'🎥 {title}')
        self.lbl_title.setStyleSheet('color: #79c0ff; font-weight: 600; font-size: 12px;')
        header.addWidget(self.lbl_title, 1)
        self.btn_close = QPushButton('✕')
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.clicked.connect(self.close)
        header.addWidget(self.btn_close)
        inner.addLayout(header)

        # graphics view + video item — scene coords == source video pixels
        self.video_scene = QGraphicsScene(self)
        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_scene.addItem(self.video_item)
        self.video_view = QGraphicsView(self.video_scene)
        self.video_view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.video_view.setBackgroundBrush(QColor('#000'))
        self.video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.video_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.video_view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.video_view.setStyleSheet('background: #000; border-radius: 4px;')
        self.video_view.setMinimumSize(320, 180)
        inner.addWidget(self.video_view, 1)

    # ------------------------------------------------------------------
    # Video sizing — fit either the full frame or the crop rect into view
    # ------------------------------------------------------------------

    def _on_native_size(self, size):
        if size.isValid() and not size.isEmpty():
            self._video_native = QSizeF(size)
            self.video_item.setSize(self._video_native)
            self._fit()
            if not self._auto_fit_done:
                self._auto_fit_done = True
                # Wait one event loop turn so the layout settles before
                # we use video_view.size() to adjust window dims.
                QTimer.singleShot(0, self._fit_window_to_aspect)

    def _visible_rect(self):
        if (self._crop_rect is not None
                and self._crop_rect.width() > 0
                and self._crop_rect.height() > 0):
            return self._crop_rect
        return QRectF(QPointF(0, 0), self._video_native)

    def _fit(self):
        rect = self._visible_rect()
        self.video_scene.setSceneRect(rect)
        self.video_view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _fit_window_to_aspect(self):
        """Resize the window so the video viewport matches the crop's aspect,
        eliminating letterbox bars on initial open."""
        rect = self._visible_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        aspect = rect.width() / rect.height()
        vp = self.video_view.size()
        if vp.width() <= 0 or vp.height() <= 0:
            return
        # Anchor on current viewport width — adjust height to match aspect.
        new_vp_h = max(120, int(vp.width() / aspect))
        delta_h = new_vp_h - vp.height()
        self.resize(self.width(), max(180, self.height() + delta_h))
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    # ------------------------------------------------------------------
    # Frameless window dragging (only via header label)
    # ------------------------------------------------------------------

    def mousePressEvent(self, e):
        # let edges trigger an OS-managed resize first
        if handle_resize_press(self, e):
            return
        if e.button() == Qt.MouseButton.LeftButton:
            # only drag when click lands on the title row, not on the video
            child = self.childAt(e.position().toPoint())
            if child is self.video_view or child is self.video_view.viewport():
                e.ignore()
                return
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
            return
        # update cursor when hovering near edges
        handle_resize_move(self, e)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def closeEvent(self, e):
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except Exception:
            pass
        super().closeEvent(e)
