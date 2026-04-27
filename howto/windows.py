"""Enumerate visible windows for the screen-capture target picker."""

import win32gui
import win32process

# Common system windows to hide from the picker.
_BLOCKLIST_TITLES = {
    'Program Manager',
    'Settings',
    'Microsoft Text Input Application',
    'Windows Input Experience',
    'Windows Shell Experience Host',
}


def get_window_bounds(hwnd):
    """Return (x, y, width, height) for the window. None if minimized/invalid."""
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    # minimized windows have negative coords like -32000
    if left <= -10000 or top <= -10000:
        return None
    return (left, top, width, height)


def list_visible_windows():
    """Return list of {hwnd, title, pid, bounds} for visible top-level windows."""
    windows = []

    def callback(hwnd, _ctx):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or title in _BLOCKLIST_TITLES:
            return True
        bounds = get_window_bounds(hwnd)
        if bounds is None:
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = None
        windows.append({'hwnd': hwnd, 'title': title, 'pid': pid, 'bounds': bounds})
        return True

    win32gui.EnumWindows(callback, None)
    return windows
