import os
import shutil
from collections import deque
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
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
    QComboBox,
    QSplitter,
    QFrame,
    QSlider,
    QDialog,
)

from .recorder import Recorder, HotkeyToggle
from .storage import save as save_combo, load as load_combo
from .timeline import TimelineWidget
from .windows import list_visible_windows, get_window_bounds
from .screen_recorder import ScreenRecorder, is_ffmpeg_available
from .event_list import EventListView
from .player import PlayerWindow
from .video_overlay import VideoOverlayWindow
from .crop_dialog import CropDialog
from .add_event_dialog import AddEventDialog
from .resources_loader import (
    champion_choices,
    champion_skill_icons,
    manifest_available,
    path_to_relative,
    path_to_absolute,
    PROJECT_ROOT,
    RESOURCES_DIR,
)
from .key_mapping_dialog import KeyMappingDialog, unique_keys

from PyQt6.QtGui import QPixmap


RECORDINGS_DIR = Path('recordings')
PLAYBACK_RATES = [0.25, 0.5, 1.0, 1.5, 2.0]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('HowTo')
        self.resize(1200, 820)

        self.recorder = Recorder()
        self.recorder.event_recorded.connect(self._on_event)
        self.recorder.state_changed.connect(self._on_state)

        self.screen_recorder = ScreenRecorder()
        self.screen_recorder.failed.connect(self._on_screen_failed)

        self.hotkey = HotkeyToggle('<f9>')
        self.hotkey.triggered.connect(self._on_hotkey)

        # State
        self._pending_video_path = None
        self._completed_video_path = None
        self._capture_bounds = None
        self._capture_window_title = ''
        self._video_path = None  # path currently loaded in player
        self._loaded_video_meta = None  # video_meta from loaded JSON, preserved across save
        self._history = deque(maxlen=20)
        self._overlay_window = None  # PlayerWindow (held to prevent GC)
        self._video_overlay_window = None  # VideoOverlayWindow
        self._crop_rect = None  # (x, y, w, h) in source video pixels, applied on save
        self._manual_key_icons = {}  # {KEY: image path} — overrides champion auto-icons

        self._build_ui()
        self._refresh_windows()
        self._refresh_record_readiness()
        self._refresh_button_state(False)
        self._refresh_edit_button_state([])

        QShortcut(QKeySequence('Ctrl+Z'), self, activated=self._undo)
        QShortcut(QKeySequence('Space'), self, activated=self._toggle_play)

    # =====================================================================
    # UI
    # =====================================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- header form ----
        form = QFormLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText('예: Yasuo Q-cancel')
        self.game_input = QLineEdit()
        self.game_input.setPlaceholderText('예: League of Legends')
        form.addRow('제목', self.title_input)
        form.addRow('게임', self.game_input)

        # Champion picker (only useful if DDragon manifest is available)
        self.champion_combo = QComboBox()
        self.champion_combo.addItem('— 선택 안 함 —', userData='')
        if manifest_available():
            for display, cid in champion_choices():
                self.champion_combo.addItem(f'{display}  ({cid})', userData=cid)
        else:
            self.champion_combo.setEnabled(False)
            self.champion_combo.setToolTip(
                'resources/manifest.json 없음 — `python tools/download_ddragon.py` 로 받으세요'
            )
        form.addRow('챔피언 (LoL)', self.champion_combo)

        target_row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(380)
        self.window_combo.currentIndexChanged.connect(self._refresh_record_readiness)
        self.btn_refresh_windows = QPushButton('🔄')
        self.btn_refresh_windows.setToolTip('창 목록 새로고침')
        self.btn_refresh_windows.setFixedWidth(32)
        self.btn_refresh_windows.clicked.connect(self._refresh_windows)
        self.lbl_ready = QLabel('')
        self.lbl_ready.setStyleSheet('color: #6b7280;')
        target_row.addWidget(self.window_combo, 1)
        target_row.addWidget(self.btn_refresh_windows)
        target_row.addWidget(self.lbl_ready)
        form.addRow('대상 창', target_row)
        root.addLayout(form)

        # ---- main button row ----
        btns = QHBoxLayout()
        self.btn_record = QPushButton('녹화 (F9)')
        self.btn_record.clicked.connect(self._on_hotkey)
        self.btn_clear = QPushButton('지우기')
        self.btn_clear.clicked.connect(self._clear)
        self.btn_save = QPushButton('저장…')
        self.btn_save.clicked.connect(self._save)
        self.btn_load = QPushButton('불러오기…')
        self.btn_load.clicked.connect(self._load)
        self.btn_overlay = QPushButton('🎯 오버레이 재생')
        self.btn_overlay.setToolTip('항상 위에 떠 있는 콤보 시퀀스 + 입력 트래커 창 열기')
        self.btn_overlay.clicked.connect(self._open_overlay)
        self.btn_crop = QPushButton('🖼 크롭 설정')
        self.btn_crop.setToolTip('영상의 캡처 영역을 줄여서 캐릭터 부분만 강조 (저장 시 ffmpeg로 재인코딩)')
        self.btn_crop.clicked.connect(self._open_crop_dialog)
        self.btn_crop_clear = QPushButton('크롭 해제')
        self.btn_crop_clear.clicked.connect(self._clear_crop)
        self.btn_keymap = QPushButton('🔧 키 아이콘 매핑…')
        self.btn_keymap.setToolTip('각 키에 사용할 아이콘 이미지를 직접 지정 (자동 매핑 위에 덮어씀)')
        self.btn_keymap.clicked.connect(self._open_keymap_dialog)
        for b in (self.btn_record, self.btn_clear, self.btn_save, self.btn_load,
                  self.btn_overlay, self.btn_crop, self.btn_crop_clear, self.btn_keymap):
            btns.addWidget(b)
        btns.addStretch(1)
        self.lbl_crop = QLabel('크롭 없음')
        self.lbl_crop.setStyleSheet('color: #6b7280;')
        btns.addWidget(self.lbl_crop)
        self.lbl_count = QLabel('이벤트 0')
        btns.addWidget(self.lbl_count)
        root.addLayout(btns)

        # ---- main split: video / timeline / event list ----
        splitter = QSplitter(Qt.Orientation.Vertical)

        # video widget + transport controls
        video_panel = QFrame()
        video_layout = QVBoxLayout(video_panel)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(4)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(240)
        self.video_widget.setStyleSheet('background: #000;')
        video_layout.addWidget(self.video_widget, 1)

        transport = QHBoxLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        self.btn_play = QPushButton('▶')
        self.btn_play.setFixedWidth(36)
        self.btn_play.clicked.connect(self._toggle_play)
        self.scrub_slider = QSlider(Qt.Orientation.Horizontal)
        self.scrub_slider.setRange(0, 0)
        self.scrub_slider.sliderMoved.connect(self._on_scrub)
        self.lbl_time = QLabel('0.00 / 0.00 s')
        self.lbl_time.setMinimumWidth(120)
        self.speed_combo = QComboBox()
        for r in PLAYBACK_RATES:
            self.speed_combo.addItem(f'{r}x', userData=r)
        self.speed_combo.setCurrentIndex(PLAYBACK_RATES.index(1.0))
        self.speed_combo.currentIndexChanged.connect(self._on_speed_change)
        transport.addWidget(self.btn_play)
        transport.addWidget(self.scrub_slider, 1)
        transport.addWidget(self.lbl_time)
        transport.addWidget(QLabel('속도'))
        transport.addWidget(self.speed_combo)
        video_layout.addLayout(transport)
        splitter.addWidget(video_panel)

        # timeline
        self.timeline = TimelineWidget()
        splitter.addWidget(self.timeline)

        # edit panel
        edit_panel = QFrame()
        edit_layout = QVBoxLayout(edit_panel)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(4)

        edit_bar = QHBoxLayout()
        edit_bar.setContentsMargins(0, 0, 0, 0)
        edit_bar.addWidget(QLabel('편집:'))
        self.btn_del = QPushButton('🗑 선택 삭제')
        self.btn_del.setToolTip('선택한 이벤트 제거 (Delete)')
        self.btn_del.clicked.connect(self._delete_selected)
        self.btn_trim_start = QPushButton('⏮ 앞쪽 자르기')
        self.btn_trim_start.setToolTip('선택한 첫 이벤트 앞은 모두 제거')
        self.btn_trim_start.clicked.connect(self._trim_to_start)
        self.btn_trim_end = QPushButton('⏭ 뒤쪽 자르기')
        self.btn_trim_end.setToolTip('선택한 마지막 이벤트 뒤는 모두 제거')
        self.btn_trim_end.clicked.connect(self._trim_to_end)
        self.btn_keep_range = QPushButton('↔ 구간만 남기기')
        self.btn_keep_range.setToolTip('선택한 구간 외의 이벤트 모두 제거')
        self.btn_keep_range.clicked.connect(self._keep_only_range)
        self.btn_remove_releases = QPushButton('🚫 release 모두 제거')
        self.btn_remove_releases.setToolTip('모든 key_release / mouse_release 이벤트 일괄 삭제')
        self.btn_remove_releases.clicked.connect(self._delete_all_releases)
        self.btn_remove_same_key = QPushButton('🔑 이 키 모두 제거')
        self.btn_remove_same_key.setToolTip(
            '선택한 첫 이벤트의 키 / 버튼 이름과 일치하는 모든 이벤트 제거 (press + release)'
        )
        self.btn_remove_same_key.clicked.connect(self._delete_same_key)
        self.btn_event_icon = QPushButton('🎨 아이콘 지정')
        self.btn_event_icon.setToolTip(
            '선택한 이벤트(들)에만 적용할 아이콘 이미지 지정 — 키별 매핑보다 우선'
        )
        self.btn_event_icon.clicked.connect(self._set_event_icon)
        self.btn_event_icon_clear = QPushButton('아이콘 제거')
        self.btn_event_icon_clear.setToolTip('선택 이벤트의 개별 아이콘 제거 (키 매핑·자동 매핑으로 복귀)')
        self.btn_event_icon_clear.clicked.connect(self._clear_event_icon)
        self.btn_add_event = QPushButton('➕ 이벤트 추가')
        self.btn_add_event.setToolTip(
            '원하는 시간/키로 이벤트를 직접 추가 (현재 영상 위치가 기본값)'
        )
        self.btn_add_event.clicked.connect(self._add_event)
        self.btn_undo = QPushButton('↶ 실행취소')
        self.btn_undo.setToolTip('마지막 편집 되돌리기 (Ctrl+Z)')
        self.btn_undo.clicked.connect(self._undo)
        for b in (
            self.btn_del, self.btn_trim_start, self.btn_trim_end, self.btn_keep_range,
            self.btn_remove_releases, self.btn_remove_same_key,
            self.btn_event_icon, self.btn_event_icon_clear,
            self.btn_add_event, self.btn_undo,
        ):
            edit_bar.addWidget(b)
        edit_bar.addStretch(1)
        self.lbl_selection = QLabel('선택 0')
        edit_bar.addWidget(self.lbl_selection)
        edit_layout.addLayout(edit_bar)

        self.event_list = EventListView()
        self.event_list.selection_changed.connect(self._on_list_selection)
        QShortcut(QKeySequence.StandardKey.Delete, self.event_list, activated=self._delete_selected)
        edit_layout.addWidget(self.event_list, 1)
        splitter.addWidget(edit_panel)

        splitter.setStretchFactor(0, 4)  # video gets most space
        splitter.setStretchFactor(1, 1)  # timeline thin
        splitter.setStretchFactor(2, 3)  # list comfortable
        root.addWidget(splitter, 1)

        # ---- media player ----
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        self.player.positionChanged.connect(self._on_video_position)
        self.player.durationChanged.connect(self._on_video_duration)
        self.player.playbackStateChanged.connect(self._on_video_state)
        self.player.errorOccurred.connect(self._on_video_error)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage('대기 중. 대상 창 선택 후 F9 로 녹화 시작.')

    # =====================================================================
    # Window picker
    # =====================================================================

    def _refresh_windows(self):
        current = self.window_combo.currentText()
        self.window_combo.clear()
        for w in list_visible_windows():
            label = f"{w['title']}  (pid {w['pid']})"
            self.window_combo.addItem(label, userData={'hwnd': w['hwnd'], 'title': w['title']})
        for i in range(self.window_combo.count()):
            if self.window_combo.itemText(i) == current:
                self.window_combo.setCurrentIndex(i)
                break
        self._refresh_record_readiness()

    def _selected_window_info(self):
        data = self.window_combo.currentData()
        if not data or 'hwnd' not in data:
            return None
        return data

    def _refresh_record_readiness(self):
        ok_ffmpeg = is_ffmpeg_available()
        ok_window = self._selected_window_info() is not None
        if not ok_ffmpeg:
            msg = '⚠ ffmpeg 미설치 (winget install Gyan.FFmpeg)'
        elif not ok_window:
            msg = '⚠ 대상 창 선택 필요'
        else:
            msg = '✓ 녹화 가능'
        self.lbl_ready.setText(msg)
        if hasattr(self, 'btn_record'):
            self.btn_record.setEnabled(ok_ffmpeg and ok_window and not self.recorder.recording)

    # =====================================================================
    # Recorder integration
    # =====================================================================

    def _on_hotkey(self):
        # F9 / button: only allow start if ready
        if self.recorder.recording:
            self.recorder.stop()
            return
        if not is_ffmpeg_available() or not self._selected_window_info():
            self.statusBar().showMessage('녹화 시작 불가 — 대상 창 + ffmpeg 모두 필요')
            return
        self.recorder.start()

    def _on_event(self, evt):
        self.timeline.append_event(evt)
        self.lbl_count.setText(f"이벤트 {len(self.recorder.events)}")

    def _on_state(self, recording):
        self._refresh_button_state(recording)
        if recording:
            self._history.clear()
            self.timeline.clear()
            self.event_list.set_events([])
            self.lbl_count.setText('이벤트 0')
            self._unload_video()
            self._maybe_start_screen_recording()
            self.statusBar().showMessage('🔴 녹화 중… F9 로 정지')
        else:
            self._maybe_stop_screen_recording()
            self.event_list.set_events(self.recorder.events)
            self.timeline.set_events(self.recorder.events)
            duration = (self.recorder.events[-1]['t_ms'] / 1000) if self.recorder.events else 0
            self.statusBar().showMessage(
                f"녹화 완료. {len(self.recorder.events)}개 이벤트, {duration:.2f}초"
            )
            if self._completed_video_path:
                self._load_video(self._completed_video_path)

    def _maybe_start_screen_recording(self):
        info = self._selected_window_info()
        if not info:
            self.statusBar().showMessage('대상 창 선택 안 됨 — 녹화 중단')
            self.recorder.stop()
            return
        bounds = get_window_bounds(info['hwnd'])
        if not bounds:
            self.statusBar().showMessage('대상 창이 최소화/이동됨 — 녹화 중단')
            self.recorder.stop()
            return
        x, y, width, height = bounds
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
        non_record = [
            self.btn_clear, self.btn_save, self.btn_load, self.btn_overlay,
            self.btn_crop, self.btn_crop_clear, self.btn_keymap,
            self.btn_del, self.btn_trim_start, self.btn_trim_end,
            self.btn_keep_range, self.btn_remove_releases,
            self.btn_remove_same_key,
            self.btn_event_icon, self.btn_event_icon_clear,
            self.btn_undo,
        ]
        for b in non_record:
            b.setEnabled(not recording)
        self.window_combo.setEnabled(not recording)
        self.btn_refresh_windows.setEnabled(not recording)
        if hasattr(self, 'event_list'):
            self.event_list.setEnabled(not recording)
        # video transport
        for w in (self.btn_play, self.scrub_slider, self.speed_combo):
            w.setEnabled(not recording)
        self._refresh_record_readiness()

    # =====================================================================
    # Video player
    # =====================================================================

    def _load_video(self, path):
        if not path or not os.path.exists(path):
            return
        self._video_path = path
        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self.player.pause()  # show first frame, don't auto-play
        self.player.setPosition(0)

    def _unload_video(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self._video_path = None
        self._loaded_video_meta = None
        self.scrub_slider.setRange(0, 0)
        self.lbl_time.setText('0.00 / 0.00 s')

    def _toggle_play(self):
        if self.recorder.recording or not self._video_path:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_video_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText('⏸')
        else:
            self.btn_play.setText('▶')

    def _on_video_position(self, ms):
        if not self.scrub_slider.isSliderDown():
            self.scrub_slider.setValue(int(ms))
        dur = self.player.duration()
        self.lbl_time.setText(f'{ms / 1000:.2f} / {dur / 1000:.2f} s')
        self.timeline.set_playhead(ms)

    def _on_video_duration(self, ms):
        self.scrub_slider.setRange(0, int(ms))

    def _on_scrub(self, ms):
        self.player.setPosition(int(ms))

    def _on_speed_change(self, _idx):
        rate = self.speed_combo.currentData()
        if rate is not None:
            self.player.setPlaybackRate(float(rate))

    def _on_video_error(self, error, error_string=''):
        if error == QMediaPlayer.Error.NoError:
            return
        self.statusBar().showMessage(f'비디오 오류: {error_string or error}')

    # =====================================================================
    # List + edit
    # =====================================================================

    def _on_list_selection(self, indices):
        self.lbl_selection.setText(f'선택 {len(indices)}')
        self._refresh_edit_button_state(indices)
        # seek video to first selected event
        if indices and self._video_path:
            t = self.recorder.events[indices[0]].get('t_ms', 0)
            self.player.setPosition(int(t))

    def _refresh_edit_button_state(self, indices):
        recording = self.recorder.recording
        has_selection = bool(indices)
        for b in (self.btn_del, self.btn_trim_start, self.btn_trim_end, self.btn_keep_range):
            b.setEnabled(has_selection and not recording)
        # "이 키 모두 제거" needs a selected event that has a key or button
        first_has_key = False
        if has_selection:
            ref = self.recorder.events[indices[0]]
            first_has_key = bool(ref.get('key') or ref.get('button'))
        self.btn_remove_same_key.setEnabled(first_has_key and not recording)
        # per-event icon buttons need press/click events selected
        any_press_selected = False
        for i in indices:
            if self.recorder.events[i].get('type') in ('key_press', 'mouse_press'):
                any_press_selected = True
                break
        self.btn_event_icon.setEnabled(any_press_selected and not recording)
        any_has_icon = any(self.recorder.events[i].get('icon') for i in indices)
        self.btn_event_icon_clear.setEnabled(any_has_icon and not recording)
        # ▼ insert is always available outside of recording
        self.btn_add_event.setEnabled(not recording)
        # bulk release removal — always available when there are events
        self.btn_remove_releases.setEnabled(bool(self.recorder.events) and not recording)
        self.btn_undo.setEnabled(bool(self._history) and not recording)

    def _push_history(self):
        self._history.append([dict(e) for e in self.recorder.events])

    def _refresh_after_edit(self, msg=None):
        self.timeline.set_events(self.recorder.events)
        self.event_list.set_events(self.recorder.events)
        self.lbl_count.setText(f"이벤트 {len(self.recorder.events)}")
        self._refresh_edit_button_state([])
        if msg:
            self.statusBar().showMessage(msg)

    def _add_event(self):
        if self.recorder.recording:
            return
        # default to current video position so the user can pause and add
        default_t = int(self.player.position()) if self._video_path else 0
        if not default_t and self.recorder.events:
            default_t = self.recorder.events[-1].get('t_ms', 0) + 100
        dlg = AddEventDialog(self, default_t_ms=default_t)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_event = dlg.event_dict()
        if not new_event:
            return
        self._push_history()
        self.recorder.events.append(new_event)
        self.recorder.events.sort(key=lambda e: e.get('t_ms', 0))
        self._refresh_after_edit('이벤트 1개 추가')

    def _delete_selected(self):
        if self.recorder.recording:
            return
        indices = set(self.event_list.selected_indices())
        if not indices:
            return
        self._push_history()
        before = len(self.recorder.events)
        self.recorder.events = [e for i, e in enumerate(self.recorder.events) if i not in indices]
        self._refresh_after_edit(f'{before - len(self.recorder.events)}개 이벤트 삭제')

    def _trim_to_start(self):
        if self.recorder.recording:
            return
        indices = self.event_list.selected_indices()
        if not indices or indices[0] == 0:
            return
        keep_from = indices[0]
        self._push_history()
        self.recorder.events = self.recorder.events[keep_from:]
        self._refresh_after_edit(f'앞쪽 {keep_from}개 잘라냄')

    def _trim_to_end(self):
        if self.recorder.recording:
            return
        indices = self.event_list.selected_indices()
        if not indices:
            return
        keep_until = indices[-1]
        removed = len(self.recorder.events) - (keep_until + 1)
        if removed <= 0:
            return
        self._push_history()
        self.recorder.events = self.recorder.events[: keep_until + 1]
        self._refresh_after_edit(f'뒤쪽 {removed}개 잘라냄')

    def _keep_only_range(self):
        if self.recorder.recording:
            return
        indices = self.event_list.selected_indices()
        if not indices:
            return
        start, end = indices[0], indices[-1]
        before = len(self.recorder.events)
        kept = end - start + 1
        if kept == before:
            return
        self._push_history()
        self.recorder.events = self.recorder.events[start: end + 1]
        self._refresh_after_edit(f'{kept}개 유지, {before - kept}개 제거')

    def _delete_all_releases(self):
        if self.recorder.recording or not self.recorder.events:
            return
        before = len(self.recorder.events)
        kept = [
            e for e in self.recorder.events
            if e.get('type') not in ('key_release', 'mouse_release')
        ]
        removed = before - len(kept)
        if removed == 0:
            self.statusBar().showMessage('release 이벤트 없음')
            return
        self._push_history()
        self.recorder.events = kept
        self._refresh_after_edit(f'release {removed}개 제거')

    def _delete_same_key(self):
        if self.recorder.recording:
            return
        indices = self.event_list.selected_indices()
        if not indices:
            return
        ref = self.recorder.events[indices[0]]
        ref_key = ref.get('key') or ref.get('button')
        if not ref_key:
            self.statusBar().showMessage('선택한 이벤트에 키/버튼 정보 없음 (스크롤?)')
            return
        before = len(self.recorder.events)
        kept = [
            e for e in self.recorder.events
            if (e.get('key') or e.get('button')) != ref_key
        ]
        removed = before - len(kept)
        if removed == 0:
            return
        self._push_history()
        self.recorder.events = kept
        self._refresh_after_edit(f'"{ref_key}" 관련 {removed}개 제거')

    def _set_event_icon(self):
        if self.recorder.recording:
            return
        indices = [
            i for i in self.event_list.selected_indices()
            if self.recorder.events[i].get('type') in ('key_press', 'mouse_press')
        ]
        if not indices:
            return
        start_dir = str(RESOURCES_DIR) if RESOURCES_DIR.exists() else ''
        path, _ = QFileDialog.getOpenFileName(
            self, '이벤트 아이콘 선택', start_dir,
            'Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)',
        )
        if not path:
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.statusBar().showMessage('이미지 로드 실패')
            return
        self._push_history()
        for i in indices:
            self.recorder.events[i]['icon'] = path
        self._refresh_after_edit(f'{len(indices)}개 이벤트에 아이콘 지정')

    def _clear_event_icon(self):
        if self.recorder.recording:
            return
        indices = self.event_list.selected_indices()
        cleared = 0
        for i in indices:
            if 'icon' in self.recorder.events[i]:
                cleared += 1
        if cleared == 0:
            return
        self._push_history()
        for i in indices:
            self.recorder.events[i].pop('icon', None)
        self._refresh_after_edit(f'{cleared}개 이벤트 아이콘 제거')

    def _undo(self):
        if self.recorder.recording or not self._history:
            return
        self.recorder.events = self._history.pop()
        self._refresh_after_edit('실행취소')

    # =====================================================================
    # Crop
    # =====================================================================

    def _video_resolution(self):
        """Best-effort source resolution from current state."""
        # Loaded JSON's video_meta.capture_bounds
        meta = self._loaded_video_meta or {}
        bounds = meta.get('capture_bounds') if isinstance(meta, dict) else None
        if bounds and len(bounds) >= 4:
            return (int(bounds[2]), int(bounds[3]))
        # Fresh recording: self._capture_bounds = (x, y, w, h)
        if self._capture_bounds and len(self._capture_bounds) == 4:
            return (int(self._capture_bounds[2]), int(self._capture_bounds[3]))
        return None

    def _open_crop_dialog(self):
        if self.recorder.recording:
            return
        # source video can be either freshly recorded (in recordings/) or loaded
        source = self._completed_video_path
        if not (source and os.path.exists(source)):
            source = self._video_path
        if not (source and os.path.exists(source)):
            self.statusBar().showMessage('크롭할 영상이 없습니다. 녹화하거나 영상이 있는 .json 을 불러오세요.')
            return
        if not is_ffmpeg_available():
            self.statusBar().showMessage('ffmpeg 미설치 — 크롭 불가')
            return

        size = self._video_resolution()
        dlg = CropDialog(
            source,
            video_size=size,
            initial_crop=self._crop_rect,
            parent=self,
        )
        if dlg.exec():
            crop = dlg.selected_crop()
            self._crop_rect = crop
            self._refresh_crop_label()
            if crop:
                self.statusBar().showMessage(
                    f'크롭 설정됨: {crop[2]}×{crop[3]} @ ({crop[0]}, {crop[1]}) — 저장 시 적용'
                )
            else:
                self.statusBar().showMessage('크롭 영역이 너무 작거나 전체와 동일 — 적용 안 됨')

    def _clear_crop(self):
        if self._crop_rect is None:
            return
        self._crop_rect = None
        self._refresh_crop_label()
        self.statusBar().showMessage('크롭 해제됨')

    def _refresh_crop_label(self):
        if self._crop_rect:
            x, y, w, h = self._crop_rect
            self.lbl_crop.setText(f'크롭: {w}×{h} @ ({x},{y})')
            self.lbl_crop.setStyleSheet('color: #7ee787;')
        else:
            self.lbl_crop.setText('크롭 없음')
            self.lbl_crop.setStyleSheet('color: #6b7280;')

    # =====================================================================
    # Manual key→icon mapping
    # =====================================================================

    def _build_key_icon_map(self):
        """Final {KEY: QPixmap} = champion auto-icons overridden by manual mappings."""
        cid = self.champion_combo.currentData() or ''
        icons = dict(champion_skill_icons(cid)) if cid else {}
        for key, path in self._manual_key_icons.items():
            if not path or not os.path.exists(path):
                continue
            pix = QPixmap(path)
            if not pix.isNull():
                icons[key.upper()] = pix
        return icons

    def _open_keymap_dialog(self):
        if self.recorder.recording or not self.recorder.events:
            self.statusBar().showMessage('매핑할 이벤트가 없습니다.')
            return
        keys = unique_keys(self.recorder.events)
        cid = self.champion_combo.currentData() or ''
        base_icons = champion_skill_icons(cid) if cid else {}
        dlg = KeyMappingDialog(
            keys,
            current_mappings=self._manual_key_icons,
            base_icons=base_icons,
            parent=self,
        )
        if dlg.exec():
            self._manual_key_icons = dlg.mappings()
            self.statusBar().showMessage(
                f'키 매핑 {len(self._manual_key_icons)}개 적용 — 저장 시 함께 기록됨'
            )

    # =====================================================================
    # Overlay player
    # =====================================================================

    def _open_overlay(self):
        if not self.recorder.events:
            self.statusBar().showMessage('재생할 이벤트가 없습니다. 먼저 녹화하거나 불러오세요.')
            return
        # close existing overlays before opening new
        for attr in ('_overlay_window', '_video_overlay_window'):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass
                setattr(self, attr, None)

        title = self.title_input.text() or '콤보'
        media_player = None

        # If a video is loaded, open the video overlay first and link its
        # QMediaPlayer to the sequence overlay so they share a time source.
        if self._video_path and os.path.exists(self._video_path):
            self._video_overlay_window = VideoOverlayWindow(
                self._video_path, title=title, crop_rect=self._crop_rect,
            )
            self._video_overlay_window.show()
            media_player = self._video_overlay_window.player

        key_icons = self._build_key_icon_map()
        self._overlay_window = PlayerWindow(
            self.recorder.events, title=title,
            media_player=media_player, key_icons=key_icons,
        )
        # position sequence window next to video window
        if self._video_overlay_window is not None:
            geom = self._video_overlay_window.geometry()
            self._overlay_window.move(geom.x() + geom.width() + 12, geom.y())
        self._overlay_window.show()

    # =====================================================================
    # Main actions
    # =====================================================================

    def _clear(self):
        self.recorder.events = []
        self._history.clear()
        self.timeline.clear()
        self.event_list.set_events([])
        self.lbl_count.setText('이벤트 0')
        self._unload_video()
        if self._completed_video_path and os.path.exists(self._completed_video_path):
            try:
                os.remove(self._completed_video_path)
            except OSError:
                pass
        self._completed_video_path = None
        self._crop_rect = None
        self._refresh_crop_label()
        self._manual_key_icons = {}
        self.statusBar().showMessage('비웠습니다.')

    def _save(self):
        if not self.recorder.events:
            self.statusBar().showMessage('저장할 이벤트가 없습니다.')
            return
        default_name = (self.title_input.text() or 'combo').replace(' ', '_') + '.json'
        path, _ = QFileDialog.getSaveFileName(
            self, '콤보 저장', default_name, 'HowTo files (*.json)'
        )
        if not path:
            return

        target_json = Path(path)
        target_video = target_json.with_suffix('.mp4')

        # Pick the source video. Fresh recording wins over a loaded one.
        is_fresh = bool(self._completed_video_path) and os.path.exists(self._completed_video_path)
        source_video = self._completed_video_path if is_fresh else self._video_path

        # Release the file lock from the media player so we can move/copy it.
        had_loaded = self._video_path is not None
        if had_loaded:
            self.player.stop()
            self.player.setSource(QUrl())
            self._video_path = None

        video_file_rel = None
        video_meta = None
        if source_video and os.path.exists(source_video):
            try:
                src = Path(source_video).resolve()
                # Save the original video as-is. The crop region is stored in
                # JSON and applied at playback time — no ffmpeg re-encoding,
                # so the user can adjust the crop later without quality loss.
                if src != target_video.resolve():
                    if is_fresh:
                        shutil.move(str(src), str(target_video))
                    else:
                        shutil.copy2(str(src), str(target_video))

                if target_video.exists():
                    video_file_rel = target_video.name
                    if is_fresh:
                        video_meta = {
                            'fps': 30,
                            'codec': 'libx264',
                            'window_title': self._capture_window_title or '',
                            'capture_bounds': list(self._capture_bounds or ()),
                        }
                    else:
                        video_meta = dict(self._loaded_video_meta) if self._loaded_video_meta else {}
                    if self._crop_rect is not None:
                        video_meta['crop_view'] = list(self._crop_rect)
                    elif 'crop_view' in video_meta:
                        del video_meta['crop_view']
                    if is_fresh:
                        self._completed_video_path = None
            except (OSError, RuntimeError) as exc:
                self.statusBar().showMessage(f'영상 처리 실패: {exc}')

        # Persist key icons + per-event icons with relative paths when possible.
        portable_key_icons = {
            k: path_to_relative(p) for k, p in self._manual_key_icons.items()
        }
        portable_events = []
        for e in self.recorder.events:
            if 'icon' in e and e['icon']:
                e2 = dict(e)
                e2['icon'] = path_to_relative(e2['icon'])
                portable_events.append(e2)
            else:
                portable_events.append(e)

        save_combo(
            portable_events, path,
            title=self.title_input.text(),
            game=self.game_input.text(),
            champion_id=self.champion_combo.currentData() or '',
            key_icons=portable_key_icons,
            video_file=video_file_rel,
            video_meta=video_meta,
        )

        # Reload video into player so user can keep editing post-save.
        if video_file_rel:
            self._load_video(str(target_video))
            if video_meta:
                self._loaded_video_meta = video_meta

        msg = f'저장됨: {target_json.name}'
        if video_file_rel:
            msg += f' (+ {video_file_rel})'
        self.statusBar().showMessage(msg)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '콤보 불러오기', '', 'HowTo files (*.json)'
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
        # restore champion selection if present in JSON
        champ_id = data.get('champion_id', '')
        if champ_id:
            for i in range(self.champion_combo.count()):
                if self.champion_combo.itemData(i) == champ_id:
                    self.champion_combo.setCurrentIndex(i)
                    break
        else:
            self.champion_combo.setCurrentIndex(0)
        # restore manual key→icon mappings; resolve relative paths against PROJECT_ROOT
        loaded_map = data.get('key_icons', {}) or {}
        self._manual_key_icons = {}
        for k, stored in loaded_map.items():
            if not isinstance(stored, str) or not stored:
                continue
            absolute = path_to_absolute(stored)
            if os.path.exists(absolute):
                self._manual_key_icons[k] = absolute
        loaded_events = list(data.get('events', []))
        for e in loaded_events:
            if e.get('icon'):
                resolved = path_to_absolute(e['icon'])
                if os.path.exists(resolved):
                    e['icon'] = resolved
                else:
                    e.pop('icon', None)
        self.recorder.events = loaded_events
        self._history.clear()
        self.timeline.set_events(self.recorder.events)
        self.event_list.set_events(self.recorder.events)
        self.lbl_count.setText(f"이벤트 {len(self.recorder.events)}")

        # try to load companion video
        self._unload_video()
        video_file = data.get('video_file')
        if video_file:
            video_path = Path(path).parent / video_file
            if video_path.exists():
                self._load_video(str(video_path))
                self._loaded_video_meta = data.get('video_meta')
        # restore crop region from metadata if present
        self._crop_rect = None
        meta = self._loaded_video_meta or {}
        cv = meta.get('crop_view')
        if cv and len(cv) == 4:
            self._crop_rect = tuple(int(v) for v in cv)
        self._refresh_crop_label()

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
            self.player.stop()
            for w in (self._overlay_window, self._video_overlay_window):
                if w is not None:
                    w.close()
        except Exception:
            pass
        super().closeEvent(event)
