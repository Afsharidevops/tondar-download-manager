"""Signed HLS link that stops working (like Filimo after the IP changes): the download fails with
403, then "Refresh address" with a new link continues from where it stopped (not from zero)."""
import http.server
import os
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, parse_qs

home = tempfile.mkdtemp()
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/c", XDG_DATA_HOME=home + "/d", QT_QPA_PLATFORM="offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.environ.get("YTDLP_STANDALONE"):
    os.makedirs(home + "/d/tondar/bin", exist_ok=True)
    os.symlink(os.environ["YTDLP_STANDALONE"], home + "/d/tondar/bin/yt-dlp_linux")

site = tempfile.mkdtemp()
subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=60:size=640x360:rate=25",
                "-f", "lavfi", "-i", "sine=duration=60", "-shortest", "-c:v", "libx264", "-g", "50", "-b:v", "1M",
                "-c:a", "aac", "-hls_time", "2", "-hls_playlist_type", "vod", os.path.join(site, "film.m3u8")],
               check=True)
valid = {"tok": "AAA"}
log = []


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=site, **k)

    def log_message(self, *a):
        pass

    def do_GET(self):
        q = parse_qs(urlsplit(self.path).query)
        tok = (q.get("token") or [""])[0]
        ref = self.headers.get("Referer", "")
        path = urlsplit(self.path).path
        if path.endswith(".ts"):
            tok = ref.rsplit("token=", 1)[-1] if "token=" in ref else tok
        log.append((path, tok))
        if path.endswith(".m3u8"):
            if tok != valid["tok"]:
                self.send_error(403)
                return
            body = open(os.path.join(site, "film.m3u8")).read().replace(".ts", f".ts?token={tok}").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        seg_tok = (q.get("token") or [""])[0]
        if seg_tok != valid["tok"]:
            self.send_error(403)
            return
        time.sleep(0.15)       # slow enough to stop half way
        self.path = path
        super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18900), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

from tondar.qt import QtWidgets, QtCore  # noqa: E402
from tondar.config import Settings  # noqa: E402
from tondar.manager import DownloadManager  # noqa: E402
from tondar.server import Bridge  # noqa: E402
from tondar.ui import main_window, theme  # noqa: E402
from tondar.models import KIND_MEDIA  # noqa: E402

app = QtWidgets.QApplication([])
theme.apply(app, "light")
s = Settings()
s["show_progress_dialog"] = False
s["max_connections"] = 2
m = DownloadManager(s)
w = main_window.MainWindow(m, s, Bridge(), {}, "/x")
main_window.QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)


def wait(cond, t=120):
    t0 = time.time()
    while time.time() - t0 < t and not cond():
        app.processEvents()
        time.sleep(0.05)


url1 = "http://127.0.0.1:18900/film.m3u8?film_id=1&token=AAA"
it = m.new_item(url1, "Film.mp4", kind=KIND_MEDIA, media_format="best", page_url=url1, media_title="Film",
                referer="http://127.0.0.1:18900/page")
m.add(it, start=True)
wait(lambda: it.downloaded > 1_500_000)
m.stop(it.id)
wait(lambda: it.id not in m.engines)
done_before = it.downloaded
segs_before = sum(1 for p, t in log if p.endswith(".ts"))
print("paused at", done_before, "bytes,", segs_before, "segments fetched")

valid["tok"] = "BBB"            # "internet changed": the old link is refused now
m.start(it.id)
wait(lambda: it.id not in m.engines and it.status in ("Error", "Complete"))
print("resume with old link ->", it.status, "|", it.error)

# browser sends the same video again with a fresh link -> Tondar offers to continue it
n_before = len(log)
w.on_browser_media({"url": "http://127.0.0.1:18900/film.m3u8?film_id=1&token=BBB", "format": None, "title": "Film",
                    "referer": "http://127.0.0.1:18900/page"})
wait(lambda: it.id not in m.engines and it.status in ("Error", "Complete"))
time.sleep(0.5)
wait(lambda: it.id not in m.engines and it.status in ("Error", "Complete"))
segs_after = sum(1 for p, t in log[n_before:] if p.endswith(".ts"))
dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", it.path],
                     capture_output=True, text=True).stdout.strip() if os.path.exists(it.path) else None
print("after refresh ->", it.status, it.error, "| items in list:", len(m.items), "| duration:", dur,
      f"| segments fetched after refresh: {segs_after} of 30")
srv.shutdown()
