"""The persistent download record."""
import os
import time
import uuid

QUEUED = "Queued"
WAITING = "Waiting"          # added with "Download later", not in any running queue
DOWNLOADING = "Downloading"
PAUSED = "Paused"
COMPLETED = "Complete"
ERROR = "Error"
CONNECTING = "Connecting"

KIND_HTTP = "http"
KIND_MEDIA = "media"         # handled by yt-dlp

FIELDS = dict(
    id="", url="", final_url="", filename="", save_dir="", category="General",
    size=-1, downloaded=0, resumable=False, status=WAITING, segments=None,
    added=0.0, last_try=0.0, finished=0.0, description="", referer="", cookies="",
    user_agent="", headers=None, kind=KIND_HTTP, media_format="", media_title="",
    error="", queue="Main queue", page_url="", auto_name=False, cookie_jar=None, refresh_wait=False,
)


class DownloadItem:
    def __init__(self, **kw):
        for k, v in FIELDS.items():
            setattr(self, k, kw.get(k, v.copy() if isinstance(v, (list, dict)) else v))
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.added:
            self.added = time.time()
        if self.segments is None:
            self.segments = []
        if self.headers is None:
            self.headers = {}
        # runtime only
        self.speed = 0.0
        self.eta = -1
        self.connections = 0

    @property
    def path(self):
        return os.path.join(self.save_dir, self.filename)

    @property
    def progress(self):
        if self.size > 0:
            return min(1.0, self.downloaded / self.size)
        return 1.0 if self.status == COMPLETED else 0.0

    def to_dict(self):
        return {k: getattr(self, k) for k in FIELDS}

    @classmethod
    def from_dict(cls, d):
        item = cls(**{k: v for k, v in d.items() if k in FIELDS})
        if item.status in (DOWNLOADING, CONNECTING):
            item.status = PAUSED
        return item


def human_size(n):
    if n is None or n < 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024.0


def human_speed(bps):
    if not bps or bps <= 0:
        return ""
    return human_size(bps) + "/sec"


def human_eta(sec):
    if sec is None or sec < 0:
        return ""
    sec = int(sec)
    if sec < 60:
        return f"{sec} sec"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m} min {s} sec"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} hr {m} min"
    d, h = divmod(h, 24)
    return f"{d} day {h} hr"
