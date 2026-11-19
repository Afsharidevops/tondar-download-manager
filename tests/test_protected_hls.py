"""A CDN that only serves the player (like arvanvod.ir): every playlist/segment request must carry
Referer = <player origin>/ and Origin = <player origin>, otherwise 403.

1. Real Chrome + extension: page (127.0.0.1:18700) embeds player iframe (localhost:18701) which fetches
   HLS from the CDN (127.0.0.1:18702). The panel must resolve + download the full video.
2. Import of a "name|url" list (videos.txt style) with the Referer typed into the dialog.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PLAYER = "http://localhost:18701"
site = tempfile.mkdtemp()
cdn = os.path.join(site, "cdn")
os.makedirs(cdn)
ff = ["ffmpeg", "-loglevel", "error", "-y"]
subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=duration=40:size=854x480:rate=25", "-f", "lavfi", "-i",
                     "sine=duration=40", "-shortest", "-c:v", "libx264", "-g", "50", "-b:v", "1M", "-c:a", "aac",
                     "-hls_time", "2", "-hls_playlist_type", "vod", os.path.join(cdn, "index-f4-v1-a1.m3u8")],
               check=True)
with open(os.path.join(cdn, "master.m3u8"), "w") as f:
    f.write("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480\nindex-f4-v1-a1.m3u8\n")
os.makedirs(os.path.join(site, "page"))
os.makedirs(os.path.join(site, "player"))
open(os.path.join(site, "page", "index.html"), "w").write(
    f"""<!doctype html><html dir="rtl"><head><meta charset="utf-8"><title>Backup Strategy - آروان آکادمی</title></head>
<body style="margin:0"><h3>درس</h3><iframe src="{PLAYER}/embed.html" width="960" height="560"
style="border:0"></iframe></body></html>""")
open(os.path.join(site, "player", "embed.html"), "w").write(
    """<!doctype html><html><body style="margin:0;background:#000">
<video id="v" width="940" height="530" controls muted></video>
<script>
fetch('http://127.0.0.1:18702/master.m3u8').then(r => r.text()).then(() =>
fetch('http://127.0.0.1:18702/index-f4-v1-a1.m3u8')).then(r => r.text());
</script></body></html>""")

rejected = []


def make(root, protect):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=root, **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def do_GET(self):
            if protect:
                ref, org = self.headers.get("Referer", ""), self.headers.get("Origin", "")
                if ref != PLAYER + "/" or org != PLAYER:
                    rejected.append((self.path, ref, org))
                    self.send_error(403)
                    return
            if self.path.split("?")[0].endswith(".m3u8"):
                self.extensions_map = dict(self.extensions_map, **{".m3u8": "application/vnd.apple.mpegurl"})
            super().do_GET()
    return H


for port, sub, prot in ((18700, "page", False), (18701, "player", False), (18702, "cdn", True)):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), make(os.path.join(site, sub), prot))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

home = tempfile.mkdtemp()
env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home + "/.config", XDG_DATA_HOME=home + "/.local/share",
           QT_QPA_PLATFORM="offscreen", PYTHONPATH=ROOT)
os.makedirs(home + "/.config/tondar")
json.dump({"show_file_info_dialog": False, "show_progress_dialog": False, "show_complete_dialog": False,
           "download_dir": home + "/dl"}, open(home + "/.config/tondar/settings.json", "w"))
os.makedirs(home + "/.local/share/tondar/bin")
for name in ("yt-dlp_linux",):
    src = os.environ.get("YTDLP_STANDALONE")
    if src:
        os.symlink(src, home + "/.local/share/tondar/bin/" + name)
app = subprocess.Popen([sys.executable, "-m", "tondar"], env=env, cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(3)


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 path], capture_output=True, text=True).stdout.strip() or 0)


from playwright.sync_api import sync_playwright  # noqa: E402
ext = os.path.join(ROOT, "extension", "build", "chrome")
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        tempfile.mkdtemp(), executable_path="/usr/bin/google-chrome", headless=False,
        args=["--headless=new", f"--disable-extensions-except={ext}", f"--load-extension={ext}"],
        viewport={"width": 1100, "height": 700})
    time.sleep(1.5)
    page = ctx.new_page()
    page.goto("http://127.0.0.1:18700/index.html")
    frame = None
    for _ in range(40):
        frame = next((f for f in page.frames if f.url.startswith(PLAYER)), None)
        if frame and frame.evaluate("!!document.querySelector('tondar-panel') && "
                                    "getComputedStyle(document.querySelector('tondar-panel')).display==='block'"):
            break
        time.sleep(0.5)
    time.sleep(2)
    box = frame.evaluate("(() => {const h=document.querySelector('tondar-panel').getBoundingClientRect();"
                         "return [h.left, h.top]})()")
    fe = page.query_selector("iframe").bounding_box()
    x, y = fe["x"] + box[0] + 60, fe["y"] + box[1] + 15
    page.mouse.click(x, y)
    time.sleep(12)
    page.screenshot(path="/home/claude/shots/12_protected.png")
    print("panel at", x, y)
    page.mouse.click(x, y + 80)      # first quality row (below header + title)
    time.sleep(1)
    page.screenshot(path="/home/claude/shots/12b_after_click.png")
    time.sleep(15)
    ctx.close()

app.terminate()
app.wait(10)
state = json.load(open(home + "/.local/share/tondar/downloads.json"))
for d in state["downloads"]:
    path = os.path.join(d["save_dir"], d["filename"])
    print("BROWSER:", d["filename"], "|", d["status"], "| referer:", d["referer"], "| headers:", d["headers"],
          "| duration:", duration(path) if os.path.exists(path) else None, "| err:", d["error"][:150])
print("rejected requests (expected only from probes without headers):", len(rejected), rejected[:3])

# ---- part 2: import list with referer typed in the dialog
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/.config", XDG_DATA_HOME=home + "/.local/share",
                  QT_QPA_PLATFORM="offscreen")
from tondar.qt import QtCore, QtWidgets  # noqa: E402
from tondar.config import Settings  # noqa: E402
from tondar.manager import DownloadManager  # noqa: E402
from tondar.server import Bridge  # noqa: E402
from tondar.ui.main_window import MainWindow  # noqa: E402
from tondar.ui import dialogs, theme  # noqa: E402
from tondar import listio  # noqa: E402

lst = os.path.join(home, "videos.txt")
open(lst, "w").write("#example :\n01-What_is_DevOps.mp4|http://127.0.0.1:18702/index-f4-v1-a1.m3u8\n"
                     "02-Master.mp4|http://127.0.0.1:18702/master.m3u8\n")
qapp = QtWidgets.QApplication([])
theme.apply(qapp, "light")
s = Settings()
m = DownloadManager(s)
win = MainWindow(m, s, Bridge(), {}, "/x")
links = listio.import_file(lst)
dlg = dialogs.LinksDialog(s, links, win, "Import")
dlg.show()
steps = {"n": 0}


def tick():
    steps["n"] += 1
    n = steps["n"]
    if n == 8:
        print("before referer:", [(l["_item"].text(0), l["_item"].text(2)) for l in dlg.links])
        dlg.referer.setText(PLAYER + "/")
        dlg._recheck()
    if n == 20:
        print("after referer: ", [(l["_item"].text(0), l["_item"].text(1), l["_item"].text(2)) for l in dlg.links])
        dlg.grab().save("/home/claude/shots/13_import_referer.png")
        dlg.accept()
        added = []
        # replicate MainWindow.on_browser_links tail with this dialog
        for l in dlg.selected_links():
            h = dlg._headers_for(l)
            best = l.get("_stream") or {}
            it = m.new_item(l["url"], l["filename"], None, "Video", kind="media", media_format=best.get("id") or "bv*+ba/b",
                            page_url=l["url"], referer=h.get("Referer", ""), headers={"Origin": h["Origin"]})
            m.add(it, start=True)
            added.append(it.id)
        steps["ids"] = added
    if n > 20 and all(m.items[i].status in ("Complete", "Error") for i in steps["ids"]):
        for i in steps["ids"]:
            it = m.items[i]
            print("IMPORT:", it.filename, it.status, "| duration:", duration(it.path) if it.status == "Complete" else None,
                  "|", it.error[:150])
        qapp.quit()
    if n > 200:
        qapp.quit()


t = QtCore.QTimer()
t.timeout.connect(tick)
t.start(500)
qapp.exec()
