"""Always-on-top video window. The QMediaPlayer it owns is exposed so the
sequence overlay can subscribe to its position/state and stay in sync.
"""

import os
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
)


class VideoOverlayWindow(QWidget):
    def __init__(self, video_path, title='Video'):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self._drag_pos = None
        self._build_ui(title)

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        # Auto-loop so the user can keep practicing without alt-tabbing back.
        self.player.setLoops(QMediaPlayer.Loops.Infinite)

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

        # video widget
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet('background: #000; border-radius: 4px;')
        self.video_widget.setMinimumSize(320, 180)
        inner.addWidget(self.video_widget, 1)

    # ------------------------------------------------------------------
    # Frameless window dragging (only via header label)
    # ------------------------------------------------------------------

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # only drag when click lands on the title row, not on the video
            child = self.childAt(e.position().toPoint())
            if child is self.video_widget:
                e.ignore()
                return
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def closeEvent(self, e):
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except Exception:
            pass
        super().closeEvent(e)
