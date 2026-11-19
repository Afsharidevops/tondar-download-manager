"""End-to-end: real Chrome + extension + running Tondar app (offscreen)."""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.range_server import serve  # noqa: E402

site = tempfile.mkdtemp()
subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=6:size=1280x720:rate=30",
                "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-c:v", "libx264", "-b:v", "2M",
                "-c:a", "aac", os.path.join(site, "clip.mp4")], check=True)
with open(os.path.join(site, "tools.zip"), "wb") as f:
    f.write(os.urandom(3 * 1024 * 1024))
with open(os.path.join(site, "index.html"), "w") as f:
    f.write("""<!doctype html><html><head><title>Test video page</title></head>
<body style="margin:0;background:#111;color:#eee;font-family:sans-serif">
<h2 style="padding:8px 16px">My video page</h2>
<video id="v" src="clip.mp4" width="960" height="540" controls muted autoplay style="margin-left:16px"></video>
<p style="padding:8px 16px"><a id="zip" href="tools.zip">Download tools.zip</a></p>
</body></html>""")
serve(site, 18200)

home = tempfile.mkdtemp()
env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home + "/.config", XDG_DATA_HOME=home + "/.local/share",
           QT_QPA_PLATFORM="offscreen", PYTHONPATH=ROOT)
os.makedirs(home + "/.config/tondar")
json.dump({"show_file_info_dialog": False, "show_progress_dialog": False, "show_complete_dialog": False,
           "download_dir": home + "/dl"}, open(home + "/.config/tondar/settings.json", "w"))
app = subprocess.Popen([sys.executable, "-m", "tondar"], env=env, cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(2.5)

from playwright.sync_api import sync_playwright  # noqa: E402

ext = os.path.join(ROOT, "extension", "build", "chrome")
out = "/home/claude/shots"
results = {}
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        tempfile.mkdtemp(), executable_path="/usr/bin/google-chrome", headless=False,
        args=["--headless=new", f"--disable-extensions-except={ext}", f"--load-extension={ext}",
              "--autoplay-policy=no-user-gesture-required"],
        viewport={"width": 1100, "height": 720}, accept_downloads=True)
    time.sleep(1.5)
    page = ctx.new_page()
    page.goto("http://127.0.0.1:18200/index.html")
    page.wait_for_function("document.querySelector('tondar-panel') && "
                           "getComputedStyle(document.querySelector('tondar-panel')).display==='block'",
                           timeout=15000)
    results["panel_shown"] = True
    time.sleep(1)
    page.screenshot(path=f"{out}/8_browser_panel.png")
    # open the quality menu (closed shadow root -> click by coordinates)
    box = page.evaluate("(() => {const h=document.querySelector('tondar-panel').getBoundingClientRect();"
                        "return [h.left, h.top]})()")
    page.mouse.click(box[0] + 60, box[1] + 15)
    time.sleep(8)       # yt-dlp reads the page
    page.screenshot(path=f"{out}/9_browser_menu.png")
    # capture a file download
    import urllib.request
    rq = urllib.request.Request("http://127.0.0.1:9614/ping", headers={"X-Tondar-Client": "1"})
    print("ping:", urllib.request.urlopen(rq, timeout=3).read()[:80])
    sw = ctx.service_workers[0] if ctx.service_workers else None
    print("service worker:", sw.url if sw else None)
    sw.evaluate("globalThis.__log=[]; const of=globalThis.fetch; globalThis.fetch=(u,o)=>{__log.push(String(u)); return of(u,o).then(r=>{__log.push('status '+r.status);return r}, e=>{__log.push('err '+e);throw e})}; chrome.downloads.onCreated.addListener(d=>__log.push('created '+d.url))")
    page.click("#zip")
    time.sleep(2)
    print("swlog:", sw.evaluate("JSON.stringify(__log)"))
    time.sleep(2)
    if sw:
        print("sw eval:", sw.evaluate("appInfo ? 'alive' : 'none'"))
        print("downloads:", sw.evaluate("chrome.downloads.search({}).then(r=>JSON.stringify(r.map(d=>[d.url,d.filename,d.state,d.error])))"))
    ctx.close()

app.terminate()
try:
    log = app.communicate(timeout=10)[0].decode(errors="replace")
except Exception:
    log = ""
print("APP LOG:", log[-2000:])
state = json.load(open(home + "/.local/share/tondar/downloads.json"))
for d in state["downloads"]:
    print("app got:", d["filename"], d["status"], d["size"], d["url"])
results["zip_captured"] = any(d["url"].endswith("tools.zip") and d["status"] == "Complete" for d in state["downloads"])
print(results)
print(log[-1500:])
