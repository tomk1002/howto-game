"""Always-on-top overlay window that plays back a recording's input sequence.

Layout (top → bottom):
  - Title bar with play/reset/close transport
  - Horizontal timeline strip:
      Top row  : the recorded press sequence drawn as boxes positioned by
                 t_ms along a left→right time axis. The current step (per
                 the playback playhead) is highlighted; passed steps are
                 dimmed; upcoming steps are full color.
      Playhead : a vertical red line that sweeps left→right with playback.
      Bottom row: live user inputs captured via pynput, drawn as markers
                 at the time they arrived relative to playback start.

No game input is injected. The overlay is purely visual.
"""

import os
import time
from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QSizePolicy,
)
from pynput import keyboard, mouse

from .frameless import handle_resize_press, handle_resize_move
from .resources_loader import path_to_absolute


# Empirical compensation for ffmpeg gdigrab startup latency. The input
# recorder logs t_ms relative to its own start, but ffmpeg only begins
# capturing ~300ms later, so video position 0 corresponds to recorder
# time SYNC_OFFSET_MS rather than 0. Adding this to the video position
# before looking up the current step pulls the highlight back into sync
# with what's actually shown on screen.
SYNC_OFFSET_MS = 500


def _extract_steps(events):
    out = []
    for e in events:
        if e.get('type') not in ('key_press', 'mouse_press'):
            continue
        step = {
            't_ms': int(e.get('t_ms', 0)),
            'input': e.get('key') or e.get('button') or '?',
            'type': e['type'],
        }
        # Per-event icon override (highest priority at render time)
        icon_path = e.get('icon')
        if icon_path:
            absolute = path_to_absolute(icon_path)
            if os.path.exists(absolute):
                pix = QPixmap(absolute)
                if not pix.isNull():
                    step['icon_pixmap'] = pix
        out.append(step)
    return out


def _key_label(key):
    try:
        return key.char if key.char else str(key)
    except AttributeError:
        return str(key)


def _strip_prefix(s):
    s = str(s)
    for prefix in ('Key.', 'Button.'):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def _format_input(value):
    s = _strip_prefix(value)
    return s.upper() if len(s) <= 3 else s


# ============================================================
# Horizontal timeline strip
# ============================================================

COLOR_BG = QColor(13, 16, 20, 150)
COLOR_GRID = QColor('#1a1e23')
COLOR_AXIS = QColor('#262b32')
COLOR_TIME_LABEL = QColor('#6b7280')

COLOR_STEP_UPCOMING_FILL = QColor('#1f3d2a')
COLOR_STEP_UPCOMING_BORDER = QColor('#3f7a52')
COLOR_STEP_UPCOMING_TEXT = QColor('#bff0c8')

COLOR_STEP_CURRENT_FILL = QColor('#7ee787')
COLOR_STEP_CURRENT_BORDER = QColor('#a4f0ad')
COLOR_STEP_CURRENT_TEXT = QColor('#0d1014')

COLOR_STEP_PAST_FILL = QColor(60, 60, 60, 120)
COLOR_STEP_PAST_BORDER = QColor(110, 110, 110, 200)
COLOR_STEP_PAST_TEXT = QColor(180, 180, 180, 200)

# user-input boxes (mirror the step-box rendering, blue palette so the user's
# actual presses sit visually parallel to the green demo sequence)
COLOR_USER_FILL = QColor('#142944')
COLOR_USER_BORDER = QColor('#3984c6')
COLOR_USER_TEXT = QColor('#cce6ff')

COLOR_PLAYHEAD = QColor('#ff7b72')


class TimelineStrip(QWidget):
    """Custom horizontal timeline visualizing recorded steps + live user inputs.

    Step boxes are auto-stacked into vertical lanes when their time positions
    would overlap horizontally — so a flurry of inputs in <1s no longer paints
    on top of each other. Lane assignment runs every paint based on the
    current widget width.
    """

    MARGIN_X = 12
    LANE_TOP_Y = 12
    BASE_BOX_HEIGHT = 26
    BASE_BOX_WIDTH = 32
    LANE_GAP = 4
    USER_LANE_GAP = 16
    DEFAULT_LANE_RESERVE = 3   # how many lanes minHeight reserves room for

    SCALE_STEPS = (0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)
    DEFAULT_SCALE_INDEX = 1  # 1.0x

    def __init__(self):
        super().__init__()
        self._scale_idx = self.DEFAULT_SCALE_INDEX
        self._update_min_height()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.steps = []
        self.duration_ms = 1000
        self.playhead_ms = 0
        self.current_step = -1
        self.user_inputs = []  # list of {t_ms, label}
        self.key_icons = {}  # mapping from uppercase key label -> QPixmap

    @property
    def scale(self):
        return self.SCALE_STEPS[self._scale_idx]

    @property
    def BOX_WIDTH(self):
        return int(self.BASE_BOX_WIDTH * self.scale)

    @property
    def BOX_HEIGHT(self):
        return int(self.BASE_BOX_HEIGHT * self.scale)

    def adjust_scale(self, delta):
        new_idx = max(0, min(len(self.SCALE_STEPS) - 1, self._scale_idx + delta))
        if new_idx == self._scale_idx:
            return False
        self._scale_idx = new_idx
        self._update_min_height()
        self.updateGeometry()
        self.update()
        return True

    USER_LANE_RESERVE = 2

    def _update_min_height(self):
        step_block = self.DEFAULT_LANE_RESERVE * (self.BOX_HEIGHT + self.LANE_GAP)
        user_block = self.USER_LANE_RESERVE * (self.BOX_HEIGHT + self.LANE_GAP)
        h = (
            self.LANE_TOP_Y
            + step_block
            + 6                         # space before axis
            + self.USER_LANE_GAP        # axis-to-user gap
            + user_block
            + 20                        # time-label row
        )
        self.setMinimumHeight(h)

    def set_key_icons(self, icons):
        """icons: dict mapping uppercase key labels (e.g. 'Q') to QPixmap."""
        self.key_icons = dict(icons or {})
        self.update()

    def set_steps(self, steps):
        self.steps = list(steps)
        last_t = max((s['t_ms'] for s in self.steps), default=0)
        self._steps_duration = max(1000, last_t + 500)
        self.duration_ms = max(self.duration_ms, self._steps_duration)
        self.update()

    def ensure_duration(self, ms):
        """Extend the timeline so a t_ms ≤ ``ms`` event is in-bounds.
        Used when video length or live user input runs past the last demo step."""
        ms = int(max(0, ms))
        if ms > self.duration_ms:
            self.duration_ms = ms
            self.update()

    def set_playhead(self, ms):
        self.playhead_ms = int(max(0, ms))
        cur = -1
        for i, s in enumerate(self.steps):
            if s['t_ms'] <= self.playhead_ms:
                cur = i
            else:
                break
        self.current_step = cur
        self.update()

    def add_user_input(self, t_ms, label):
        t = int(max(0, t_ms))
        self.user_inputs.append({'t_ms': t, 'label': label})
        # cap memory
        if len(self.user_inputs) > 200:
            self.user_inputs = self.user_inputs[-200:]
        # grow the strip if the user pressed past the demo's end
        if t + 200 > self.duration_ms:
            self.duration_ms = t + 200
        self.update()

    def clear_user_inputs(self):
        self.user_inputs = []
        self.update()

    def _x_for(self, t_ms, plot_w):
        return self.MARGIN_X + (t_ms / self.duration_ms) * plot_w

    @staticmethod
    def _draw_label_on_icon(painter, box, text, font, is_past):
        """Overlay the key label semi-transparently over an icon. Outline + fill
        so the text stays legible on any spell art."""
        if not text:
            return
        painter.save()
        painter.setOpacity(0.45 if is_past else 0.78)
        painter.setFont(font)
        # cheap 4-direction outline — black halo behind white fill
        painter.setPen(QColor(0, 0, 0, 230))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(box.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _assign_lanes(self, items, plot_w):
        """Greedy left-to-right lane packing for any iterable of {t_ms} dicts."""
        lane_right_edges = []
        lanes = []
        half_w = self.BOX_WIDTH / 2
        pad = 2
        for it in items:
            cx = self._x_for(it['t_ms'], plot_w)
            box_left = cx - half_w
            box_right = cx + half_w
            chosen = -1
            for i, last_r in enumerate(lane_right_edges):
                if last_r + pad <= box_left:
                    lane_right_edges[i] = box_right
                    chosen = i
                    break
            if chosen == -1:
                lane_right_edges.append(box_right)
                chosen = len(lane_right_edges) - 1
            lanes.append(chosen)
        return lanes, max(len(lane_right_edges), 1)

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), COLOR_BG)

        plot_w = max(self.width() - 2 * self.MARGIN_X, 100)
        step_lanes, n_step_lanes = self._assign_lanes(self.steps, plot_w)
        user_lanes, n_user_lanes = self._assign_lanes(self.user_inputs, plot_w)
        step_block_h = n_step_lanes * self.BOX_HEIGHT + (n_step_lanes - 1) * self.LANE_GAP
        user_block_h = max(0, n_user_lanes * self.BOX_HEIGHT + (n_user_lanes - 1) * self.LANE_GAP)
        axis_y = self.LANE_TOP_Y + step_block_h + 6
        user_top_y = axis_y + self.USER_LANE_GAP
        grid_bottom = user_top_y + user_block_h + 4

        # --- time grid ---
        painter.setPen(QPen(COLOR_GRID, 1))
        for t in range(0, self.duration_ms + 1, 500):
            x = int(self._x_for(t, plot_w))
            painter.drawLine(x, self.LANE_TOP_Y, x, grid_bottom)

        # axis line
        painter.setPen(QPen(COLOR_AXIS, 1))
        painter.drawLine(self.MARGIN_X, axis_y, self.MARGIN_X + plot_w, axis_y)

        # second labels
        painter.setPen(QPen(COLOR_TIME_LABEL))
        painter.setFont(QFont('Consolas', 8))
        for t in range(0, self.duration_ms + 1, 1000):
            x = int(self._x_for(t, plot_w))
            painter.drawText(x + 2, self.height() - 4, f'{t / 1000:.0f}s')

        # --- step boxes (with lane stacking) ---
        text_pt = max(9, int(11 * self.scale))
        text_font = QFont('Consolas', text_pt, QFont.Weight.Bold)
        painter.setFont(text_font)
        for i, s in enumerate(self.steps):
            lane = step_lanes[i]
            cx = self._x_for(s['t_ms'], plot_w)
            y = self.LANE_TOP_Y + lane * (self.BOX_HEIGHT + self.LANE_GAP)
            box = QRectF(cx - self.BOX_WIDTH / 2, y, self.BOX_WIDTH, self.BOX_HEIGHT)

            is_current = (i == self.current_step)
            is_past = (self.playhead_ms > s['t_ms']) and not is_current

            label = _format_input(s['input'])
            text = label[:4]
            # priority: per-event icon > per-key mapping > none
            icon = s.get('icon_pixmap') or self.key_icons.get(label.upper())

            if icon is not None and not icon.isNull():
                # icon mode — render the spell sprite, dim past, glow current
                painter.save()
                if is_past:
                    painter.setOpacity(0.35)
                elif not is_current:
                    painter.setOpacity(0.85)
                pad = max(2, int(3 * self.scale))
                w = int(self.BOX_WIDTH - pad * 2)
                h = int(self.BOX_HEIGHT - pad * 2)
                scaled = icon.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                tx = box.x() + (self.BOX_WIDTH - scaled.width()) / 2
                ty = y + (self.BOX_HEIGHT - scaled.height()) / 2
                painter.drawPixmap(int(tx), int(ty), scaled)
                painter.restore()
                # key label overlay — semi-transparent on top of icon
                self._draw_label_on_icon(painter, box, text, text_font, is_past)
                # state border (drawn at full opacity over the icon)
                if is_current:
                    painter.setPen(QPen(COLOR_STEP_CURRENT_BORDER, 2))
                    painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    painter.drawRoundedRect(box, 5, 5)
                elif is_past:
                    painter.setPen(QPen(COLOR_STEP_PAST_BORDER, 1))
                    painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    painter.drawRoundedRect(box, 5, 5)
                painter.setFont(text_font)
            else:
                # text fallback (no icon for this key)
                if is_current:
                    fill, border, text_color = COLOR_STEP_CURRENT_FILL, COLOR_STEP_CURRENT_BORDER, COLOR_STEP_CURRENT_TEXT
                elif is_past:
                    fill, border, text_color = COLOR_STEP_PAST_FILL, COLOR_STEP_PAST_BORDER, COLOR_STEP_PAST_TEXT
                else:
                    fill, border, text_color = COLOR_STEP_UPCOMING_FILL, COLOR_STEP_UPCOMING_BORDER, COLOR_STEP_UPCOMING_TEXT
                painter.setBrush(fill)
                painter.setPen(QPen(border, 1.5))
                painter.drawRoundedRect(box, 5, 5)
                painter.setPen(QPen(text_color))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

        # --- user input boxes (mirror step boxes, blue palette) ---
        painter.setFont(text_font)
        max_t = self.duration_ms
        for i, evt in enumerate(self.user_inputs):
            t = evt['t_ms']
            if t > max_t:
                continue
            lane = user_lanes[i]
            cx = self._x_for(t, plot_w)
            y = user_top_y + lane * (self.BOX_HEIGHT + self.LANE_GAP)
            box = QRectF(cx - self.BOX_WIDTH / 2, y, self.BOX_WIDTH, self.BOX_HEIGHT)
            label = _format_input(evt['label'])
            text = label[:4]
            icon = self.key_icons.get(label.upper())

            if icon is not None and not icon.isNull():
                painter.save()
                painter.setOpacity(0.92)
                pad = max(2, int(3 * self.scale))
                w = int(self.BOX_WIDTH - pad * 2)
                h = int(self.BOX_HEIGHT - pad * 2)
                scaled = icon.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                tx = box.x() + (self.BOX_WIDTH - scaled.width()) / 2
                ty = y + (self.BOX_HEIGHT - scaled.height()) / 2
                painter.drawPixmap(int(tx), int(ty), scaled)
                painter.restore()
                self._draw_label_on_icon(painter, box, text, text_font, False)
                painter.setPen(QPen(COLOR_USER_BORDER, 2))
                painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                painter.drawRoundedRect(box, 5, 5)
                painter.setFont(text_font)
            else:
                painter.setBrush(COLOR_USER_FILL)
                painter.setPen(QPen(COLOR_USER_BORDER, 1.5))
                painter.drawRoundedRect(box, 5, 5)
                painter.setPen(QPen(COLOR_USER_TEXT))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

        # --- playhead ---
        if self.playhead_ms is not None:
            x = int(self._x_for(self.playhead_ms, plot_w))
            painter.setPen(QPen(COLOR_PLAYHEAD, 2))
            painter.drawLine(x, self.LANE_TOP_Y - 2, x, grid_bottom)


# ============================================================
# Player window
# ============================================================

class PlayerWindow(QWidget):
    # Cross-thread relay: pynput callbacks fire on a non-Qt thread without an
    # event loop, so QTimer.singleShot from there never delivers. Emitting
    # a Qt signal auto-queues to the receiver's (main) thread instead.
    user_input_received = pyqtSignal(str)

    def __init__(self, events, title='HowTo', media_player=None, key_icons=None):
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
        self._drag_pos = None
        self.setMouseTracking(True)

        self._media_player = media_player

        self._build_ui(title)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        if self._media_player is not None:
            self._media_player.positionChanged.connect(self._on_external_position)
            self._media_player.playbackStateChanged.connect(self._on_external_state)
            self._media_player.durationChanged.connect(self._on_external_duration)

        self.user_input_received.connect(self._record_user_input)
        self._kb_listener = keyboard.Listener(on_press=self._on_user_key)
        self._mouse_listener = mouse.Listener(on_click=self._on_user_click)
        self._kb_listener.start()
        self._mouse_listener.start()

        # initial size — wide for horizontal timeline; height accommodates ~3 lanes
        self.resize(760, 200)
        self.move(60, 60)

        self.timeline_strip.set_steps(self.steps)
        self.timeline_strip.set_playhead(0)
        # Always pass through; empty dict → text fallback per-step in paintEvent.
        self.timeline_strip.set_key_icons(key_icons or {})

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
                background: rgba(11, 13, 16, 150);
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
        self.lbl_input_count = QLabel('입력 0')
        self.lbl_input_count.setStyleSheet('color: #79c0ff; font-size: 11px;')
        self.lbl_input_count.setToolTip('pynput가 캡처한 키/마우스 입력 누적 수')
        header.addWidget(self.lbl_input_count)
        self.btn_play = QPushButton('▶')
        self.btn_play.setFixedSize(28, 22)
        self.btn_play.clicked.connect(self._toggle_play)
        header.addWidget(self.btn_play)
        self.btn_reset = QPushButton('⟲')
        self.btn_reset.setFixedSize(28, 22)
        self.btn_reset.setToolTip('처음으로')
        self.btn_reset.clicked.connect(self._reset)
        header.addWidget(self.btn_reset)
        self.btn_zoom_out = QPushButton('−')
        self.btn_zoom_out.setFixedSize(22, 22)
        self.btn_zoom_out.setToolTip('아이콘 작게')
        self.btn_zoom_out.clicked.connect(lambda: self._zoom(-1))
        header.addWidget(self.btn_zoom_out)
        self.btn_zoom_in = QPushButton('+')
        self.btn_zoom_in.setFixedSize(22, 22)
        self.btn_zoom_in.setToolTip('아이콘 크게')
        self.btn_zoom_in.clicked.connect(lambda: self._zoom(1))
        header.addWidget(self.btn_zoom_in)
        self.btn_close = QPushButton('✕')
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.clicked.connect(self.close)
        header.addWidget(self.btn_close)
        inner.addLayout(header)

        # timeline strip — replaces both the old vertical step list and
        # the recent-inputs label. Steps and live user marks share one
        # left→right time axis.
        self.timeline_strip = TimelineStrip()
        inner.addWidget(self.timeline_strip, 1)

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def _zoom(self, delta):
        if not self.timeline_strip.adjust_scale(delta):
            return
        # If the window is smaller than the strip's new minimum, grow it.
        needed = self.timeline_strip.minimumHeight() + 50  # header + margins
        if self.height() < needed:
            self.resize(self.width(), needed)

    def _toggle_play(self):
        if self._media_player is not None:
            if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._media_player.pause()
            else:
                dur = self._media_player.duration()
                if dur > 0 and self._media_player.position() >= dur - 50:
                    self._media_player.setPosition(0)
                    self.timeline_strip.clear_user_inputs()
                self._media_player.play()
            return
        if self._playing:
            self._stop()
        else:
            self._play()

    def _play(self):
        if not self.steps:
            return
        # restart on new run
        if self.current_step >= len(self.steps) - 1:
            self.current_step = -1
            self.timeline_strip.clear_user_inputs()
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
        else:
            self._stop()
            self._start_time = None
        self.current_step = -1
        self.timeline_strip.set_playhead(0)
        self.timeline_strip.clear_user_inputs()

    def _tick(self):
        if not self._playing or self._start_time is None:
            return
        elapsed_ms = int((time.perf_counter() - self._start_time) * 1000)
        end_ms = (self.steps[-1]['t_ms'] + 800) if self.steps else 1000
        if elapsed_ms > end_ms:
            # auto-loop — restart from 0 without stopping the timer
            self._start_time = time.perf_counter()
            self.timeline_strip.clear_user_inputs()
            elapsed_ms = 0
        self.timeline_strip.set_playhead(elapsed_ms)

    # External (video) time source
    def _on_external_position(self, ms):
        new_t = int(ms) + SYNC_OFFSET_MS
        # When the video loops, position drops sharply backward — clear user
        # marks from the previous run so the new loop starts clean.
        if new_t + 100 < self.timeline_strip.playhead_ms:
            self.timeline_strip.clear_user_inputs()
        self.timeline_strip.set_playhead(new_t)

    def _on_external_duration(self, ms):
        if ms and ms > 0:
            self.timeline_strip.ensure_duration(int(ms) + SYNC_OFFSET_MS)

    def _on_external_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText('⏸')
        else:
            self.btn_play.setText('▶')

    def _current_time_ms(self):
        """Return the current playback time in ms, on the same axis as the
        playhead (so user-input markers line up with the red bar)."""
        if self._media_player is not None:
            return int(self._media_player.position()) + SYNC_OFFSET_MS
        if self._playing and self._start_time is not None:
            return int((time.perf_counter() - self._start_time) * 1000)
        return self.timeline_strip.playhead_ms

    # ------------------------------------------------------------------
    # Live input tracker
    # ------------------------------------------------------------------

    def _on_user_key(self, key):
        self.user_input_received.emit(_strip_prefix(_key_label(key)))

    def _on_user_click(self, _x, _y, button, pressed):
        if not pressed:
            return
        self.user_input_received.emit(_strip_prefix(str(button)))

    def _record_user_input(self, label):
        self.timeline_strip.add_user_input(self._current_time_ms(), label)
        self.lbl_input_count.setText(f'입력 {len(self.timeline_strip.user_inputs)}')

    # ------------------------------------------------------------------
    # Frameless window dragging (only via header area, not the strip)
    # ------------------------------------------------------------------

    def mousePressEvent(self, e):
        if handle_resize_press(self, e):
            return
        if e.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(e.position().toPoint())
            if child is self.timeline_strip:
                e.ignore()
                return
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
            return
        handle_resize_move(self, e)

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
