"""Download list, queues, scheduler and persistence."""
import datetime
import json
import os
import subprocess
import threading
import time

from .qt import QtCore, Signal
from .config import STATE_FILE, DATA_DIR
from .engine import HttpDownloader, SpeedLimiter, probe, unique_path, PART_SUFFIX
from .media import MediaDownloader, probe_media
from .models import (DownloadItem, QUEUED, WAITING, DOWNLOADING, PAUSED, COMPLETED, ERROR,
                     CONNECTING, KIND_MEDIA)

MAIN_QUEUE = "Main queue"
SYNC_QUEUE = "Synchronization queue"


class DownloadManager(QtCore.QObject):
    item_added = Signal(str)
    item_updated = Signal(str)
    item_removed = Signal(str)
    item_finished = Signal(str, str)        # id, status
    queue_state_changed = Signal(bool)
    probe_finished = Signal(object, object, object)      # token, info, error
    _engine_done = Signal(object, str, object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.items = {}            # id -> DownloadItem (insertion ordered)
        self.engines = {}          # id -> downloader
        self.queue_running = False
        self.queue_started_by_scheduler = False
        self.limiter = SpeedLimiter(self.settings.speed_limit_bytes)
        self._last = {}            # id -> (time, bytes) for speed calc
        self._dirty = False
        self._engine_done.connect(self._on_engine_done)
        self.load()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        self.sched_timer = QtCore.QTimer(self)
        self.sched_timer.timeout.connect(self._check_scheduler)
        self.sched_timer.start(20_000)
        self._sched_fired = set()

    # ------------------------------------------------------------------ io
    def load(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("downloads", []):
                it = DownloadItem.from_dict(d)
                self.items[it.id] = it
        except FileNotFoundError:
            pass
        except Exception as e:
            print("state load error:", e)

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for it_id, eng in list(self.engines.items()):
            it = self.items.get(it_id)
            if it and isinstance(eng, HttpDownloader):
                eng._persist()
        tmp = str(STATE_FILE) + ".tmp"
        # the list can hold login cookies of unfinished downloads: keep it private
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
            json.dump({"downloads": [i.to_dict() for i in self.items.values()]}, f,
                      ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE_FILE)
        self._dirty = False

    def mark_dirty(self):
        self._dirty = True

    # ------------------------------------------------------------ probing
    def probe_async(self, token, url, headers=None, media=False):
        def work():
            try:
                if media:
                    h = headers or {}
                    info = probe_media(url, self.settings, referer=h.get("Referer", ""),
                                       cookies=h.get("Cookie", ""),
                                       headers={k: v for k, v in h.items() if k == "Origin"})
                else:
                    info = probe(url, headers, self.settings["proxy"],
                                 self.settings["use_system_proxy"], self.settings["timeout"])
                self.probe_finished.emit(token, info, None)
            except Exception as e:  # noqa: BLE001
                self.probe_finished.emit(token, None, str(e))
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- adding
    def new_item(self, url, filename, save_dir=None, category=None, **kw):
        category = category or self.settings.category_for(filename)
        save_dir = save_dir or str(self.settings.dir_for_category(category))
        path = unique_path(os.path.join(save_dir, filename))
        it = DownloadItem(url=url, filename=os.path.basename(path), save_dir=save_dir,
                          category=category, **kw)
        return it

    def add(self, item, start=True, queue=None):
        self.items[item.id] = item
        if queue:
            item.queue = queue
            item.status = QUEUED
        else:
            item.status = WAITING if not start else PAUSED
        self.item_added.emit(item.id)
        if start:
            self.start(item.id)
        self.mark_dirty()
        return item

    def find_duplicate(self, url):
        for it in self.items.values():
            if it.url == url or it.page_url == url and it.kind == KIND_MEDIA:
                return it
        return None

    # --------------------------------------------------------- control
    def start(self, item_id):
        it = self.items.get(item_id)
        if not it or item_id in self.engines or it.status == COMPLETED:
            return
        cls = MediaDownloader if it.kind == KIND_MEDIA else HttpDownloader
        eng = cls(it, self.settings, self.limiter, self._done_from_thread)
        self.engines[item_id] = eng
        it.status = CONNECTING
        it.error = ""
        it.last_try = time.time()
        self._last[item_id] = (time.monotonic(), it.downloaded)
        eng.start()
        self.item_updated.emit(item_id)

    def stop(self, item_id):
        eng = self.engines.get(item_id)
        if eng:
            eng.stop()
        else:
            it = self.items.get(item_id)
            if it and it.status in (QUEUED,):
                it.status = PAUSED
                self.item_updated.emit(item_id)

    def stop_all(self):
        self.stop_queue()
        for i in list(self.engines):
            self.stop(i)

    def redownload(self, item_id):
        it = self.items.get(item_id)
        if not it or item_id in self.engines:
            return
        try:
            os.remove(it.path + PART_SUFFIX)
        except OSError:
            pass
        it.segments, it.downloaded, it.status = [], 0, PAUSED
        self.start(item_id)

    def remove(self, item_id, delete_file=False):
        eng = self.engines.pop(item_id, None)
        if eng:
            eng.stop()
        it = self.items.pop(item_id, None)
        if it:
            if delete_file:
                for p in (it.path, it.path + PART_SUFFIX):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            else:
                try:
                    if it.status != COMPLETED:
                        os.remove(it.path + PART_SUFFIX)
                except OSError:
                    pass
        self.item_removed.emit(item_id)
        self.mark_dirty()

    def remove_completed(self):
        for i, it in list(self.items.items()):
            if it.status == COMPLETED:
                self.remove(i)

    # ----------------------------------------------------------- queue
    def add_to_queue(self, item_id, queue=MAIN_QUEUE):
        it = self.items.get(item_id)
        if it and it.status not in (COMPLETED,) and item_id not in self.engines:
            it.queue = queue
            it.status = QUEUED
            self.item_updated.emit(item_id)
            self.mark_dirty()

    def start_queue(self, by_scheduler=False):
        self.queue_running = True
        self.queue_started_by_scheduler = by_scheduler
        self.queue_state_changed.emit(True)
        self._process_queue()

    def stop_queue(self):
        if not self.queue_running:
            return
        self.queue_running = False
        for i, eng in list(self.engines.items()):
            if getattr(eng, "from_queue", False):
                eng.requeue = True
                eng.stop()
        self.queue_state_changed.emit(False)

    def queued_items(self):
        return [it for it in self.items.values() if it.status == QUEUED]

    def _process_queue(self):
        if not self.queue_running:
            return
        running = sum(1 for e in self.engines.values() if getattr(e, "from_queue", False))
        for it in self.queued_items():
            if running >= max(1, self.settings["max_simultaneous"]):
                break
            self.start(it.id)
            eng = self.engines.get(it.id)
            if eng:
                eng.from_queue = True
                running += 1
        if running == 0 and not self.queued_items():
            self.queue_running = False
            self.queue_state_changed.emit(False)
            if self.queue_started_by_scheduler:
                self._on_queue_finished()

    def _on_queue_finished(self):
        action = self.settings["scheduler"].get("on_finish", "nothing")
        if action == "quit":
            QtCore.QCoreApplication.quit()
        elif action == "shutdown":
            subprocess.Popen(["systemctl", "poweroff"])
        elif action == "suspend":
            subprocess.Popen(["systemctl", "suspend"])

    # ------------------------------------------------------- scheduler
    def _check_scheduler(self):
        sc = self.settings["scheduler"]
        if not sc.get("enabled"):
            return
        now = datetime.datetime.now()
        if now.weekday() not in sc.get("days", []):
            return
        hm = now.strftime("%H:%M")
        key = now.strftime("%Y-%m-%d ") + hm
        if sc.get("start_time") == hm and ("start", key) not in self._sched_fired:
            self._sched_fired.add(("start", key))
            self.start_queue(by_scheduler=True)
        if sc.get("stop_time") and sc["stop_time"] == hm and ("stop", key) not in self._sched_fired:
            self._sched_fired.add(("stop", key))
            self.stop_queue()

    # ---------------------------------------------------------- engine
    def _done_from_thread(self, eng, status, error):
        self._engine_done.emit(eng, status, error)

    def _on_engine_done(self, eng, status, error):
        it = eng.item
        was_queue = getattr(eng, "from_queue", False)
        if self.engines.get(it.id) is eng:
            del self.engines[it.id]
        it.downloaded = eng.downloaded() if status != "completed" else (it.size if it.size > 0 else eng.downloaded())
        it.speed, it.eta, it.connections = 0, -1, 0
        if status == "completed":
            it.status = COMPLETED
            it.finished = time.time()
            if it.size <= 0:
                try:
                    it.size = os.path.getsize(it.path)
                except OSError:
                    pass
            it.downloaded = it.size
            it.cookies, it.cookie_jar = "", None      # not needed any more - don't keep logins around
        elif status == "stopped":
            # stopped by "Stop queue" -> stays in the queue; stopped by the user -> paused
            it.status = QUEUED if getattr(eng, "requeue", False) else PAUSED
        else:
            it.status = ERROR
            it.error = error or "Unknown error"
        if it.id in self.items:
            self.item_updated.emit(it.id)
            self.item_finished.emit(it.id, it.status)
        self.save()
        if was_queue or self.queue_running:
            self._process_queue()

    def _tick(self):
        now = time.monotonic()
        for item_id, eng in list(self.engines.items()):
            it = self.items.get(item_id)
            if not it:
                continue
            done = eng.downloaded()
            t0, b0 = self._last.get(item_id, (now, done))
            dt = now - t0
            if dt >= 0.9:
                inst = max(0, done - b0) / dt
                it.speed = inst if it.speed <= 0 else it.speed * 0.6 + inst * 0.4
                self._last[item_id] = (now, done)
            it.downloaded = done
            it.connections = eng.active_connections()
            if done > 0 and it.status == CONNECTING:
                it.status = DOWNLOADING
            if it.size > 0 and it.speed > 0:
                it.eta = (it.size - done) / it.speed
            else:
                it.eta = -1
            self.item_updated.emit(item_id)
        if self._dirty:
            self.save()

    def total_speed(self):
        return sum(self.items[i].speed for i in self.engines if i in self.items)

    def shutdown(self):
        self.timer.stop()
        for eng in list(self.engines.values()):
            eng.stop()
        deadline = time.monotonic() + 3
        for eng in list(self.engines.values()):
            if eng.thread:
                eng.thread.join(max(0, deadline - time.monotonic()))
        for item_id, eng in list(self.engines.items()):
            it = self.items.get(item_id)
            if it and it.status != COMPLETED:
                it.status = PAUSED
        self.save()
