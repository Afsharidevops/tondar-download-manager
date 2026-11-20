"""Telegram support with a fake tdl (no network): parsing, login state, listing, downloads, dialog."""
import os, shutil, subprocess, sys, tempfile, time
os.environ["TONDAR_HOME"] = tempfile.mkdtemp(prefix="tondar-tg-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tondar import telegram as tg
from tondar.config import Settings

P = tg.parse_chat
assert P("@fillmayesh") == ("fillmayesh", None)
assert P("https://t.me/fillmayesh") == ("fillmayesh", None)
assert P("t.me/s/fillmayesh") == ("fillmayesh", None)
assert P("https://t.me/fillmayesh/123") == ("fillmayesh", 123)
assert P("https://t.me/c/1234567890/45") == ("1234567890", 45)
assert P("https://t.me/fillmayesh/123?single") == ("fillmayesh", 123)
assert P("") == ("me", None) and P("Saved Messages") == ("me", None)
assert tg.message_link("me", 777, 5) == "tdl://saved/5"
for bad in ("https://t.me/+AbCdEf", "hello world"):
    try:
        P(bad); raise SystemExit(f"accepted {bad!r}")
    except ValueError:
        pass
assert tg.message_link("1234567890", 1234567890, 5) == "https://t.me/c/1234567890/5"
assert tg.message_link("-1001234567890", None, 5) == "https://t.me/c/1234567890/5"
n = tg.suggest_name("5771234.mp4", '🔥سریال " شمشیر و سکوت "\n\n💥«Sword & Silence (2026).S01»\n🎬قسمت 2\n📥کیفیت : 720p\n@fillmayesh', "video/mp4", 11)
assert n == "سریال شمشیر و سکوت - Sword & Silence (2026).S01 - قسمت 2 (11).mp4", n
assert tg.suggest_name("Sword.S01E02.mp4", "x", "video/mp4", 1) == "Sword.S01E02.mp4"
assert tg.suggest_name("", "", "video/mp4", 7) == "telegram 7.mp4"
print("parsing ok")

shutil.copy(os.path.join(os.path.dirname(__file__), "fake_tdl.py"), tg.TDL_PATH) if tg.TDL_PATH.parent.mkdir(parents=True, exist_ok=True) is None else None
os.chmod(tg.TDL_PATH, 0o755)
s = Settings()
assert tg.tdl_version() == "0.20.4"
assert tg.check_login(s) is False                       # no session at all
cmd = tg.login_command(s, "qr")
assert cmd[-3:] == ["login", "-T", "qr"] and "--storage" in cmd
subprocess.run(cmd, check=True, capture_output=True)
assert tg.has_session() and tg.check_login(s) is True
s["telegram_proxy"] = "socks5://127.0.0.1:1080"
assert "--proxy" in tg.base_args(s)
s["telegram_proxy"] = ""
print("login ok")

chat, entries = tg.list_files(s, "https://t.me/fillmayesh", 50)
assert chat == "fillmayesh" and len(entries) == 4, entries
e = {x["id"]: x for x in entries}
assert e[11]["size"] == 300000 and e[11]["kind"] == "video" and e[11]["duration"] == 4155 and e[11]["h"] == 720
assert e[11]["link"] == "https://t.me/fillmayesh/11" and e[11]["name"].endswith("(11).mp4")
assert e[13]["kind"] == "image" and e[13]["size"] == 54321
assert e[14]["kind"] == "audio"
chat, saved = tg.list_files(s, "", 50)
assert chat == "me" and saved[0]["link"] == "tdl://saved/11" and saved[0]["chat_id"] == 777
chat, one = tg.list_files(s, "https://t.me/fillmayesh/12", 50)
assert [x["id"] for x in one] == [12]
print("listing ok:", [(x["name"], x["size"], x["kind"]) for x in entries])

from tondar.qt import QtWidgets, QtCore
app = QtWidgets.QApplication([])
from tondar.manager import DownloadManager, MAIN_QUEUE
from tondar.models import KIND_TELEGRAM, COMPLETED, ERROR
m = DownloadManager(s)
out = tempfile.mkdtemp()
items = []
for x, h in ((e[11], {}), (dict(saved[1], name="from saved.mp4"), {"tg_chat": "777", "tg_msg": "12"}),
             (dict(e[12], link="https://t.me/fillmayesh/99", name="missing.mp4"), {})):
    it = m.new_item(x["link"], x["name"], out, "Video", kind=KIND_TELEGRAM, size=x["size"], headers=h)
    m.add(it, start=False, queue=MAIN_QUEUE); items.append(it)
seen_progress = []
m.start_queue()
t0 = time.time()
while time.time() - t0 < 60 and any(i.status not in (COMPLETED, ERROR) for i in items):
    app.processEvents(); time.sleep(0.05)
    for i in items:
        eng = m.engines.get(i.id)
        if eng and 0 < eng.downloaded() < i.size:
            seen_progress.append(i.id)
for i in items:
    print(" ", i.filename, i.status, i.error)
assert items[0].status == COMPLETED and os.path.getsize(os.path.join(out, items[0].filename)) == 300000
assert items[1].status == COMPLETED
assert items[2].status == ERROR and "message not found" in items[2].error
assert set(seen_progress) >= {items[0].id, items[1].id}, "no progress seen"
assert not [f for f in os.listdir(out) if f.endswith(".tmp")]
print("downloads ok (one at a time, progress seen, error reported)")

# stop in the middle -> paused, temp file removed
it = m.new_item(e[11]["link"], "stopme.mp4", out, "Video", kind=KIND_TELEGRAM, size=300000)
m.add(it, start=True)
t0 = time.time()
while time.time() - t0 < 10 and not (m.engines.get(it.id) and m.engines[it.id].downloaded() > 0):
    app.processEvents(); time.sleep(0.05)
m.stop(it.id)
t0 = time.time()
while time.time() - t0 < 10 and it.id in m.engines:
    app.processEvents(); time.sleep(0.05)
assert it.status == "Paused" or it.status.lower().startswith("paus"), it.status
assert not os.path.exists(os.path.join(out, "stopme.mp4.tmp"))
print("stop ok")

from tondar.ui.telegram_dialog import TelegramDialog
d = TelegramDialog(m, s, None)
d.show()
t0 = time.time()
while time.time() - t0 < 10 and (d.busy or d.logged_in is None):
    app.processEvents(); time.sleep(0.05)
assert d.logged_in is True
d.chat.setText("@fillmayesh"); d.list_files()
t0 = time.time()
while time.time() - t0 < 10 and d.busy:
    app.processEvents(); time.sleep(0.05)
app.processEvents()
assert d.tree.topLevelItemCount() == 2, d.tree.topLevelItemCount()     # videos only
d.kind.setCurrentIndex(2); app.processEvents()
assert d.tree.topLevelItemCount() == 4
d.kind.setCurrentIndex(0); app.processEvents()
shot = os.environ.get("TG_SHOT", "/tmp/telegram-dialog.png")
d.grab().save(shot)
n0 = len(m.items)
d.start_now.setChecked(False)
d.add()
assert len(m.items) == n0 + 2 and all(i.kind == KIND_TELEGRAM for i in list(m.items.values())[-2:])
assert all(os.path.basename(i.save_dir) == "fillmayesh" for i in list(m.items.values())[-2:])
print("dialog ok ->", shot)

tg.logout()
assert not tg.has_session() and tg.check_login(s) is False
d2 = TelegramDialog(m, s, None); d2.show(); app.processEvents()
d2.grab().save("/tmp/telegram-dialog-loggedout.png")
os.remove(tg.TDL_PATH)
d3 = TelegramDialog(m, s, None); d3.show(); app.processEvents()
d3.grab().save("/tmp/telegram-dialog-notinstalled.png")
print("ALL TELEGRAM TESTS PASSED")
