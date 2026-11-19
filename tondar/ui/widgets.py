"""Custom widgets: segment map bar."""
from ..qt import QtCore, QtGui, QtWidgets, Qt


class SegmentBar(QtWidgets.QWidget):
    """Shows which byte ranges are downloaded, one block per connection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 0
        self.segments = []      # (start, end, pos, active)
        self.done_fraction = 0.0
        self.setMinimumHeight(18)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def update_state(self, total, segments, fraction):
        self.total, self.segments, self.done_fraction = total, segments, fraction
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QtGui.QColor("#7a8a99"))
        p.setBrush(QtGui.QColor("white"))
        p.drawRect(r)
        inner = r.adjusted(1, 1, 0, 0)
        w = inner.width()
        g = QtGui.QLinearGradient(0, inner.top(), 0, inner.bottom())
        g.setColorAt(0, QtGui.QColor("#5aa6ff"))
        g.setColorAt(0.5, QtGui.QColor("#1e6fd9"))
        g.setColorAt(1, QtGui.QColor("#1557b0"))
        p.setPen(Qt.PenStyle.NoPen)
        if self.total > 0 and self.segments:
            for start, end, pos, active in self.segments:
                x0 = inner.left() + w * start / self.total
                x1 = inner.left() + w * pos / self.total
                if x1 > x0:
                    p.setBrush(QtGui.QBrush(g))
                    p.drawRect(QtCore.QRectF(x0, inner.top(), max(1.0, x1 - x0), inner.height()))
                if active:
                    p.setBrush(QtGui.QColor("#ffb300"))
                    p.drawRect(QtCore.QRectF(x1, inner.top(), 2, inner.height()))
        else:
            p.setBrush(QtGui.QBrush(g))
            p.drawRect(QtCore.QRectF(inner.left(), inner.top(), w * self.done_fraction, inner.height()))
        p.end()
