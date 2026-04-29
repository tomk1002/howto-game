"""Modal dialog for hand-authoring an event into the timeline.

Useful when the user wants a press at a specific timing that the recorder
missed (or never captured) — e.g. a click cue, a delayed Q, or an event
inserted between two others. The result is a normal event dict matching
the recorder's schema.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QSpinBox,
    QLineEdit,
    QComboBox,
    QDialogButtonBox,
)


EVENT_TYPES = ('key_press', 'key_release', 'mouse_press', 'mouse_release')


class AddEventDialog(QDialog):
    def __init__(self, parent=None, default_t_ms=0):
        super().__init__(parent)
        self.setWindowTitle('이벤트 추가')
        self.setMinimumWidth(320)

        form = QFormLayout(self)

        self.t_input = QSpinBox()
        self.t_input.setRange(0, 24 * 60 * 60 * 1000)
        self.t_input.setSingleStep(50)
        self.t_input.setSuffix(' ms')
        self.t_input.setValue(int(max(0, default_t_ms)))
        form.addRow('시간', self.t_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(EVENT_TYPES)
        form.addRow('종류', self.type_combo)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText('예: q, shift, space, Button.left')
        form.addRow('키 / 버튼', self.key_input)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def event_dict(self):
        text = self.key_input.text().strip()
        if not text:
            return None
        ev = {'t_ms': int(self.t_input.value()), 'type': self.type_combo.currentText()}
        if ev['type'].startswith('mouse'):
            if not text.startswith('Button.'):
                text = f'Button.{text.lower()}'
            ev['button'] = text
        else:
            ev['key'] = text
        return ev
