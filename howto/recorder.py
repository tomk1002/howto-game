import time
from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard, mouse


def _key_to_str(key):
    try:
        return key.char if key.char else str(key)
    except AttributeError:
        return str(key)


def _is_f9(key):
    name = _key_to_str(key)
    return name in ('Key.f9',)


class Recorder(QObject):
    """Capture global keyboard/mouse events with timestamps relative to start."""

    event_recorded = pyqtSignal(dict)
    state_changed = pyqtSignal(bool)  # True = recording

    def __init__(self):
        super().__init__()
        self.events = []
        self._start_time = None
        self._kb_listener = None
        self._mouse_listener = None
        self._recording = False

    @property
    def recording(self):
        return self._recording

    def start(self):
        if self._recording:
            return
        self.events = []
        self._start_time = time.perf_counter()
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._kb_listener.start()
        self._mouse_listener.start()
        self._recording = True
        self.state_changed.emit(True)

    def stop(self):
        if not self._recording:
            return self.events
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        self._recording = False
        self.state_changed.emit(False)
        return self.events

    def toggle(self):
        if self._recording:
            self.stop()
        else:
            self.start()

    def _t_ms(self):
        return int((time.perf_counter() - self._start_time) * 1000)

    def _emit_event(self, evt):
        self.events.append(evt)
        self.event_recorded.emit(evt)

    def _on_key_press(self, key):
        if _is_f9(key):
            return
        self._emit_event({
            't_ms': self._t_ms(),
            'type': 'key_press',
            'key': _key_to_str(key),
        })

    def _on_key_release(self, key):
        if _is_f9(key):
            return
        self._emit_event({
            't_ms': self._t_ms(),
            'type': 'key_release',
            'key': _key_to_str(key),
        })

    def _on_click(self, x, y, button, pressed):
        self._emit_event({
            't_ms': self._t_ms(),
            'type': 'mouse_press' if pressed else 'mouse_release',
            'button': str(button),
            'x': x,
            'y': y,
        })

    def _on_scroll(self, x, y, dx, dy):
        self._emit_event({
            't_ms': self._t_ms(),
            'type': 'scroll',
            'dx': dx,
            'dy': dy,
        })


class HotkeyToggle(QObject):
    """Listen for a global hotkey on a background thread and emit a Qt signal."""

    triggered = pyqtSignal()

    def __init__(self, key='<f9>'):
        super().__init__()
        self._listener = keyboard.GlobalHotKeys({key: self._fire})
        self._listener.start()

    def _fire(self):
        self.triggered.emit()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
