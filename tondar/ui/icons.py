"""Original toolbar / file-type icons, drawn with QPainter (no image assets)."""
from ..qt import QtCore, QtGui, Qt

_cache = {}

S = 64  # design grid


def _pm(draw, size=S):
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.scale(size / S, size / S)
    draw(p)
    p.end()
    return pm


def _grad(c1, c2, y0=4, y1=60):
    g = QtGui.QLinearGradient(0, y0, 0, y1)
    g.setColorAt(0, QtGui.QColor(c1))
    g.setColorAt(1, QtGui.QColor(c2))
    return QtGui.QBrush(g)


def _pen(color="#00000055", w=2.0):
    return QtGui.QPen(QtGui.QColor(color), w)


def _circle(p, c1, c2):
    p.setPen(_pen("#00000040", 2))
    p.setBrush(_grad(c1, c2))
    p.drawEllipse(QtCore.QRectF(6, 6, 52, 52))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(255, 255, 255, 60))
    p.drawEllipse(QtCore.QRectF(14, 9, 36, 20))


def draw_add(p):
    _circle(p, "#5fd068", "#1f8f2c")
    p.setBrush(QtGui.QColor("white"))
    p.drawRoundedRect(QtCore.QRectF(28, 17, 8, 30), 2, 2)
    p.drawRoundedRect(QtCore.QRectF(17, 28, 30, 8), 2, 2)


def draw_resume(p):
    _circle(p, "#4fa3f7", "#1859b8")
    p.setBrush(QtGui.QColor("white"))
    path = QtGui.QPainterPath()
    path.moveTo(25, 18)
    path.lineTo(47, 32)
    path.lineTo(25, 46)
    path.closeSubpath()
    p.drawPath(path)


def _stop_sq(p, x, y, s):
    p.setPen(_pen("#00000050", 2))
    p.setBrush(_grad("#ff7a6b", "#c9271b", y, y + s))
    p.drawRoundedRect(QtCore.QRectF(x, y, s, s), 6, 6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("white"))
    p.drawRoundedRect(QtCore.QRectF(x + s * .32, y + s * .32, s * .36, s * .36), 2, 2)


def draw_stop(p):
    _stop_sq(p, 8, 8, 48)


def draw_stop_all(p):
    _stop_sq(p, 4, 4, 36)
    _stop_sq(p, 24, 24, 36)


def draw_delete(p, check=False):
    p.setPen(_pen("#00000060", 2))
    p.setBrush(_grad("#e9eef3", "#9aa7b4"))
    body = QtGui.QPainterPath()
    body.moveTo(16, 20)
    body.lineTo(48, 20)
    body.lineTo(44, 58)
    body.lineTo(20, 58)
    body.closeSubpath()
    p.drawPath(body)
    p.setBrush(_grad("#c9d2db", "#7d8b99", 10, 20))
    p.drawRoundedRect(QtCore.QRectF(11, 12, 42, 8), 3, 3)
    p.drawRoundedRect(QtCore.QRectF(26, 6, 12, 7), 2, 2)
    p.setPen(_pen("#5d6b78", 2.5))
    for x in (25, 32, 39):
        p.drawLine(QtCore.QPointF(x, 26), QtCore.QPointF(x, 52))
    if check:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_grad("#5fd068", "#1f8f2c", 32, 62))
        p.drawEllipse(QtCore.QRectF(34, 34, 28, 28))
        p.setPen(QtGui.QPen(QtGui.QColor("white"), 4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QtGui.QPainterPath()
        path.moveTo(41, 48)
        path.lineTo(46, 53)
        path.lineTo(55, 42)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


def draw_options(p):
    p.setPen(_pen("#00000060", 2))
    p.setBrush(_grad("#b8c4d0", "#5b6b7b"))
    path = QtGui.QPainterPath()
    import math
    teeth = 8
    for i in range(teeth * 2):
        a = math.pi * i / teeth
        r = 27 if i % 2 == 0 else 21
        a2 = a + math.pi / teeth
        for aa in (a, a2):
            x, y = 32 + r * math.cos(aa), 32 + r * math.sin(aa)
            if i == 0 and aa == a:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
    path.closeSubpath()
    hole = QtGui.QPainterPath()
    hole.addEllipse(QtCore.QRectF(23, 23, 18, 18))
    p.drawPath(path.subtracted(hole))


def draw_scheduler(p):
    p.setPen(_pen("#00000060", 2))
    p.setBrush(_grad("#ffffff", "#d5dde6"))
    p.drawEllipse(QtCore.QRectF(6, 6, 52, 52))
    p.setPen(_pen("#2a6fd1", 3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QtCore.QRectF(10, 10, 44, 44))
    p.setPen(QtGui.QPen(QtGui.QColor("#333"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QtCore.QPointF(32, 32), QtCore.QPointF(32, 17))
    p.drawLine(QtCore.QPointF(32, 32), QtCore.QPointF(43, 38))
    p.setBrush(QtGui.QColor("#d33"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QtCore.QRectF(29, 29, 6, 6))


def _queue_lines(p):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_grad("#7f8c99", "#4b5864"))
    for i, y in enumerate((8, 20, 32)):
        p.drawRoundedRect(QtCore.QRectF(4, y, 34 - i * 4, 7), 2, 2)


def draw_start_queue(p):
    _queue_lines(p)
    p.setPen(_pen("#00000040", 2))
    p.setBrush(_grad("#5fd068", "#1f8f2c", 28, 62))
    p.drawEllipse(QtCore.QRectF(28, 28, 33, 33))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("white"))
    path = QtGui.QPainterPath()
    path.moveTo(40, 36)
    path.lineTo(53, 44.5)
    path.lineTo(40, 53)
    path.closeSubpath()
    p.drawPath(path)


def draw_stop_queue(p):
    _queue_lines(p)
    _stop_sq(p, 28, 28, 33)


def draw_speed(p):
    import math
    p.setPen(_pen("#00000060", 2))
    p.setBrush(_grad("#3c4a57", "#1d252d"))
    p.drawPie(QtCore.QRectF(4, 10, 56, 56), 0, 180 * 16)
    for i, col in enumerate(("#4cd964", "#ffcc00", "#ff3b30")):
        p.setPen(QtGui.QPen(QtGui.QColor(col), 5))
        p.drawArc(QtCore.QRectF(10, 16, 44, 44), (180 - i * 60) * 16, -60 * 16)
    p.setPen(QtGui.QPen(QtGui.QColor("white"), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    a = math.radians(50)
    p.drawLine(QtCore.QPointF(32, 38), QtCore.QPointF(32 + 20 * math.cos(a), 38 - 20 * math.sin(a)))


def draw_app(p):
    """App logo: lightning bolt over a down arrow ("Tondar" = thunder)."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_grad("#2b7de9", "#0b3f91"))
    p.drawRoundedRect(QtCore.QRectF(2, 2, 60, 60), 14, 14)
    p.setBrush(_grad("#ffe55c", "#ffab1a", 8, 56))
    bolt = QtGui.QPainterPath()
    for i, (x, y) in enumerate([(36, 6), (16, 36), (30, 36), (24, 58), (48, 26), (34, 26), (40, 6)]):
        (bolt.moveTo if i == 0 else bolt.lineTo)(x, y)
    bolt.closeSubpath()
    p.drawPath(bolt)


def draw_video(p):
    p.setPen(_pen("#00000050", 1.5))
    p.setBrush(_grad("#5a6cff", "#2a35b8"))
    p.drawRoundedRect(QtCore.QRectF(6, 12, 52, 40), 6, 6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("white"))
    path = QtGui.QPainterPath()
    path.moveTo(26, 22)
    path.lineTo(42, 32)
    path.lineTo(26, 42)
    path.closeSubpath()
    p.drawPath(path)


def draw_music(p):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_grad("#ff7ac0", "#c2186b"))
    p.drawEllipse(QtCore.QRectF(8, 40, 18, 14))
    p.drawEllipse(QtCore.QRectF(36, 34, 18, 14))
    p.drawRect(QtCore.QRectF(22, 12, 4, 36))
    p.drawRect(QtCore.QRectF(50, 6, 4, 36))
    poly = QtGui.QPolygonF([QtCore.QPointF(22, 12), QtCore.QPointF(54, 6),
                            QtCore.QPointF(54, 14), QtCore.QPointF(22, 20)])
    p.drawPolygon(poly)


def draw_zip(p):
    p.setPen(_pen("#00000050", 1.5))
    p.setBrush(_grad("#ffd35c", "#d9961a"))
    p.drawRoundedRect(QtCore.QRectF(10, 6, 44, 52), 4, 4)
    p.setBrush(QtGui.QColor("#6b4b10"))
    p.setPen(Qt.PenStyle.NoPen)
    for y in range(8, 40, 6):
        p.drawRect(QtCore.QRectF(29 if (y // 6) % 2 else 33, y, 4, 3))
    p.drawRoundedRect(QtCore.QRectF(27, 40, 10, 10), 2, 2)


def draw_doc(p):
    p.setPen(_pen("#00000050", 1.5))
    p.setBrush(_grad("#ffffff", "#dfe6ee"))
    path = QtGui.QPainterPath()
    path.moveTo(12, 4)
    path.lineTo(40, 4)
    path.lineTo(52, 16)
    path.lineTo(52, 60)
    path.lineTo(12, 60)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(_pen("#3b7dd8", 3))
    for y in (24, 32, 40, 48):
        p.drawLine(QtCore.QPointF(19, y), QtCore.QPointF(45, y))


def draw_program(p):
    p.setPen(_pen("#00000050", 1.5))
    p.setBrush(_grad("#9be15d", "#3f9b1f"))
    p.drawRoundedRect(QtCore.QRectF(6, 10, 52, 44), 5, 5)
    p.setBrush(QtGui.QColor("#1f3d0f"))
    p.drawRect(QtCore.QRectF(10, 20, 44, 30))
    p.setPen(_pen("#9be15d", 3))
    p.drawLine(QtCore.QPointF(15, 27), QtCore.QPointF(22, 32))
    p.drawLine(QtCore.QPointF(22, 32), QtCore.QPointF(15, 37))
    p.drawLine(QtCore.QPointF(26, 39), QtCore.QPointF(36, 39))


def draw_general(p):
    draw_doc(p)


def draw_folder(p, open_=False):
    p.setPen(_pen("#00000040", 1.5))
    p.setBrush(_grad("#ffd970", "#e9a92a"))
    path = QtGui.QPainterPath()
    path.moveTo(4, 14)
    path.lineTo(24, 14)
    path.lineTo(30, 20)
    path.lineTo(60, 20)
    path.lineTo(60, 54)
    path.lineTo(4, 54)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(_grad("#ffe9a6", "#f3be47", 24, 54))
    p.drawRect(QtCore.QRectF(4, 26, 56, 28))


def draw_unfinished(p):
    draw_folder(p)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#2a7de1"))
    path = QtGui.QPainterPath()
    path.moveTo(32, 30)
    path.lineTo(46, 44)
    path.lineTo(18, 44)
    path.closeSubpath()
    p.drawRect(QtCore.QRectF(28, 44, 8, 8))
    p.drawPath(path)


def draw_finished(p):
    draw_folder(p)
    p.setPen(QtGui.QPen(QtGui.QColor("#1f8f2c"), 5, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    path = QtGui.QPainterPath()
    path.moveTo(20, 38)
    path.lineTo(28, 46)
    path.lineTo(44, 30)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def draw_queue(p):
    _queue_lines(p)
    p.setBrush(_grad("#7f8c99", "#4b5864"))
    p.drawRoundedRect(QtCore.QRectF(4, 44, 22, 7), 2, 2)


def draw_all(p):
    draw_folder(p)
    p.setPen(_pen("#2a7de1", 4))
    p.drawLine(QtCore.QPointF(32, 28), QtCore.QPointF(32, 48))
    p.drawLine(QtCore.QPointF(24, 40), QtCore.QPointF(32, 48))
    p.drawLine(QtCore.QPointF(40, 40), QtCore.QPointF(32, 48))


DRAWERS = {
    "add": draw_add, "resume": draw_resume, "stop": draw_stop, "stop_all": draw_stop_all,
    "delete": draw_delete, "delete_done": lambda p: draw_delete(p, True), "options": draw_options,
    "scheduler": draw_scheduler, "start_queue": draw_start_queue, "stop_queue": draw_stop_queue,
    "speed": draw_speed, "app": draw_app, "Video": draw_video, "Music": draw_music,
    "Compressed": draw_zip, "Documents": draw_doc, "Programs": draw_program, "General": draw_general,
    "folder": draw_folder, "unfinished": draw_unfinished, "finished": draw_finished,
    "queue": draw_queue, "all": draw_all,
}


def icon(name):
    if name not in _cache:
        ic = QtGui.QIcon()
        draw = DRAWERS.get(name, draw_general)
        for size in (16, 24, 32, 48, 64, 128):
            ic.addPixmap(_pm(draw, size))
        _cache[name] = ic
    return _cache[name]


def pixmap(name, size):
    return _pm(DRAWERS.get(name, draw_general), size)
