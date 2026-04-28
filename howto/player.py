"""Always-on-top overlay window that plays back a recording's input sequence.

Two core widgets stacked in a single frameless, translucent window:
  1. Step sequence — list of input events with cumulative timing, the
     current step (according to elapsed playback time) highlighted.
  2. Live input tracker — last N keys/buttons the user pressed, captured
     via pynput so it works while the game has focus.

No game input is injected. The overlay is purely visual; the user
matches the displayed timing by hand.
"""

import time
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
)
from pynput import keyboard, mouse


def _extract_steps(events):
    """Keep only press events; carry over absolute t_ms for display."""
    out = []
    for e in events:
        if e.get('type') not in ('key_press', 'mouse_press'):
            continue
        out.append({
            't_ms': int(e.get('t_ms', 0)),
            'input': e.get('key') or e.get('button') or '?',
            'type': e['type'],
        })
    return out


def _key_label(key):
    try:
        return key.char if key.char else str(key)
    except AttributeError:
        return str(key)


class PlayerWindow(QWidget):
    def __init__(self, events, title='HowTo', media_player=None):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.steps = _extract_steps(events)
        self.current_step = -1
        self._start_time = None
        self._playing = False

        self.recent_inputs = []
        self._drag_pos = None

        # External media_player (from VideoOverlayWindow) drives time when present.
        self._media_player = media_player

        self._build_ui(title)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        if self._media_player is not None:
            self._media_player.positionChanged.connect(self._on_external_position)
            self._media_player.playbackStateChanged.connect(self._on_external_state)

        # input listeners (read-only — never injects)
        self._kb_listener = keyboard.Listener(on_press=self._on_user_key)
        self._mouse_listener = mouse.Listener(on_click=self._on_user_click)
        self._kb_listener.start()
        self._mouse_listener.start()

        # default size + position
        self.resize(360, max(280, 80 + 18 * min(len(self.steps), 18)))
        self.move(60, 60)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self, title):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

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
                padding: 0;
            }
            QPushButton:hover { background: rgba(126,231,135,40); border-color: rgba(126,231,135,120); color: #7ee787; }
            QLabel { color: #d7dae0; font-family: Consolas, monospace; }
            """
        )
        outer.addWidget(self.frame)

        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(10, 8, 10, 10)
        inner.setSpacing(6)

        # header (drag handle + transport)
        header = QHBoxLayout()
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet('color: #7ee787; font-weight: 600; font-size: 12px;')
        header.addWidget(self.lbl_title, 1)
        self.btn_play = QPushButton('▶')
        self.btn_play.setFixedSize(28, 22)
        self.btn_play.clicked.connect(self._toggle_play)
        header.addWidget(self.btn_play)
        self.btn_reset = QPushButton('⟲')
        self.btn_reset.setFixedSize(28, 22)
        self.btn_reset.setToolTip('처음으로')
        self.btn_reset.clicked.connect(self._reset)
        header.addWidget(self.btn_reset)
        self.btn_close = QPushButton('✕')
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.clicked.connect(self.close)
        header.addWidget(self.btn_close)
        inner.addLayout(header)

        # divider
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setStyleSheet('color: rgba(255,255,255,25);')
        inner.addWidget(rule)

        # sequence (rendered as rich text)
        self.lbl_sequence = QLabel('')
        self.lbl_sequence.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_sequence.setWordWrap(False)
        self.lbl_sequence.setStyleSheet('font-size: 12px; color: #d7dae0;')
        self.lbl_sequence.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        inner.addWidget(self.lbl_sequence, 1)

        # divider
        rule2 = QFrame()
        rule2.setFrameShape(QFrame.Shape.HLine)
        rule2.setStyleSheet('color: rgba(255,255,255,25);')
        inner.addWidget(rule2)

        # input tracker
        self.lbl_inputs = QLabel('입력 대기 중…')
        self.lbl_inputs.setStyleSheet('color: rgba(255,255,255,150); font-size: 11px;')
        inner.addWidget(self.lbl_inputs)

        self._render_sequence()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_sequence(self):
        if not self.steps:
            self.lbl_sequence.setText(
                '<span style="color:#888;">no press events in this recording</span>'
            )
            return

        rows = []
        for i, s in enumerate(self.steps):
            is_cur = (i == self.current_step)
            arrow = '▶ ' if is_cur else '  '
            row_color = '#7ee787' if is_cur else '#d7dae0'
            weight = '600' if is_cur else '400'
            t_text = f'+{s["t_ms"]:>5}ms'
            inp_text = self._format_input(s)
            line = (
                f'<div style="color:{row_color}; font-weight:{weight}; padding:1px 0;">'
                f'{arrow}<span style="color:#6b7280;">{i+1:>2}.</span> '
                f'<span style="color:#f2cc60;">{t_text}</span>  '
                f'<span style="font-weight:700;">{inp_text}</span>'
                f'</div>'
            )
            rows.append(line)
        self.lbl_sequence.setText(''.join(rows))

    @staticmethod
    def _format_input(step):
        s = str(step['input'])
        # strip pynput's "Key." / "Button." prefix for compactness
        for prefix in ('Key.', 'Button.'):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        return s.upper() if len(s) <= 3 else s

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def _toggle_play(self):
        if self._media_player is not None:
            # Route through the external video player; our state follows its signals.
            if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._media_player.pause()
            else:
                # if at end, rewind so play() doesn't no-op
                dur = self._media_player.duration()
                if dur > 0 and self._media_player.position() >= dur - 50:
                    self._media_player.setPosition(0)
                self._media_player.play()
            return
        # No video — internal timer mode.
        if self._playing:
            self._stop()
        else:
            self._play()

    def _play(self):
        if not self.steps:
            return
        if self.current_step >= len(self.steps) - 1:
            self.current_step = -1
        last_done_t = self.steps[self.current_step]['t_ms'] if self.current_step >= 0 else -1
        self._start_time = time.perf_counter() - max(0, last_done_t) / 1000.0
        self._playing = True
        self.btn_play.setText('⏸')
        self._timer.start(16)

    def _stop(self):
        self._playing = False
        self.btn_play.setText('▶')
        self._timer.stop()

    def _reset(self):
        if self._media_player is not None:
            self._media_player.pause()
            self._media_player.setPosition(0)
            self.current_step = -1
            self._render_sequence()
            return
        self._stop()
        self.current_step = -1
        self._start_time = None
        self._render_sequence()

    def _tick(self):
        if not self._playing or self._start_time is None:
            return
        elapsed_ms = int((time.perf_counter() - self._start_time) * 1000)
        self._update_current_step(elapsed_ms)
        if self.steps and elapsed_ms > self.steps[-1]['t_ms'] + 800:
            self._stop()

    def _update_current_step(self, elapsed_ms):
        new_current = -1
        for i, s in enumerate(self.steps):
            if s['t_ms'] <= elapsed_ms:
                new_current = i
            else:
                break
        if new_current != self.current_step:
            self.current_step = new_current
            self._render_sequence()

    # External (video) time source
    def _on_external_position(self, ms):
        self._update_current_step(int(ms))

    def _on_external_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText('⏸')
        else:
            self.btn_play.setText('▶')

    # ------------------------------------------------------------------
    # Live input tracker (pynput callbacks run on background threads;
    # use QTimer.singleShot to bounce to the main thread before touching UI)
    # ------------------------------------------------------------------

    def _on_user_key(self, key):
        label = _key_label(key)
        QTimer.singleShot(0, lambda: self._append_input(label))

    def _on_user_click(self, _x, _y, button, pressed):
        if not pressed:
            return
        label = str(button)
        QTimer.singleShot(0, lambda: self._append_input(label))

    def _append_input(self, label):
        for prefix in ('Key.', 'Button.'):
            if label.startswith(prefix):
                label = label[len(prefix):]
                break
        self.recent_inputs.append(label.upper() if len(label) <= 3 else label)
        self.recent_inputs = self.recent_inputs[-12:]
        self.lbl_inputs.setText('입력  ' + '  '.join(self.recent_inputs))

    # ------------------------------------------------------------------
    # Frameless window dragging
    # ------------------------------------------------------------------

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def closeEvent(self, e):
        self._stop()
        try:
            if self._kb_listener:
                self._kb_listener.stop()
                self._kb_listener = None
            if self._mouse_listener:
                self._mouse_listener.stop()
                self._mouse_listener = None
        except Exception:
            pass
        super().closeEvent(e)
