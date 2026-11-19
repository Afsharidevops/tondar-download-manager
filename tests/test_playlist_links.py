"""Download-all-links on YouTube pages (yt-dlp mocked: YouTube is not reachable from CI)."""
import os
import sys
import tempfile
import time

home = tempfile.mkdtemp()
os.environ.update(HOME=home, XDG_CONFIG_HOME=home + "/c", XDG_DATA_HOME=home + "/d", QT_QPA_PLATFORM="offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tondar import media  # noqa: E402

VIDS = {f"vid{n:08d}": (f"Song number {n}", 180 + n) for n in range(1, 8)}
PLAYLISTS = {"PLaaa": ("Donya Music Videos", ["vid00000001", "vid00000002", "vid00000003"]),
             "PLbbb": ("Sasy Music Videos", ["vid00000004", "vid00000005"])}
calls = []


def fake_flat(url, settings, cookie_jar=None, limit=500, timeout=180):
    calls.append(("flat", url))
    time.sleep(0.2)
    if "/playlists" in url:
        return media.flat_entries({"_type": "playlist", "title": "Radio Javan - Playlists", "entries": [
            {"_type": "url", "ie_key": "YoutubeTab", "url": f"https://www.youtube.com/playlist?list={k}", "title": v[0]}
            for k, v in PLAYLISTS.items()]})
    lst = media.yt_list_id(url)
    if lst.startswith("RD"):
        ids, title = ["vid00000001", "vid00000006", "vid00000007"], "My Mix"
    else:
        title, ids = PLAYLISTS[lst]
    return media.flat_entries({"_type": "playlist", "title": title, "entries": [
        {"_type": "url", "ie_key": "Youtube", "id": i, "url": f"https://www.youtube.com/watch?v={i}",
         "title": VIDS[i][0], "duration": VIDS[i][1]} for i in ids]})


def fake_probe(url, settings, **kw):
    calls.append(("probe", url))
    time.sleep(0.2)
    return {"title": "x", "duration": 200, "options": [
        {"id": "137+140", "label": "MP4 1080p", "ext": "mp4", "size": 50_000_000, "approx": False, "type": "video", "height": 1080},
        {"id": "136+140", "label": "MP4 720p", "ext": "mp4", "size": 25_000_000, "approx": False, "type": "video", "height": 720},
        {"id": "140", "label": "M4A audio", "ext": "m4a", "size": 3_000_000, "approx": False, "type": "audio"},
        {"id": "bestaudio/best", "label": "MP3", "ext": "mp3", "size": 6_000_000, "approx": True, "type": "mp3"}]}


media.flat_playlist = fake_flat
media.probe_media = fake_probe

from tondar.qt import QtCore, QtWidgets  # noqa: E402
from tondar.config import Settings  # noqa: E402
from tondar.manager import DownloadManager  # noqa: E402
from tondar.server import Bridge  # noqa: E402
from tondar.ui import theme, main_window, dialogs  # noqa: E402

app = QtWidgets.QApplication([])
theme.apply(app, "light")
s = Settings()
m = DownloadManager(s)
win = main_window.MainWindow(m, s, Bridge(), {}, "/x")
shots = iter(["14_mix_links.png", "15_channel_playlists.png"])


def fake_exec(dlg, *a):
    if not isinstance(dlg, dialogs.LinksDialog):
        return 0
    dlg.show()
    t0 = time.time()
    while time.time() - t0 < 6:
        app.processEvents()
        time.sleep(0.05)
    if dlg.links and any(l.get("yt") == "playlist" for l in dlg.links):       # channel page: tick one playlist
        for l in dlg.links:
            if l.get("yt") == "playlist" and "Donya" in (l.get("title") or ""):
                l["_item"].setCheckState(0, QtCore.Qt.CheckState.Checked)
    else:
        dlg.quality.setCurrentIndex(2)        # 720p
        app.processEvents()
    dlg.grab().save("/home/claude/shots/" + next(shots))
    rows = [(l["_item"].text(0), l["_item"].text(1), l["_item"].text(2), l["_item"].checkState(0) ==
             QtCore.Qt.CheckState.Checked, l["_item"].isHidden()) for l in dlg.links]
    for r in rows:
        if not r[4]:
            print("   ROW", r[:4])
    print("   status:", dlg.status.text())
    dlg.closed = True
    return QtWidgets.QDialog.DialogCode.Accepted


main_window.exec_ = fake_exec
s["start_queue_now"] = False

print("== watch page with a Mix")
page = "https://www.youtube.com/watch?v=vid00000001&list=RDMMvid00000001&start_radio=1"
links = [{"url": page, "referer": page, "page": True},
         {"url": "https://www.youtube.com/watch?v=vid00000001&list=RDMMvid00000001&index=1", "text": "  Song number 1  3:01"},
         {"url": "https://www.youtube.com/watch?v=vid00000006&list=RDMMvid00000001&index=2", "text": "Song number 6"},
         {"url": "https://www.youtube.com/watch?v=vid00000004", "text": "A recommended video"},
         {"url": "https://www.googleadservices.com/pagead/aclk?sa=L&ai=xyz"},
         {"url": "https://www.youtube.com/feed/history"},
         {"url": "https://www.youtube.com/@radiojavan"},
         {"url": "https://developers.google.com/youtube"}]
win.on_browser_links(links)
for it in m.items.values():
    print("   QUEUED", os.path.relpath(it.path, home), "|", it.media_format.split("/")[0], "|", it.url)
n1 = len(m.items)

print("== channel Playlists tab (context menu on the page)")
win.on_browser_media({"url": "https://www.youtube.com/@radiojavan/playlists"})
for it in list(m.items.values())[n1:]:
    print("   QUEUED", os.path.relpath(it.path, home), "|", it.media_format.split("/")[0])
print("yt-dlp calls:", len(calls), sorted({c[0] for c in calls}))
m.stop_queue()
