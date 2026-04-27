from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import QWidget


COLOR_BG = QColor('#161a1e')
COLOR_GRID = QColor('#262b32')
COLOR_AXIS = QColor('#6b7280')
COLOR_KEY_PRESS = QColor('#7ee787')
COLOR_KEY_RELEASE = QColor('#3b6b46')
COLOR_MOUSE_PRESS = QColor('#79c0ff')
COLOR_MOUSE_RELEASE = QColor('#385879')
COLOR_SCROLL = QColor('#f2cc60')
COLOR_LABEL = QColor('#d7dae0')
COLOR_PLAYHEAD = QColor('#ff7b72')


class TimelineWidget(QWidget):
    """Horizontal timeline visualizing recorded input events.

    Layout:
      - X axis = time (ms), 0 at left
      - Y axis = one row per distinct (input source) — keyboard keys grouped, mouse buttons grouped, scroll
      - Each event: small filled rect at its t_ms on its row
    """

    LABEL_WIDTH = 110
    ROW_HEIGHT = 22
    PAD_TOP = 24
    PAD_BOTTOM = 18

    def __init__(self):
        super().__init__()
        self._events = []
        self._duration_ms = 5000
        self._playhead_ms = None
        self.setMinimumHeight(160)
        self.setStyleSheet('background: #161a1e;')

    def set_events(self, events):
        self._events = list(events)
        self._duration_ms = max(
            (e.get('t_ms', 0) for e in self._events),
            default=0,
        ) + 500
        if self._duration_ms < 1000:
            self._duration_ms = 1000
        self.update()

    def append_event(self, evt):
        self._events.append(evt)
        t = evt.get('t_ms', 0)
        if t + 500 > self._duration_ms:
            self._duration_ms = t + 500
        self.update()

    def clear(self):
        self._events = []
        self._duration_ms = 5000
        self._playhead_ms = None
        self.update()

    def set_playhead(self, t_ms):
        self._playhead_ms = t_ms
        self.update()

    def _row_keys(self):
        """Distinct row labels in display order."""
        rows = []
        seen = set()

        def add(label):
            if label not in seen:
                seen.add(label)
                rows.append(label)

        for e in self._events:
            t = e.get('type', '')
            if t.startswith('key_'):
                add(f"key {e.get('key', '?')}")
            elif t.startswith('mouse_'):
                add(f"mouse {e.get('button', '?')}")
            elif t == 'scroll':
                add('scroll')
        return rows

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), COLOR_BG)

        rows = self._row_keys()
        n_rows = max(len(rows), 1)

        plot_x = self.LABEL_WIDTH
        plot_y = self.PAD_TOP
        plot_w = max(self.width() - plot_x - 12, 100)
        plot_h = max(n_rows * self.ROW_HEIGHT, self.ROW_HEIGHT)

        # axis box
        painter.setPen(QPen(COLOR_AXIS, 1))
        painter.drawRect(plot_x, plot_y, plot_w, plot_h)

        # time grid every 500ms
        font = QFont('Consolas', 8)
        painter.setFont(font)
        painter.setPen(QPen(COLOR_GRID, 1))
        for t in range(0, self._duration_ms + 1, 500):
            x = plot_x + int(t / self._duration_ms * plot_w)
            painter.drawLine(x, plot_y, x, plot_y + plot_h)
        painter.setPen(QPen(COLOR_AXIS, 1))
        for t in range(0, self._duration_ms + 1, 1000):
            x = plot_x + int(t / self._duration_ms * plot_w)
            painter.drawText(x + 2, plot_y + plot_h + 12, f"{t / 1000:.0f}s")

        # row labels
        painter.setPen(QPen(COLOR_LABEL, 1))
        for i, label in enumerate(rows):
            y = plot_y + i * self.ROW_HEIGHT + self.ROW_HEIGHT / 2 + 4
            painter.drawText(8, int(y), label[: self.LABEL_WIDTH - 12])

        # event rectangles
        for e in self._events:
            t = e.get('t_ms', 0)
            x = plot_x + (t / self._duration_ms) * plot_w
            etype = e.get('type', '')
            if etype.startswith('key_'):
                row_label = f"key {e.get('key', '?')}"
                color = COLOR_KEY_PRESS if etype == 'key_press' else COLOR_KEY_RELEASE
            elif etype.startswith('mouse_'):
                row_label = f"mouse {e.get('button', '?')}"
                color = COLOR_MOUSE_PRESS if etype == 'mouse_press' else COLOR_MOUSE_RELEASE
            elif etype == 'scroll':
                row_label = 'scroll'
                color = COLOR_SCROLL
            else:
                continue
            row_idx = rows.index(row_label) if row_label in rows else 0
            ry = plot_y + row_idx * self.ROW_HEIGHT + 4
            rh = self.ROW_HEIGHT - 8
            painter.fillRect(QRectF(x - 2, ry, 4, rh), color)

        # playhead
        if self._playhead_ms is not None:
            x = plot_x + (self._playhead_ms / self._duration_ms) * plot_w
            pen = QPen(COLOR_PLAYHEAD, 2)
            painter.setPen(pen)
            painter.drawLine(int(x), plot_y, int(x), plot_y + plot_h)
