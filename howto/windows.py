"""Enumerate visible windows for the screen-capture target picker."""

import ctypes
from ctypes import wintypes

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

# DwmGetWindowAttribute / DWMWA_EXTENDED_FRAME_BOUNDS returns the visible window
# rectangle without the invisible drop-shadow padding that GetWindowRect adds on
# Windows Vista+ (typically 7~8 px sides + bottom). Using this prevents the
# capture region from extending past the actual window edges.
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


class _RECT(ctypes.Structure):
    _fields_ = [
        ('left', ctypes.c_long),
        ('top', ctypes.c_long),
        ('right', ctypes.c_long),
        ('bottom', ctypes.c_long),
    ]


def _dwm_extended_frame_bounds(hwnd):
    rect = _RECT()
    try:
        hresult = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
    except (OSError, AttributeError):
        return None
    if hresult != 0:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _client_bounds(hwnd):
    """Client area in screen coords: excludes title bar, borders, shadow."""
    try:
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
        cw, ch = cr - cl, cb - ct
        if cw <= 0 or ch <= 0:
            return None
        sx, sy = win32gui.ClientToScreen(hwnd, (cl, ct))
        return (sx, sy, cw, ch)
    except Exception:
        return None


def get_window_bounds(hwnd):
    """Return (x, y, width, height) for the visible content area.

    Tries client area first (excludes title bar/border — best for game capture),
    falls back to DWM extended frame bounds (no shadow padding), then to plain
    GetWindowRect.
    """
    bounds = _client_bounds(hwnd)
    if bounds is None:
        coords = _dwm_extended_frame_bounds(hwnd)
        if coords is None:
            try:
                coords = win32gui.GetWindowRect(hwnd)
            except Exception:
                return None
        left, top, right, bottom = coords
        bounds = (left, top, right - left, bottom - top)

    x, y, width, height = bounds
    if width <= 0 or height <= 0:
        return None
    # minimized windows have coords near -32000
    if x <= -10000 or y <= -10000:
        return None
    return (x, y, width, height)


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
