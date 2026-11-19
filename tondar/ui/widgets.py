"""Custom widgets: segment map bar."""
from ..qt import QtCore, QtGui, QtWidgets, Qt  # noqa: F401


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
        from . import theme
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        modern = theme.is_modern()
        if modern:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("track"))
            p.drawRoundedRect(r, 5, 5)
            path = QtGui.QPainterPath()
            path.addRoundedRect(r, 5, 5)
            p.setClipPath(path)
            g = theme.color("accent")
        else:
            p.setPen(QtGui.QColor("#7a8a99"))
            p.setBrush(QtGui.QColor("white"))
            p.drawRect(r)
            gr = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
            gr.setColorAt(0, QtGui.QColor("#5aa6ff"))
            gr.setColorAt(0.5, QtGui.QColor("#1e6fd9"))
            gr.setColorAt(1, QtGui.QColor("#1557b0"))
            g = gr
        inner = r.adjusted(1, 1, -1, -1)
        w = inner.width()
        p.setPen(Qt.PenStyle.NoPen)
        if self.total > 0 and self.segments:
            for start, end, pos, active in self.segments:
                x0 = inner.left() + w * start / self.total
                x1 = inner.left() + w * pos / self.total
                if x1 > x0:
                    p.setBrush(QtGui.QBrush(g))
                    p.drawRect(QtCore.QRectF(x0, inner.top(), max(1.0, x1 - x0), inner.height()))
                if active:
                    p.setBrush(QtGui.QColor("#f59e0b"))
                    p.drawRect(QtCore.QRectF(x1, inner.top(), 2, inner.height()))
        else:
            p.setBrush(QtGui.QBrush(g))
            p.drawRect(QtCore.QRectF(inner.left(), inner.top(), w * self.done_fraction, inner.height()))
        p.end()
