"""Render the main windows offscreen and save screenshots; also drives a real download."""
import os
import sys
import tempfile

home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.environ["XDG_CONFIG_HOME"] = home + "/.config"
os.environ["XDG_DATA_HOME"] = home + "/.local/share"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.range_server import serve  # noqa: E402
root = tempfile.mkdtemp()
for name, size in (("ubuntu-24.04-desktop.iso", 40), ("Album - Track 01.mp3", 6), ("report.pdf", 3),
                   ("Movie.2026.1080p.mkv", 9), ("Movie.2026.720p.mkv", 5), ("setup.deb", 2)):
    with open(os.path.join(root, name), "wb") as f:
        f.write(os.urandom(size * 1024 * 1024))
serve(root, 18090, throttle=900_000)

from tondar.qt import QtCore, QtWidgets, QtGui  # noqa: E402
from tondar.config import Settings  # noqa: E402
from tondar.manager import DownloadManager  # noqa: E402
from tondar.server import Bridge  # noqa: E402
from tondar.ui.main_window import MainWindow  # noqa: E402
from tondar.ui.dialogs import FileInfoDialog, ProgressDialog, OptionsDialog, CompleteDialog, SchedulerDialog  # noqa: E402
from tondar.models import COMPLETED  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/shots"
os.makedirs(out, exist_ok=True)
app = QtWidgets.QApplication(sys.argv)
s = Settings()
from tondar.ui import theme  # noqa: E402
theme.apply(app, os.environ.get("THEME", "light"))
m = DownloadManager(s)
win = MainWindow(m, s, Bridge(), {}, "/usr/share/tondar/extension")
win.show()

base = "http://127.0.0.1:18090/"
ids = []
for n in ("ubuntu-24.04-desktop.iso", "Album - Track 01.mp3", "report.pdf"):
    it = m.new_item(base + n, n)
    m.add(it, start=True)
    ids.append(it.id)
fake = m.new_item("https://example.com/video/Big.Buck.Bunny.1080p.mkv", "Big.Buck.Bunny.1080p.mkv", size=734003200,
                  downloaded=301989888, description="")
m.add(fake, start=False)
fake.status = "Paused"
fake.downloaded = 301989888
q = m.new_item("https://example.com/files/LibreOffice_25.2_Linux_x86-64_deb.tar.gz",
               "LibreOffice_25.2_Linux_x86-64_deb.tar.gz", size=262144000)
m.add(q, start=False, queue="Main queue")

state = {"step": 0}
prog = {}


def shot(w, name):
    w.grab().save(os.path.join(out, name))
    print("saved", name)


def step():
    state["step"] += 1
    st = state["step"]
    if st == 1:
        prog["d"] = ProgressDialog(m, s, ids[0])
        prog["d"].show()
    elif st == 3:
        shot(win, "1_main_window.png")
        shot(prog["d"], "2_progress.png")
        fi = FileInfoDialog(m, s, {"url": base + "report.pdf"}, win)
        fi.show()
        prog["fi"] = fi
    elif st == 5:
        shot(prog["fi"], "3_file_info.png")
        prog["fi"].close()
        o = OptionsDialog(s, win, "/usr/share/tondar/extension")
        o.show()
        shot(o, "4_options.png")
        o.close()
        sc = SchedulerDialog(m, s, win)
        sc.show()
        shot(sc, "5_scheduler.png")
        sc.close()
    elif st >= 6 and "links_at" not in state:
        done = [m.items[i].status for i in ids]
        if all(x == COMPLETED for x in done) or st > 80:
            print("statuses:", done)
            it = m.items[ids[2]]
            c = CompleteDialog(s, it)
            c.show()
            shot(c, "6_complete.png")
            shot(win, "7_main_after.png")
            import hashlib
            for i in ids:
                it = m.items[i]
                a = hashlib.md5(open(it.path, "rb").read()).hexdigest()
                b = hashlib.md5(open(os.path.join(root, it.filename), "rb").read()).hexdigest()
                print(it.filename, "OK" if a == b else "MISMATCH")
            from tondar import listio
            for fmt in ("txt", "ef2", "json"):
                pth = os.path.join(home, "list." + fmt)
                listio.export_items(list(m.items.values()), pth)
                back = listio.import_file(pth)
                print("export/import", fmt, len(back), "links", back[0])
            open(os.path.join(root, "index.html"), "w").write("<html>hi</html>")
            links = [{"url": base + n} for n in ("Movie.2026.1080p.mkv", "Movie.2026.720p.mkv", "setup.deb",
                                                   "index.html", "missing.zip")]
            links += [{"url": base + "index.html#about"}]
            from tondar.ui.dialogs import LinksDialog
            ld = LinksDialog(s, links, win)
            ld.show()
            prog["ld"] = ld
            state["links_at"] = st
    elif "links_at" in state and st >= state["links_at"] + 4:
        ld = prog["ld"]
        shot(ld, "10_links.png")
        print("links status:", ld.status.text())
        print("checked:", [l.get("filename", l["url"]) for l in ld.selected_links()])
        ld.reject()
        app.quit()


t = QtCore.QTimer()
t.timeout.connect(step)
t.start(700)
app.exec()
