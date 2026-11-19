"""Application entry point (single instance)."""
import os
import signal
import socket
import sys
import threading

from . import APP_NAME, APP_ID, VERSION
from .qt import QtCore, QtWidgets, exec_
from .config import Settings, SOCKET_PATH


def extension_dir():
    for d in (os.environ.get("TONDAR_EXT_DIR"), "/usr/share/tondar/extension",
              os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension", "build")):
        if d and os.path.isdir(d):
            return d
    return "/usr/share/tondar/extension"


def send_to_running(urls):
    """If another instance is running, hand it our URLs and return True."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(1)
            c.connect(SOCKET_PATH)
            c.sendall(("\n".join(urls) or "--show").encode())
        return True
    except OSError:
        return False


def listen_single_instance(bridge):
    try:
        os.unlink(SOCKET_PATH)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    srv.listen(4)

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
                with conn:
                    conn.settimeout(2)
                    data = b""
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        data += chunk
                bridge.activate_requested.emit(data.decode(errors="replace"))
            except OSError:
                return
    threading.Thread(target=loop, daemon=True).start()
    return srv


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"{APP_NAME} {VERSION}")
        return 0
    QtWidgets.QApplication.setApplicationName(APP_ID)
    QtWidgets.QApplication.setApplicationDisplayName(APP_NAME)
    QtWidgets.QApplication.setDesktopFileName(APP_ID)
    app = QtWidgets.QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    urls = [a for a in argv[1:] if "://" in a]
    if send_to_running(urls):
        return 0

    from .manager import DownloadManager
    from .server import ApiServer, Bridge
    from .ui.main_window import MainWindow

    settings = Settings()
    from .ui import theme
    theme.apply(app, settings.get("theme", "auto"))
    from .media import auto_update
    auto_update(settings)
    manager = DownloadManager(settings)
    bridge = Bridge()
    media_cache = {}
    server = ApiServer(settings, bridge, media_cache)
    api_ok = server.start()
    win = MainWindow(manager, settings, bridge, media_cache, extension_dir())
    if "--minimized" not in argv:
        win.show()
    if not api_ok:
        win.statusBar().showMessage(
            f"Browser integration disabled: port {settings['api_port']} is in use", 15000)

    # single-instance listener: a second "tondar <url>" call lands here
    def on_activate(data):
        win.show_window()
        for u in data.splitlines():
            if "://" in u:
                win.add_url(u.strip())
    bridge.activate_requested.connect(on_activate)
    listen_single_instance(bridge)

    for u in urls:
        QtCore.QTimer.singleShot(300, lambda u=u: win.add_url(u))

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    t = QtCore.QTimer()
    t.timeout.connect(lambda: None)   # let Python handle signals
    t.start(500)

    app.aboutToQuit.connect(manager.shutdown)
    app.aboutToQuit.connect(server.stop)
    app.aboutToQuit.connect(lambda: os.path.exists(SOCKET_PATH) and os.unlink(SOCKET_PATH))
    return exec_(app)


if __name__ == "__main__":
    sys.exit(main())
