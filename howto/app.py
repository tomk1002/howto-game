import os
import shutil
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QStatusBar,
    QLineEdit,
    QFormLayout,
    QCheckBox,
    QComboBox,
)

from .recorder import Recorder, HotkeyToggle
from .storage import save as save_combo, load as load_combo
from .timeline import TimelineWidget
from .windows import list_visible_windows, get_window_bounds
from .screen_recorder import ScreenRecorder, is_ffmpeg_available


RECORDINGS_DIR = Path('recordings')


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('HowTo')
        self.resize(1000, 560)

        self.recorder = Recorder()
        self.recorder.event_recorded.connect(self._on_event)
        self.recorder.state_changed.connect(self._on_state)

        self.screen_recorder = ScreenRecorder()
        self.screen_recorder.failed.connect(self._on_screen_failed)

        self.hotkey = HotkeyToggle('<f9>')
        self.hotkey.triggered.connect(self.recorder.toggle)

        # State for current recording session
        self._pending_video_path = None  # temp .mp4 path while recording
        self._completed_video_path = None  # final .mp4 path after stop, before save
        self._capture_bounds = None  # (x, y, w, h) used by ffmpeg this session
        self._capture_window_title = ''

        self._build_ui()
        self._refresh_button_state(False)
        self._refresh_windows()

        if not is_ffmpeg_available():
            self.statusBar().showMessage(
                'ffmpeg 미설치 — 화면 녹화 비활성화. winget install Gyan.FFmpeg 후 재시작.'
            )
            self.video_check.setEnabled(False)
            self.video_check.setChecked(False)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # metadata form
        form = QFormLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText('예: Yasuo Q-cancel')
        self.game_input = QLineEdit()
        self.game_input.setPlaceholderText('예: League of Legends')
        form.addRow('제목', self.title_input)
        form.addRow('게임', self.game_input)

        # video options row
        video_row = QHBoxLayout()
        self.video_check = QCheckBox('화면 녹화')
        self.video_check.setChecked(False)
        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(380)
        self.btn_refresh_windows = QPushButton('🔄')
        self.btn_refresh_windows.setToolTip('창 목록 새로고침')
        self.btn_refresh_windows.setFixedWidth(32)
        self.btn_refresh_windows.clicked.connect(self._refresh_windows)
        video_row.addWidget(self.video_check)
        video_row.addWidget(QLabel('대상 창:'))
        video_row.addWidget(self.window_combo, 1)
        video_row.addWidget(self.btn_refresh_windows)
        form.addRow('영상', video_row)

        root.addLayout(form)

        # buttons
        btns = QHBoxLayout()
        self.btn_record = QPushButton('녹화 (F9)')
        self.btn_record.clicked.connect(self.recorder.toggle)
        self.btn_clear = QPushButton('지우기')
        self.btn_clear.clicked.connect(self._clear)
        self.btn_save = QPushButton('저장…')
        self.btn_save.clicked.connect(self._save)
        self.btn_load = QPushButton('불러오기…')
        self.btn_load.clicked.connect(self._load)
        for b in (self.btn_record, self.btn_clear, self.btn_save, self.btn_load):
            btns.addWidget(b)
        btns.addStretch(1)
        self.lbl_count = QLabel('이벤트 0')
        btns.addWidget(self.lbl_count)
        root.addLayout(btns)

        # timeline
        self.timeline = TimelineWidget()
        root.addWidget(self.timeline, 1)

        # status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage('대기 중. F9 또는 [녹화] 버튼으로 시작.')

    # ---- window list ----

    def _refresh_windows(self):
        current = self.window_combo.currentText()
        self.window_combo.clear()
        for w in list_visible_windows():
            label = f"{w['title']}  (pid {w['pid']})"
            # store dict {hwnd, title} so we can re-fetch bounds at record time
            self.window_combo.addItem(label, userData={'hwnd': w['hwnd'], 'title': w['title']})
        # try to restore previous selection
        for i in range(self.window_combo.count()):
            if self.window_combo.itemText(i) == current:
                self.window_combo.setCurrentIndex(i)
                break

    def _selected_window_info(self):
        data = self.window_combo.currentData()
        if not data or 'hwnd' not in data:
            return None
        return data

    # ---- events from recorder ----

    def _on_event(self, evt):
        self.timeline.append_event(evt)
        self.lbl_count.setText(f"이벤트 {len(self.recorder.events)}")

    def _on_state(self, recording):
        self._refresh_button_state(recording)
        if recording:
            self.timeline.clear()
            self.lbl_count.setText('이벤트 0')
            self._maybe_start_screen_recording()
            self.statusBar().showMessage('🔴 녹화 중… F9 로 정지')
        else:
            self._maybe_stop_screen_recording()
            duration = (self.recorder.events[-1]['t_ms'] / 1000) if self.recorder.events else 0
            self.statusBar().showMessage(
                f"녹화 완료. {len(self.recorder.events)}개 이벤트, {duration:.2f}초"
                + (f", 영상 임시저장 {Path(self._completed_video_path).name}" if self._completed_video_path else '')
            )

    def _maybe_start_screen_recording(self):
        if not self.video_check.isChecked():
            self._pending_video_path = None
            return
        if not is_ffmpeg_available():
            self.statusBar().showMessage('ffmpeg 미설치 — 영상 없이 입력만 녹화')
            return
        info = self._selected_window_info()
        if not info:
            self.statusBar().showMessage('대상 창 선택 안 됨 — 영상 없이 입력만 녹화')
            return
        # Re-fetch bounds at record start (window may have moved since selection)
        bounds = get_window_bounds(info['hwnd'])
        if not bounds:
            self.statusBar().showMessage('대상 창이 최소화/이동됨 — 영상 없이 입력만 녹화')
            return
        x, y, width, height = bounds
        # Inset by a few pixels to crop out anti-cheat / capture-indicator borders
        # that some games (e.g., Vanguard) draw on the window frame itself.
        inset = 3
        if width > 2 * inset and height > 2 * inset:
            x += inset
            y += inset
            width -= 2 * inset
            height -= 2 * inset
        self._capture_bounds = (x, y, width, height)
        self._capture_window_title = info['title']
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._pending_video_path = str(RECORDINGS_DIR / f'rec_{stamp}.mp4')
        self.screen_recorder.start(
            self._pending_video_path,
            x=x, y=y, width=width, height=height, fps=30,
        )

    def _maybe_stop_screen_recording(self):
        if not self.screen_recorder.is_running:
            return
        path = self.screen_recorder.stop()
        self._completed_video_path = path
        self._pending_video_path = None

    def _on_screen_failed(self, msg):
        self.statusBar().showMessage(f'화면 녹화 실패: {msg}')
        self._pending_video_path = None
        self._completed_video_path = None

    def _refresh_button_state(self, recording):
        self.btn_record.setText('정지 (F9)' if recording else '녹화 (F9)')
        for b in (self.btn_save, self.btn_load, self.btn_clear):
            b.setEnabled(not recording)
        # disable video controls during recording
        self.video_check.setEnabled(not recording and is_ffmpeg_available())
        self.window_combo.setEnabled(not recording)
        self.btn_refresh_windows.setEnabled(not recording)

    # ---- actions ----

    def _clear(self):
        self.recorder.events = []
        self.timeline.clear()
        self.lbl_count.setText('이벤트 0')
        # also discard temp video
        if self._completed_video_path and os.path.exists(self._completed_video_path):
            try:
                os.remove(self._completed_video_path)
            except OSError:
                pass
        self._completed_video_path = None
        self.statusBar().showMessage('비웠습니다.')

    def _save(self):
        if not self.recorder.events:
            self.statusBar().showMessage('저장할 이벤트가 없습니다.')
            return
        default_name = (self.title_input.text() or 'combo').replace(' ', '_') + '.json'
        path, _ = QFileDialog.getSaveFileName(
            self,
            '콤보 저장',
            default_name,
            'HowTo files (*.json)',
        )
        if not path:
            return

        video_file_rel = None
        video_meta = None
        if self._completed_video_path and os.path.exists(self._completed_video_path):
            json_path = Path(path)
            target_video = json_path.with_suffix('.mp4')
            try:
                shutil.move(self._completed_video_path, target_video)
                video_file_rel = target_video.name  # store relative basename
                video_meta = {
                    'fps': 30,
                    'codec': 'libx264',
                    'window_title': getattr(self, '_capture_window_title', '') or '',
                    'capture_bounds': list(getattr(self, '_capture_bounds', ()) or ()),
                }
                self._completed_video_path = None
            except OSError as exc:
                self.statusBar().showMessage(f'영상 이동 실패: {exc}')

        save_combo(
            self.recorder.events,
            path,
            title=self.title_input.text(),
            game=self.game_input.text(),
            video_file=video_file_rel,
            video_meta=video_meta,
        )
        msg = f'저장됨: {Path(path).name}'
        if video_file_rel:
            msg += f' (+ {video_file_rel})'
        self.statusBar().showMessage(msg)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '콤보 불러오기',
            '',
            'HowTo files (*.json)',
        )
        if not path:
            return
        try:
            data = load_combo(path)
        except Exception as exc:
            self.statusBar().showMessage(f'불러오기 실패: {exc}')
            return
        self.title_input.setText(data.get('title', ''))
        self.game_input.setText(data.get('game', ''))
        self.recorder.events = list(data.get('events', []))
        self.timeline.set_events(self.recorder.events)
        self.lbl_count.setText(f"이벤트 {len(self.recorder.events)}")
        msg = (
            f"불러옴: {Path(path).name} ({len(self.recorder.events)}개 이벤트, "
            f"{data.get('duration_ms', 0) / 1000:.2f}초)"
        )
        if data.get('video_file'):
            msg += f' [영상: {data["video_file"]}]'
        self.statusBar().showMessage(msg)

    def closeEvent(self, event):
        try:
            self.recorder.stop()
            if self.screen_recorder.is_running:
                self.screen_recorder.stop()
            self.hotkey.stop()
        except Exception:
            pass
        super().closeEvent(event)
