"""Dialog: list every unique key in the current recording and let the
user pick a custom icon image for each.

Manual mappings override the automatic champion-spell mapping. Mappings
that point to an existing image are persisted to the recording's JSON
under ``key_icons``; missing files are silently ignored at load.
"""

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QWidget,
)

from .resources_loader import RESOURCES_DIR, PROJECT_ROOT


def _strip(value):
    s = str(value)
    for prefix in ('Key.', 'Button.'):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def unique_keys(events):
    """Distinct uppercase key/button labels in press order."""
    seen = set()
    out = []
    for e in events:
        if e.get('type') not in ('key_press', 'mouse_press'):
            continue
        label = _strip(e.get('key') or e.get('button') or '').upper()
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def _scaled_pixmap_label(pixmap, size=36):
    label = QLabel()
    label.setFixedSize(size + 4, size + 4)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if pixmap and not pixmap.isNull():
        label.setPixmap(pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
    else:
        label.setText('—')
        label.setStyleSheet('color: #6b7280;')
    return label


class KeyMappingDialog(QDialog):
    def __init__(self, keys, current_mappings=None, base_icons=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('키 → 아이콘 매핑')
        self.resize(640, 480)

        self._mappings = dict(current_mappings or {})  # {KEY: filepath}
        self._base_icons = dict(base_icons or {})       # {KEY: QPixmap}
        self._keys = list(keys)

        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(
            '각 키에 사용할 아이콘 이미지를 지정합니다. '
            '미지정 키는 챔피언 자동 매핑(있으면)을 따르고, 그것도 없으면 글자로 표시됩니다.'
        )
        hint.setStyleSheet('color: #6b7280;')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['키', '아이콘', '경로', ''])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 50)
        self.table.setColumnWidth(3, 160)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self):
        self.table.setRowCount(len(self._keys))
        for row, key in enumerate(self._keys):
            self._render_row(row, key)
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, 44)

    def _render_row(self, row, key):
        # column 0 — key label
        item = QTableWidgetItem(key)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, item)

        # column 1 — preview
        path = self._mappings.get(key, '')
        preview_pix = None
        if path and os.path.exists(path):
            preview_pix = QPixmap(path)
        if preview_pix is None or preview_pix.isNull():
            preview_pix = self._base_icons.get(key)
        self.table.setCellWidget(row, 1, _scaled_pixmap_label(preview_pix))

        # column 2 — path text (forward-slashed relative form when inside project)
        if path:
            display = path
            try:
                display = Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
            except (ValueError, OSError):
                pass
            text = display
        else:
            text = '(자동 매핑 사용)' if key in self._base_icons else '(매핑 없음 — 글자로 표시)'
        path_item = QTableWidgetItem(text)
        path_item.setFlags(path_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        path_item.setForeground(Qt.GlobalColor.darkGray if not path else Qt.GlobalColor.white)
        self.table.setItem(row, 2, path_item)

        # column 3 — actions
        actions = QWidget()
        h = QHBoxLayout(actions)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(4)
        btn_change = QPushButton('변경…')
        btn_clear = QPushButton('지우기')
        btn_change.clicked.connect(lambda _=False, k=key, r=row: self._on_change(k, r))
        btn_clear.clicked.connect(lambda _=False, k=key, r=row: self._on_clear(k, r))
        h.addWidget(btn_change)
        h.addWidget(btn_clear)
        self.table.setCellWidget(row, 3, actions)

    def _on_change(self, key, row):
        start_dir = str(RESOURCES_DIR) if RESOURCES_DIR.exists() else ''
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"'{key}' 키 아이콘 선택",
            start_dir,
            'Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)',
        )
        if not path:
            return
        # validate it loads
        pix = QPixmap(path)
        if pix.isNull():
            return
        self._mappings[key] = path
        self._render_row(row, key)

    def _on_clear(self, key, row):
        if key in self._mappings:
            del self._mappings[key]
            self._render_row(row, key)

    def mappings(self):
        """Return dict of {KEY: filepath} only for keys with a valid mapping."""
        out = {}
        for k, p in self._mappings.items():
            if p and os.path.exists(p):
                out[k] = p
        return out
