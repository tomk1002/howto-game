"""ffmpeg-based screen recorder using desktop capture cropped to a window region.

Why not gdigrab title=...?
  Modern games (Direct3D 11/12, Vulkan) render to swap chains that gdigrab's
  window-targeted mode cannot read — you get a single frozen frame. Capturing
  the composited desktop and cropping to the window's bounds works regardless
  of the game's rendering API.

Tradeoff:
  The capture region is fixed at start time. Moving the window during recording
  desynchronizes the crop. Notifications/popups that overlap the region also
  appear in the recording.
"""

import glob
import os
import shutil
import subprocess
from PyQt6.QtCore import QObject, pyqtSignal


def find_ffmpeg():
    """Locate ffmpeg.exe. Tries PATH first, then known winget install paths."""
    found = shutil.which('ffmpeg')
    if found:
        return found

    candidates = []
    local = os.environ.get('LOCALAPPDATA')
    if local:
        # winget shim
        candidates.append(os.path.join(local, 'Microsoft', 'WinGet', 'Links', 'ffmpeg.exe'))
        # Gyan.FFmpeg package install (version varies)
        candidates.extend(
            glob.glob(os.path.join(local, 'Microsoft', 'WinGet', 'Packages', 'Gyan.FFmpeg*', '**', 'ffmpeg.exe'),
                      recursive=True)
        )
    # Chocolatey default
    candidates.append(r'C:\ProgramData\chocolatey\bin\ffmpeg.exe')
    # Scoop default
    home = os.environ.get('USERPROFILE')
    if home:
        candidates.append(os.path.join(home, 'scoop', 'shims', 'ffmpeg.exe'))

    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def is_ffmpeg_available():
    return find_ffmpeg() is not None


def _even(n):
    """Round to nearest even number (libx264 yuv420p requires even dims)."""
    n = int(n)
    return n - (n % 2)


class ScreenRecorder(QObject):
    started = pyqtSignal()
    stopped = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._process = None
        self._filepath = None
        self._stderr_path = None

    @property
    def is_running(self):
        return self._process is not None

    def start(self, output_path: str, *, x: int, y: int, width: int, height: int, fps: int = 30):
        if self._process is not None:
            return
        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            self.failed.emit('ffmpeg not found in PATH or winget locations. winget install Gyan.FFmpeg')
            return

        width = _even(width)
        height = _even(height)
        if width < 16 or height < 16:
            self.failed.emit(f'capture region too small: {width}x{height}')
            return

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        cmd = [
            ffmpeg_path,
            '-y',
            '-loglevel', 'error',
            '-f', 'gdigrab',
            '-framerate', str(fps),
            '-offset_x', str(int(x)),
            '-offset_y', str(int(y)),
            '-video_size', f'{width}x{height}',
            '-i', 'desktop',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-pix_fmt', 'yuv420p',
            '-crf', '23',
            output_path,
        ]

        self._stderr_path = output_path + '.ffmpeg.log'
        try:
            stderr_file = open(self._stderr_path, 'w', encoding='utf-8')
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
        except FileNotFoundError:
            self.failed.emit('ffmpeg not found')
            self._process = None
            return
        except Exception as exc:
            self.failed.emit(f'failed to start ffmpeg: {exc}')
            self._process = None
            return

        self._filepath = output_path
        self.started.emit()

    def stop(self):
        if self._process is None:
            return None
        try:
            if self._process.stdin and not self._process.stdin.closed:
                self._process.stdin.write(b'q')
                self._process.stdin.flush()
                self._process.stdin.close()
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)
        except OSError:
            self._process.kill()

        return_code = self._process.returncode
        filepath = self._filepath
        self._process = None
        self._filepath = None

        if return_code not in (0, None) and self._stderr_path and os.path.exists(self._stderr_path):
            try:
                with open(self._stderr_path, 'r', encoding='utf-8') as f:
                    tail = f.read().strip().splitlines()[-3:]
                self.failed.emit(f'ffmpeg exited {return_code}: {" | ".join(tail)}')
            except Exception:
                self.failed.emit(f'ffmpeg exited {return_code}')
            return None

        self.stopped.emit(filepath or '')
        return filepath

    def cleanup_log(self):
        if self._stderr_path and os.path.exists(self._stderr_path):
            try:
                os.remove(self._stderr_path)
            except OSError:
                pass
            self._stderr_path = None
