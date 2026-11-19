"""Real Chrome + extension: RTL page with an HLS stream (master + variants) and a direct MP4.

Checks that the panel resolves stream qualities with sizes, lists the direct file,
renders left-to-right on an RTL page, and that a click lands in the app with the page title.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.range_server import serve  # noqa: E402

site = tempfile.mkdtemp()
ff = ["ffmpeg", "-loglevel", "error", "-y"]
src = os.path.join(site, "src.mp4")
subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=duration=8:size=1280x720:rate=25", "-f", "lavfi",
                     "-i", "sine=duration=8", "-shortest", "-c:v", "libx264", "-b:v", "1500k", "-c:a", "aac", src],
               check=True)
for name, h, br in (("720", 720, "1500k"), ("360", 360, "500k")):
    d = os.path.join(site, "hls", name)
    os.makedirs(d)
    subprocess.run(ff + ["-i", src, "-vf", f"scale=-2:{h}", "-c:v", "libx264", "-b:v", br, "-c:a", "aac",
                         "-hls_time", "2", "-hls_playlist_type", "vod", os.path.join(d, "chunk.m3u8")], check=True)
with open(os.path.join(site, "hls", "master.m3u8"), "w") as f:
    f.write("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1700000,RESOLUTION=1280x720\n720/chunk.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=650000,RESOLUTION=640x360\n360/chunk.m3u8\n")
subprocess.run(["cp", src, os.path.join(site, "lesson-720p.mp4")], check=True)
with open(os.path.join(site, "index.html"), "w") as f:
    f.write("""<!doctype html><html dir="rtl" lang="fa"><head><meta charset="utf-8">
<title>آموزش ریاضی هشتم - فصل دوم</title></head>
<body style="margin:0;font-family:sans-serif">
<h2 style="padding:8px 16px">صفحه‌ی ویدیو</h2>
<video id="v" width="900" height="506" controls muted style="margin:0 16px;background:#000"></video>
<script>
  // what a typical player does: fetch the HLS playlists with XHR, play an MP4 preview
  fetch('hls/master.m3u8').then(r => r.text());
  fetch('hls/720/chunk.m3u8').then(r => r.text());
  fetch('hls/360/chunk.m3u8').then(r => r.text());
  document.getElementById('v').src = 'lesson-720p.mp4';
</script></body></html>""")


class H:
    pass


# serve .m3u8 with the right type
import tests.range_server as rs  # noqa: E402
_orig = rs.make_handler


def handler(root, ranges=True, throttle=0):
    base = _orig(root, ranges, throttle)

    class X(base):
        def send_header(self, k, v):
            if k == "Content-Type" and self.path.split("?")[0].endswith(".m3u8"):
                v = "application/vnd.apple.mpegurl"
            if k == "Content-Disposition" and not self.path.split("?")[0].endswith(".zip"):
                return
            super().send_header(k, v)
    return X


rs.make_handler = handler
rs.serve(site, 18500)

home = tempfile.mkdtemp()
env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home + "/.config", XDG_DATA_HOME=home + "/.local/share",
           QT_QPA_PLATFORM="offscreen", PYTHONPATH=ROOT)
os.makedirs(home + "/.config/tondar")
json.dump({"show_file_info_dialog": False, "show_progress_dialog": False, "show_complete_dialog": False,
           "download_dir": home + "/dl"}, open(home + "/.config/tondar/settings.json", "w"))
os.makedirs(home + "/.local/share/tondar/bin")
# use the pip-installed yt-dlp instead of downloading one
open(home + "/.local/share/tondar/bin/yt-dlp", "w").write(
    "import sys, runpy\nsys.argv[0]='yt-dlp'\nrunpy.run_module('yt_dlp', run_name='__main__')\n")
app = subprocess.Popen([sys.executable, "-m", "tondar"], env=env, cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(2.5)

base = "http://127.0.0.1:18500/"
rq = urllib.request.Request("http://127.0.0.1:9614/media/resolve", method="POST",
                            headers={"X-Tondar-Client": "1", "Content-Type": "application/json"},
                            data=json.dumps({"page": base + "index.html", "title": "Lesson",
                                             "streams": [base + "hls/720/chunk.m3u8", base + "hls/master.m3u8",
                                                         base + "hls/360/chunk.m3u8"],
                                             "files": [base + "lesson-720p.mp4"]}).encode())
res = json.loads(urllib.request.urlopen(rq, timeout=180).read())
print("API resolve:", json.dumps(res, ensure_ascii=False)[:900])

from playwright.sync_api import sync_playwright  # noqa: E402
ext = os.path.join(ROOT, "extension", "build", "chrome")
out = "/home/claude/shots"
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        tempfile.mkdtemp(), executable_path="/usr/bin/google-chrome", headless=False,
        args=["--headless=new", f"--disable-extensions-except={ext}", f"--load-extension={ext}"],
        viewport={"width": 1100, "height": 640})
    time.sleep(1.5)
    page = ctx.new_page()
    page.goto(base + "index.html")
    page.wait_for_function("document.querySelector('tondar-panel') && "
                           "getComputedStyle(document.querySelector('tondar-panel')).display==='block'", timeout=15000)
    time.sleep(2)
    box = page.evaluate("(() => {const h=document.querySelector('tondar-panel').getBoundingClientRect();"
                        "return [h.left, h.top, h.width]})()")
    page.mouse.click(box[0] + 60, box[1] + 15)
    time.sleep(15)
    page.screenshot(path=f"{out}/11_rtl_panel.png")
    # click the first quality row (rows are ~30px apart under the header + title)
    page.mouse.click(box[0] + 60, box[1] + 34 + 60)
    time.sleep(12)
    ctx.close()

app.terminate()
app.wait(10)
state = json.load(open(home + "/.local/share/tondar/downloads.json"))
for d in state["downloads"]:
    print("app got:", d["filename"], "|", d["status"], "|", d["size"], "|", d["url"], "| referer:", d["referer"],
          "|", d["error"])
