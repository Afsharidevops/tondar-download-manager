"""Application entry point (single instance)."""
import os
import signal
import socket
import sys
import threading

from . import APP_NAME, APP_ID, VERSION, osutil
from .qt import QtCore, QtWidgets, exec_
from .config import Settings, SOCKET_PATH, DATA_DIR


def extension_dir():
    if osutil.FROZEN:
        # Windows/macOS build: copy the extensions out of the app bundle to a normal folder
        # (Chrome's "Load unpacked" cannot browse inside Tondar.app or Program Files reliably)
        import shutil
        src = os.path.join(getattr(sys, "_MEIPASS", ""), "extension")
        dst = DATA_DIR / "extension"
        stamp = dst / ".version"
        try:
            if os.path.isdir(src) and (not stamp.exists() or stamp.read_text() != VERSION):
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
                stamp.write_text(VERSION)
        except OSError as e:
            print("could not copy extension:", e)
        return str(dst)
    for d in (os.environ.get("TONDAR_EXT_DIR"), "/usr/share/tondar/extension",
              os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension", "build")):
        if d and os.path.isdir(d):
            return d
    return "/usr/share/tondar/extension"


def send_to_running(urls, port=None):
    """If another instance is running, hand it our URLs and return True."""
    if osutil.IS_WIN:      # no Unix sockets: ask the running app through its local API
        import json
        import urllib.request
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/activate", method="POST",
                                         data=json.dumps({"urls": urls}).encode(),
                                         headers={"X-Tondar-Client": "1", "Content-Type": "application/json"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=1.5) as r:
                return json.loads(r.read()).get("app") == "tondar"
        except Exception:
            return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(1)
            c.connect(SOCKET_PATH)
            c.sendall(("\n".join(urls) or "--show").encode())
        return True
    except OSError:
        return False


def listen_single_instance(bridge):
    if osutil.IS_WIN:
        return None            # handled by the local API (/activate)
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
    st = next((a for a in argv if a.startswith("--self-test")), None)
    if st:
        from .selftest import run
        return run(st.partition("=")[2] or "tondar-selftest.json")
    QtWidgets.QApplication.setApplicationName(APP_ID)
    QtWidgets.QApplication.setApplicationDisplayName(APP_NAME)
    QtWidgets.QApplication.setDesktopFileName(APP_ID)
    app = QtWidgets.QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    urls = [a for a in argv[1:] if "://" in a]
    if send_to_running(urls, Settings()["api_port"]):
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
