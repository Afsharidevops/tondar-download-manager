"""Modern light / dark theme (Fusion + stylesheet) and the classic native look."""
from ..qt import QtGui, QtWidgets
from . import icons

LIGHT = dict(
    bg="#f4f6f9", surface="#ffffff", sidebar="#f8f9fb", border="#e3e7ed", text="#1f2933",
    muted="#6b7785", hover="#eef2f7", accent="#2563eb", accent_soft="#e3ecfd", track="#e6eaf0",
    scroll="#c9d1db", ok="#16a34a", err="#dc2626", warn="#d97706",
)
DARK = dict(
    bg="#18191c", surface="#202226", sidebar="#1c1d21", border="#2e3137", text="#e7e9ec",
    muted="#9aa3ad", hover="#2a2d33", accent="#4f8cff", accent_soft="#263553", track="#2f333a",
    scroll="#454a52", ok="#22c55e", err="#f87171", warn="#fbbf24",
)

QSS = """
QMainWindow, QDialog {{ background: {bg}; }}
QWidget {{ color: {text}; }}
QToolBar#main_toolbar {{ background: {surface}; border: none; border-bottom: 1px solid {border};
    padding: 6px 10px; spacing: 2px; }}
QToolBar#main_toolbar QToolButton {{ border: none; border-radius: 8px; padding: 6px 6px 4px 6px;
    min-width: 54px; color: {text}; font-size: 12px; }}
QToolBar#main_toolbar QToolButton:hover {{ background: {hover}; }}
QToolBar#main_toolbar QToolButton:pressed, QToolBar#main_toolbar QToolButton:checked
    {{ background: {accent_soft}; color: {accent}; }}
QToolBar#main_toolbar QToolButton:disabled {{ color: {muted}; }}
QLineEdit#search {{ border: 1px solid {border}; border-radius: 16px; padding: 6px 14px;
    min-width: 170px; background: {bg}; }}
QLineEdit#search:focus {{ border-color: {accent}; background: {surface}; }}

QTreeWidget#sidebar {{ background: {sidebar}; border: none; border-right: 1px solid {border};
    padding: 10px 8px; font-size: 13px; outline: 0; }}
QTreeWidget#sidebar::item {{ height: 30px; border-radius: 7px; padding-left: 4px; }}
QTreeWidget#sidebar::item:hover {{ background: {hover}; }}
QTreeWidget#sidebar::item:selected {{ background: {accent_soft}; color: {accent}; }}
QTreeWidget#sidebar {{ show-decoration-selected: 0; }}
QTreeWidget#sidebar::branch, QTreeWidget#sidebar::branch:selected {{ background: transparent; border: none; }}
QFrame[frameShape="4"] {{ border: none; border-top: 1px solid {border}; max-height: 1px; }}

QTreeView#downloads {{ background: {surface}; border: none; font-size: 13px; outline: 0;
    selection-background-color: {accent_soft}; selection-color: {text}; }}
QTreeView#downloads::item {{ height: 36px; border: none; padding-left: 8px; }}
QTreeView#downloads::item:hover {{ background: {hover}; }}
QTreeView#downloads::item:selected {{ background: {accent_soft}; color: {text}; }}
QTreeWidget, QListWidget, QTableWidget {{ background: {surface}; border: 1px solid {border};
    border-radius: 8px; outline: 0; }}
QTreeWidget::item, QListWidget::item {{ height: 28px; }}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected
    {{ background: {accent_soft}; color: {text}; }}
QHeaderView::section {{ background: {surface}; color: {muted}; border: none;
    border-bottom: 1px solid {border}; padding: 7px 8px; font-weight: 600; }}

QLineEdit, QComboBox, QSpinBox, QTimeEdit, QPlainTextEdit {{ border: 1px solid {border};
    border-radius: 7px; padding: 5px 8px; background: {surface}; selection-background-color: {accent};
    selection-color: white; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus, QPlainTextEdit:focus
    {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border};
    selection-background-color: {accent_soft}; selection-color: {text}; }}
QPushButton {{ border: 1px solid {border}; border-radius: 7px; padding: 6px 16px; background: {surface}; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:default {{ background: {accent}; color: white; border-color: {accent}; }}
QPushButton:default:hover {{ background: {accent}; }}
QPushButton:disabled {{ color: {muted}; }}
QToolButton {{ border-radius: 6px; padding: 3px 8px; }}

QProgressBar {{ border: none; border-radius: 6px; background: {track}; }}
QProgressBar::chunk {{ border-radius: 6px; background: {accent}; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 10px; top: -1px; background: {surface}; }}
QTabBar::tab {{ padding: 8px 16px; border: none; color: {muted}; background: transparent; }}
QTabBar::tab:selected {{ color: {accent}; border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover {{ color: {text}; }}
QGroupBox {{ border: 1px solid {border}; border-radius: 8px; margin-top: 14px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {muted}; }}

QStatusBar {{ background: {surface}; color: {muted}; border-top: 1px solid {border}; }}
QMenuBar {{ background: {surface}; border-bottom: 1px solid {border}; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: {hover}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {text}; }}
QMenu::item:disabled {{ color: {muted}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 6px; }}

QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle {{ background: {scroll}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {border}; width: 1px; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px 6px; }}
QLabel#hint {{ color: {muted}; }}
"""

current = dict(LIGHT)
mode = "light"
_native = {}          # style name, palette and font before we touched anything


def system_is_dark():
    # Qt 6.5+: the OS setting (Windows dark mode, macOS appearance, GNOME/KDE colour scheme)
    try:
        from ..qt import Qt
        scheme = QtWidgets.QApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except AttributeError:
        pass
    pal = _native.get("palette") or QtWidgets.QApplication.palette()
    return pal.color(QtGui.QPalette.ColorRole.Window).lightness() < 110


def apply(app, name):
    """name: auto | light | dark | classic"""
    global current, mode
    if not _native:
        _native["style"] = app.style().objectName()
        _native["palette"] = QtGui.QPalette(app.palette())
        _native["font"] = QtGui.QFont(app.font())
    if name == "classic":
        mode = "classic"
        current = dict(LIGHT)
        icons.set_flat(False)
        app.setStyleSheet("")
        if _native.get("style"):
            app.setStyle(_native["style"])
        app.setPalette(_native["palette"])
        app.setFont(_native["font"])
        return
    if name == "auto":
        # judge the *system* setting, not the palette we may have installed earlier
        dark = system_is_dark()
    else:
        dark = name == "dark"
    mode = "dark" if dark else "light"
    c = DARK if dark else LIGHT
    current = dict(c)
    icons.set_flat(True)
    app.setStyle("Fusion")
    R = QtGui.QPalette.ColorRole
    pal = QtGui.QPalette()
    for role, key in ((R.Window, "bg"), (R.Base, "surface"), (R.AlternateBase, "sidebar"),
                      (R.Text, "text"), (R.WindowText, "text"), (R.Button, "surface"),
                      (R.ButtonText, "text"), (R.Highlight, "accent"), (R.ToolTipBase, "surface"),
                      (R.ToolTipText, "text"), (R.PlaceholderText, "muted"), (R.Link, "accent")):
        pal.setColor(role, QtGui.QColor(c[key]))
    pal.setColor(R.HighlightedText, QtGui.QColor("white"))
    for grp in (QtGui.QPalette.ColorGroup.Disabled,):
        for role in (R.Text, R.WindowText, R.ButtonText):
            pal.setColor(grp, role, QtGui.QColor(c["muted"]))
    app.setPalette(pal)
    f = app.font()
    if f.pointSizeF() < 10:
        f.setPointSizeF(10)
        app.setFont(f)
    app.setStyleSheet(QSS.format(**c))


def color(key):
    return QtGui.QColor(current[key])


def is_modern():
    return mode != "classic"
