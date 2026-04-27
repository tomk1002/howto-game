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
)

from .recorder import Recorder, HotkeyToggle
from .storage import save as save_combo, load as load_combo
from .timeline import TimelineWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('combo-trainer')
        self.resize(900, 480)

        self.recorder = Recorder()
        self.recorder.event_recorded.connect(self._on_event)
        self.recorder.state_changed.connect(self._on_state)

        self.hotkey = HotkeyToggle('<f9>')
        self.hotkey.triggered.connect(self.recorder.toggle)

        self._build_ui()
        self._refresh_button_state(False)

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

    # ---- events from recorder ----

    def _on_event(self, evt):
        self.timeline.append_event(evt)
        self.lbl_count.setText(f"이벤트 {len(self.recorder.events)}")

    def _on_state(self, recording):
        self._refresh_button_state(recording)
        if recording:
            self.timeline.clear()
            self.lbl_count.setText('이벤트 0')
            self.statusBar().showMessage('🔴 녹화 중… F9 로 정지')
        else:
            self.statusBar().showMessage(
                f"녹화 완료. {len(self.recorder.events)}개 이벤트, "
                f"{(self.recorder.events[-1]['t_ms'] / 1000) if self.recorder.events else 0:.2f}초"
            )

    def _refresh_button_state(self, recording):
        self.btn_record.setText('정지 (F9)' if recording else '녹화 (F9)')
        for b in (self.btn_save, self.btn_load, self.btn_clear):
            b.setEnabled(not recording)

    # ---- actions ----

    def _clear(self):
        self.recorder.events = []
        self.timeline.clear()
        self.lbl_count.setText('이벤트 0')
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
            'Combo files (*.json)',
        )
        if not path:
            return
        save_combo(
            self.recorder.events,
            path,
            title=self.title_input.text(),
            game=self.game_input.text(),
        )
        self.statusBar().showMessage(f'저장됨: {Path(path).name}')

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '콤보 불러오기',
            '',
            'Combo files (*.json)',
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
        self.statusBar().showMessage(
            f"불러옴: {Path(path).name} ({len(self.recorder.events)}개 이벤트, "
            f"{data.get('duration_ms', 0) / 1000:.2f}초)"
        )

    def closeEvent(self, event):
        try:
            self.recorder.stop()
            self.hotkey.stop()
        except Exception:
            pass
        super().closeEvent(event)
