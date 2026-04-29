"""Edge-based resize support for frameless windows.

Mix into a frameless QWidget by calling ``handle_resize_press`` from
``mousePressEvent`` and ``handle_resize_move`` from ``mouseMoveEvent``.
The helpers detect proximity to edges/corners, set the appropriate
cursor, and delegate the actual drag to the windowing system via
``QWindow.startSystemResize`` so the OS handles the resize natively.
"""

from PyQt6.QtCore import Qt


RESIZE_MARGIN = 6


def _edges_for_pos(widget, pos):
    x, y = pos.x(), pos.y()
    w, h = widget.width(), widget.height()
    m = RESIZE_MARGIN
    edges = Qt.Edge(0)
    if x <= m:
        edges |= Qt.Edge.LeftEdge
    elif x >= w - m:
        edges |= Qt.Edge.RightEdge
    if y <= m:
        edges |= Qt.Edge.TopEdge
    elif y >= h - m:
        edges |= Qt.Edge.BottomEdge
    return edges


def _cursor_for_edges(edges):
    horiz = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
    vert = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
    diagonal_main = (
        (edges & Qt.Edge.LeftEdge and edges & Qt.Edge.TopEdge)
        or (edges & Qt.Edge.RightEdge and edges & Qt.Edge.BottomEdge)
    )
    diagonal_anti = (
        (edges & Qt.Edge.RightEdge and edges & Qt.Edge.TopEdge)
        or (edges & Qt.Edge.LeftEdge and edges & Qt.Edge.BottomEdge)
    )
    if diagonal_main:
        return Qt.CursorShape.SizeFDiagCursor
    if diagonal_anti:
        return Qt.CursorShape.SizeBDiagCursor
    if horiz:
        return Qt.CursorShape.SizeHorCursor
    if vert:
        return Qt.CursorShape.SizeVerCursor
    return None


def handle_resize_press(widget, e):
    """Returns True if the press was consumed for a system resize."""
    if e.button() != Qt.MouseButton.LeftButton:
        return False
    edges = _edges_for_pos(widget, e.position().toPoint())
    if not edges:
        return False
    handle = widget.windowHandle()
    if handle is None:
        return False
    if handle.startSystemResize(edges):
        e.accept()
        return True
    return False


def handle_resize_move(widget, e):
    """Update cursor when hovering near an edge. Returns True if cursor was set."""
    if e.buttons() & Qt.MouseButton.LeftButton:
        # mid-drag: don't fight with the active operation
        return False
    edges = _edges_for_pos(widget, e.position().toPoint())
    cursor = _cursor_for_edges(edges)
    if cursor is None:
        widget.unsetCursor()
        return False
    widget.setCursor(cursor)
    return True
