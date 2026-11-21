"""`Tondar --self-test=<report.json>`: checks a packaged build end to end without network.

Used by the GitHub Actions jobs on Windows and macOS: a segmented download from a local
server, the GUI (main window + dialogs, offscreen), and the bundled ffmpeg.
"""
import hashlib
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback


def _server(data):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            start, end, status = 0, len(data) - 1, 200
            m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
            if m:
                start = int(m.group(1))
                end = min(int(m.group(2)) if m.group(2) else len(data) - 1, len(data) - 1)
                status = 206
            self.send_response(status)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="selftest.bin"')
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.end_headers()
            try:
                for i in range(start, end + 1, 65536):
                    self.wfile.write(data[i:min(i + 65536, end + 1)])
                    time.sleep(0.002)
            except OSError:
                pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def run(report_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if not os.environ.get("TONDAR_HOME"):
        os.environ["TONDAR_HOME"] = tempfile.mkdtemp(prefix="tondar-selftest-")
    report = {"ok": False, "checks": {}, "platform": sys.platform}

    def check(name, fn):
        try:
            report["checks"][name] = {"ok": True, "info": fn()}
        except Exception as e:  # noqa: BLE001
            report["checks"][name] = {"ok": False, "error": f"{e}", "trace": traceback.format_exc()[-1500:]}

    from . import VERSION, osutil
    report["version"] = VERSION
    report["frozen"] = osutil.FROZEN

    # 1. segmented download with resume-capable server
    def download():
        from .engine import HttpDownloader, SpeedLimiter
        from .models import DownloadItem
        data = os.urandom(6 * 1024 * 1024 + 4321)
        srv = _server(data)
        out = tempfile.mkdtemp()
        it = DownloadItem(url=f"http://127.0.0.1:{srv.server_address[1]}/f", filename="f.bin", save_dir=out)
        done, res = threading.Event(), {}
        settings = {"max_connections": 8, "retries": 3, "timeout": 10, "proxy": "", "use_system_proxy": False,
                    "user_agent": "selftest"}
        eng = HttpDownloader(it, settings, SpeedLimiter(lambda: 0), lambda e, s, err: (res.update(s=s, e=err), done.set()))
        eng.start()
        seen = 0
        while not done.wait(0.1):
            seen = max(seen, len(eng.snapshot()))
        srv.shutdown()
        if res.get("s") != "completed":
            raise RuntimeError(f"download {res}")
        with open(it.path, "rb") as f:
            if hashlib.sha256(f.read()).digest() != hashlib.sha256(data).digest():
                raise RuntimeError("hash mismatch")
        return f"{len(data)} bytes, {seen} segments"
    check("segmented_download", download)

    # 2. GUI
    def gui():
        from .qt import QtWidgets, QtCore
        from .config import Settings
        from .manager import DownloadManager
        from .server import Bridge
        from .ui import theme
        from .ui.main_window import MainWindow
        from .ui.dialogs import OptionsDialog
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
        s = Settings()
        theme.apply(app, "light")
        m = DownloadManager(s)
        w = MainWindow(m, s, Bridge(), {}, "")
        w.show()
        o = OptionsDialog(s, w, "")
        o.show()
        t0 = time.time()
        while time.time() - t0 < 1.0:
            app.processEvents()
            time.sleep(0.02)
        img = os.path.splitext(report_path)[0] + ".png"
        w.grab().save(img)
        theme.apply(app, "dark")
        w.apply_theme("dark")
        app.processEvents()
        from .ui.telegram_dialog import TelegramDialog
        tgd = TelegramDialog(m, s, w)
        tgd.show()
        app.processEvents()
        tgd.close()
        o.close()
        m.shutdown()
        QtCore.QTimer.singleShot(0, app.quit)
        return {"screenshot": img}
    check("gui", gui)

    # 3. helpers that ship inside the app
    def tools():
        from .config import find_tool
        ff = find_tool("ffmpeg")
        info = {"ffmpeg": ff}
        if osutil.FROZEN:
            if not ff:
                raise RuntimeError("bundled ffmpeg missing")
            out = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=30,
                                 **osutil.subprocess_kwargs())
            if out.returncode != 0:
                raise RuntimeError("ffmpeg -version failed: " + out.stderr[-300:])
            info["ffmpeg_version"] = out.stdout.splitlines()[0] if out.stdout else ""
        return info
    check("tools", tools)

    # 4. TLS: the frozen builds must use the OS certificate store (truststore)
    def tls():
        from .engine import ssl_context, build_opener
        ctx = ssl_context()
        info = {"context": type(ctx).__module__ + "." + type(ctx).__name__}
        if osutil.FROZEN and "truststore" not in info["context"]:
            raise RuntimeError("truststore is not bundled: " + info["context"])
        if os.environ.get("TONDAR_SELFTEST_TDL") == "1":
            o = build_opener()
            o.addheaders = [("User-Agent", "tondar-dm")]
            with o.open("https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS", timeout=60) as r:
                info["github"] = r.status
        return info
    check("tls", tls)

    # 5. optional Telegram support: the tdl build for this OS downloads and runs (CI only - needs internet)
    if os.environ.get("TONDAR_SELFTEST_TDL") == "1":
        def telegram():
            from . import telegram as tg
            from .config import Settings
            tg.install_tdl(Settings(), log=lambda *_: None)
            v = tg.tdl_version()
            if not v:
                raise RuntimeError("tdl does not run")
            return {"tdl": tg.tdl_path(), "version": v}
        check("telegram", telegram)

    def paths():
        from .config import CONFIG_DIR, DATA_DIR, Settings
        from . import app as appmod
        ext = appmod.extension_dir()
        info = {"config": str(CONFIG_DIR), "data": str(DATA_DIR), "downloads": str(Settings().base_dir()),
                "extension": ext}
        if osutil.FROZEN:
            for sub in ("chrome/manifest.json", "firefox/manifest.json"):
                if not os.path.exists(os.path.join(ext, sub)):
                    raise RuntimeError(f"missing {sub} in {ext}")
        return info
    check("paths", paths)

    report["ok"] = all(c["ok"] for c in report["checks"].values())
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1
