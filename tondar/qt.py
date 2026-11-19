"""Small compatibility layer so the app runs on PyQt6 (preferred) or PyQt5.

Ubuntu 22.04 ships python3-pyqt5 and python3-pyqt6, 24.04+/26.04 ship both too;
whichever is installed is used.
"""
import os as _os

try:
    if _os.environ.get("TONDAR_QT") == "5":
        raise ImportError("PyQt5 forced")
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt6.QtCore import pyqtSignal as Signal, pyqtSlot as Slot  # noqa: F401
    from PyQt6.QtGui import QAction, QActionGroup  # noqa: F401
    QT6 = True
except ImportError:  # pragma: no cover - fallback path
    from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt5.QtCore import pyqtSignal as Signal, pyqtSlot as Slot  # noqa: F401
    from PyQt5.QtWidgets import QAction, QActionGroup  # noqa: F401
    QT6 = False

Qt = QtCore.Qt


def exec_(obj, *args):
    """Call exec()/exec_() on dialogs, menus, apps regardless of binding."""
    fn = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return fn(*args)


def dialog_accepted(code):
    return code == QtWidgets.QDialog.DialogCode.Accepted or code == 1
