"""Tabular view of recorded events for inspection and editing."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
)


class EventListView(QTableWidget):
    """Read-only table of events with multi-row selection."""

    selection_changed = pyqtSignal(list)  # emits list of selected event indices

    HEADERS = ['#', '시간 (ms)', '종류', '키 / 버튼', '동작', '🖼']

    def __init__(self):
        super().__init__()
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)

        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        self.setColumnWidth(0, 50)
        self.setColumnWidth(1, 90)
        self.setColumnWidth(2, 110)
        self.setColumnWidth(3, 140)
        self.setColumnWidth(4, 120)

        self.itemSelectionChanged.connect(self._on_selection_changed)

    def set_events(self, events):
        self.blockSignals(True)
        self.setRowCount(len(events))
        for i, e in enumerate(events):
            self._populate_row(i, e)
        self.blockSignals(False)
        self.selection_changed.emit([])

    def _populate_row(self, i, e):
        cells = [
            str(i + 1),
            f"{e.get('t_ms', 0)}",
            e.get('type', ''),
            self._key_label(e),
            self._action_label(e),
            '✓' if e.get('icon') else '',
        ]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col in (0, 1):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            elif col == 5:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(i, col, item)

    @staticmethod
    def _key_label(e):
        return e.get('key', '') or e.get('button', '') or ''

    @staticmethod
    def _action_label(e):
        t = e.get('type', '')
        if t in ('key_press', 'mouse_press'):
            return '↓ press'
        if t in ('key_release', 'mouse_release'):
            return '↑ release'
        if t == 'scroll':
            dx, dy = e.get('dx', 0), e.get('dy', 0)
            return f'scroll ({dx}, {dy})'
        return ''

    def selected_indices(self):
        return sorted({item.row() for item in self.selectedItems()})

    def _on_selection_changed(self):
        self.selection_changed.emit(self.selected_indices())

    def select_all_rows(self):
        self.selectAll()

    def clear_selection(self):
        self.clearSelection()
