"""HTTP/HTTPS/FTP download engine with IDM-style dynamic segmentation.

How it works
------------
* The file is split into N segments (N = max connections). Every segment is
  fetched by its own connection with an HTTP Range request and written in place
  (pwrite) into a pre-allocated ``.tdpart`` file.
* When a connection finishes its segment it does not sit idle: it takes the
  segment with the most bytes left, splits it in half and downloads the second
  half ("dynamic file segmentation"), so all connections stay busy until the end.
* Segment state is persisted, so a paused / crashed download resumes exactly
  where every segment stopped.
* Servers without Range support fall back to a single connection.
"""
import base64
import email.message
import http.client
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import mimetypes

CHUNK = 64 * 1024
MIN_SPLIT = 512 * 1024          # never split a segment into parts smaller than this
PART_SUFFIX = ".tdpart"

NET_ERRORS = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
              http.client.HTTPException, ssl.SSLError, OSError)


class FatalError(Exception):
    """Error that retrying will not fix (404, 403, disk full...)."""


# --------------------------------------------------------------------------
# Global speed limiter (token bucket shared by every connection)
# --------------------------------------------------------------------------
class SpeedLimiter:
    def __init__(self, rate_fn):
        self.rate_fn = rate_fn          # callable -> bytes/sec, 0 = unlimited
        self.lock = threading.Lock()
        self.tokens = 0.0
        self.last = time.monotonic()

    def chunk_size(self):
        rate = self.rate_fn()
        return CHUNK if rate <= 0 else max(4096, min(CHUNK, rate // 10))

    def consume(self, n):
        """Debt-based bucket: take n tokens, sleep off any deficit."""
        rate = self.rate_fn()
        if rate <= 0:
            with self.lock:
                self.tokens = 0.0
                self.last = time.monotonic()
            return
        with self.lock:
            now = time.monotonic()
            self.tokens = min(rate * 0.5, self.tokens + (now - self.last) * rate)
            self.last = now
            self.tokens -= n
            wait = -self.tokens / rate if self.tokens < 0 else 0.0
        if wait > 0:
            time.sleep(wait)


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------
_SSL_CTX = None


def ssl_context():
    """TLS context that trusts what the operating system trusts.

    The Python inside the Windows/macOS builds has its own OpenSSL, which only sees the root
    certificates Windows has already downloaded (Windows fetches missing roots on demand, OpenSSL
    can't) and none at all on macOS -> CERTIFICATE_VERIFY_FAILED. truststore asks the OS itself;
    certifi's bundle is the fallback."""
    global _SSL_CTX
    if _SSL_CTX is None:
        ctx = None
        try:
            import truststore
            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:  # noqa: BLE001 - not installed / unsupported
            ctx = ssl.create_default_context()
            try:
                import certifi
                ctx.load_verify_locations(certifi.where())
            except Exception:  # noqa: BLE001
                pass
        _SSL_CTX = ctx
    return _SSL_CTX


def build_opener(proxy: str = "", use_system_proxy: bool = True):
    handlers = [urllib.request.HTTPSHandler(context=ssl_context())]
    if proxy:
        if proxy.startswith("socks"):
            try:
                import socks  # python3-socks
                from sockshandler import SocksiPyHandler
                u = urllib.parse.urlparse(proxy)
                ptype = socks.SOCKS5 if "5" in u.scheme else socks.SOCKS4
                # replaces the HTTPS handler (two handlers for https would bypass the proxy)
                handlers = [SocksiPyHandler(ptype, u.hostname, u.port or 1080, rdns=True,
                                            username=u.username, password=u.password)]
            except ImportError:
                raise FatalError("SOCKS proxy needs the python3-socks package "
                                 "(sudo apt install python3-socks)")
        else:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    elif not use_system_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def normalize_url(url):
    """Percent-encode spaces and other characters http.client refuses."""
    return urllib.parse.quote(url.strip(), safe=":/?#[]@!$&'()*+,;=%~")


def make_request(url, headers, rng=None, method="GET"):
    url = normalize_url(url)
    req = urllib.request.Request(url, method=method)
    for k, v in (headers or {}).items():
        if v:
            req.add_header(k, v)
    u = urllib.parse.urlsplit(url)
    if u.username and "Authorization" not in (headers or {}):
        cred = f"{urllib.parse.unquote(u.username)}:{urllib.parse.unquote(u.password or '')}"
        req.add_header("Authorization", "Basic " + base64.b64encode(cred.encode()).decode())
        netloc = u.hostname + (f":{u.port}" if u.port else "")
        req.full_url = urllib.parse.urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))
    if rng is not None:
        start, end = rng
        req.add_header("Range", f"bytes={start}-{'' if end is None else end}")
    req.add_header("Accept-Encoding", "identity")
    return req


def filename_from_headers(headers, url, content_type=""):
    cd = headers.get("Content-Disposition", "") if headers else ""
    name = ""
    if cd:
        m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", cd, re.I)
        if m:
            name = urllib.parse.unquote(m.group(2).strip().strip('"'),
                                        encoding=m.group(1) or "utf-8", errors="replace")
        else:
            msg = email.message.Message()
            msg["content-disposition"] = cd
            name = msg.get_filename() or ""
            try:  # servers often send raw UTF-8 that got decoded as latin-1
                name = name.encode("latin-1").decode("utf-8")
            except Exception:
                pass
    if not name:
        path = urllib.parse.urlsplit(url).path
        name = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
    name = sanitize_filename(name) or "download"
    if "." not in name and content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            name += ext
    return name


def sanitize_filename(name: str) -> str:
    name = name.replace("/", "_").replace("\x00", "").strip().strip(".")
    return name[:240]


def replace_with_retry(src, dst, tries=40):
    """os.replace, but survive Windows' brief locks on fresh files (Defender / Search indexer
    scanning the file just after it was written: WinError 32 / 5)."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(min(0.1 * (i + 1), 0.5))


def unique_path(path: str) -> str:
    if not os.path.exists(path) and not os.path.exists(path + PART_SUFFIX):
        return path
    base, ext = os.path.splitext(path)
    if base.endswith(".tar"):
        base, ext = base[:-4], ".tar" + ext
    i = 2
    while True:
        p = f"{base} ({i}){ext}"
        if not os.path.exists(p) and not os.path.exists(p + PART_SUFFIX):
            return p
        i += 1


def probe(url, headers=None, proxy="", use_system_proxy=True, timeout=20):
    """Ask the server for size, range support and file name."""
    opener = build_opener(proxy, use_system_proxy)
    info = {"url": url, "final_url": url, "size": -1, "resumable": False,
            "filename": "", "content_type": ""}
    if url.lower().startswith("ftp://"):
        with opener.open(make_request(url, headers), timeout=timeout) as r:
            ln = r.headers.get("Content-Length")
            info["size"] = int(ln) if ln else -1
            info["resumable"] = info["size"] > 0
            info["filename"] = filename_from_headers(None, url)
        return info
    try:
        r = opener.open(make_request(url, headers, rng=(0, None)), timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416:  # empty file or server dislikes ranges -> plain GET
            r = opener.open(make_request(url, headers), timeout=timeout)
        else:
            raise
    with r:
        h = r.headers
        info["final_url"] = r.geturl()
        info["content_type"] = h.get("Content-Type", "")
        cr = h.get("Content-Range", "")
        m = re.match(r"bytes\s+\d+-\d+/(\d+)", cr)
        if r.status == 206 and m:
            info["size"] = int(m.group(1))
            info["resumable"] = True
        else:
            ln = h.get("Content-Length")
            info["size"] = int(ln) if ln and ln.isdigit() else -1
            info["resumable"] = False
        info["filename"] = filename_from_headers(h, info["final_url"], info["content_type"])
    return info


# --------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------
class Segment:
    __slots__ = ("start", "end", "pos", "active", "speed_bytes")

    def __init__(self, start, end, pos=None):
        self.start, self.end = start, end
        self.pos = start if pos is None else pos
        self.active = False
        self.speed_bytes = 0

    @property
    def remaining(self):
        return max(0, self.end - self.pos + 1)

    def to_list(self):
        return [self.start, self.end, self.pos]


# --------------------------------------------------------------------------
# Downloader
# --------------------------------------------------------------------------
class HttpDownloader:
    """Downloads one item. Runs in its own thread; call start()/stop()."""

    def __init__(self, item, settings, limiter, on_done):
        self.item = item
        self.settings = settings
        self.limiter = limiter
        self.on_done = on_done
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.segments = []
        self.single_pos = 0
        self.fatal = None
        self.fd = None
        self.opener = None

    # -- public -----------------------------------------------------------
    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name=f"dl-{self.item.id}")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def downloaded(self):
        with self.lock:
            if self.segments:
                return sum(s.pos - s.start for s in self.segments)
            return self.single_pos

    def snapshot(self):
        """[(start, end, pos, active)] for the progress window."""
        with self.lock:
            return [(s.start, s.end, s.pos, s.active) for s in self.segments]

    def active_connections(self):
        with self.lock:
            return sum(1 for s in self.segments if s.active) or (1 if not self.segments else 0)

    # -- internals ----------------------------------------------------------
    def _headers(self):
        it = self.item
        h = {"User-Agent": it.user_agent or self.settings["user_agent"]}
        if it.referer:
            h["Referer"] = it.referer
        if it.cookies:
            h["Cookie"] = it.cookies
        h.update(it.headers or {})
        return h

    def _run(self):
        it = self.item
        try:
            self.opener = build_opener(self.settings["proxy"], self.settings["use_system_proxy"])
            info = probe(it.url, self._headers(), self.settings["proxy"],
                         self.settings["use_system_proxy"], self.settings["timeout"])
            if it.size > 0 and info["size"] > 0 and info["size"] != it.size and it.segments:
                it.segments = []           # file changed on server -> restart
            it.size = info["size"]
            it.resumable = info["resumable"]
            it.final_url = info["final_url"]
            os.makedirs(it.save_dir, exist_ok=True)
            if it.auto_name and info["filename"] and not it.segments:
                # name came from the URL; the server's Content-Disposition name wins
                it.filename = os.path.basename(unique_path(os.path.join(it.save_dir, info["filename"])))
            it.auto_name = False
            part = it.path + PART_SUFFIX
            if it.resumable and it.size > 0:
                self._segmented(part)
            else:
                self._single(part)
            # Windows cannot rename (or let others open) a file that is still open
            self._close_fd()
            if self.fatal:
                raise self.fatal
            if self.stop_event.is_set():
                self._persist()
                self.on_done(self, "stopped", None)
                return
            final = it.path
            if os.path.exists(final):
                final = unique_path(final)
                it.filename = os.path.basename(final)
            replace_with_retry(part, final)
            it.segments = []
            self.on_done(self, "completed", None)
        except Exception as e:  # noqa: BLE001
            self._persist()
            self.on_done(self, "error", _describe_error(e))
        finally:
            self._close_fd()

    def _close_fd(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def _persist(self):
        with self.lock:
            if self.segments:
                self.item.segments = [s.to_list() for s in self.segments]
            self.item.downloaded = self.downloaded_nolock()

    def downloaded_nolock(self):
        if self.segments:
            return sum(s.pos - s.start for s in self.segments)
        return self.single_pos

    # ---- segmented -----------------------------------------------------
    def _segmented(self, part):
        it = self.item
        size = it.size
        if it.segments and os.path.exists(part):
            self.segments = [Segment(*s) for s in it.segments]
        else:
            it.segments = []
            n = max(1, min(self.settings["max_connections"], size // MIN_SPLIT or 1))
            step = size // n
            self.segments = []
            for i in range(n):
                start = i * step
                end = size - 1 if i == n - 1 else (i + 1) * step - 1
                self.segments.append(Segment(start, end))
        self.fd = os.open(part, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        if os.fstat(self.fd).st_size != size:
            os.ftruncate(self.fd, size)

        workers = []
        for _ in range(max(1, self.settings["max_connections"])):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            workers.append(t)
            time.sleep(0.05)   # stagger connection openings like a browser
        last_save = time.monotonic()
        while any(t.is_alive() for t in workers):
            time.sleep(0.2)
            if time.monotonic() - last_save > 5:
                self._persist()
                last_save = time.monotonic()
        if not self.stop_event.is_set() and not self.fatal:
            if any(s.remaining for s in self.segments):
                self.fatal = FatalError("Connection closed before the file was complete")
        os.fsync(self.fd)
        self._close_fd()

    def _next_segment(self):
        with self.lock:
            for s in self.segments:
                if not s.active and s.remaining > 0:
                    s.active = True
                    return s
            # split the biggest running segment (dynamic segmentation)
            busy = [s for s in self.segments if s.active and s.remaining >= 2 * MIN_SPLIT]
            if not busy:
                return None
            big = max(busy, key=lambda s: s.remaining)
            mid = big.pos + big.remaining // 2
            new = Segment(mid, big.end)
            big.end = mid - 1
            new.active = True
            self.segments.insert(self.segments.index(big) + 1, new)
            return new

    def _worker(self):
        while not self.stop_event.is_set() and not self.fatal:
            seg = self._next_segment()
            if seg is None:
                return
            try:
                self._fetch(seg)
            except FatalError as e:
                self.fatal = e
                self.stop_event.set()
            finally:
                with self.lock:
                    seg.active = False

    def _fetch(self, seg):
        errors = 0
        retries = self.settings["retries"]
        while not self.stop_event.is_set() and seg.remaining > 0:
            try:
                with self.lock:
                    start, end = seg.pos, seg.end
                req = make_request(self.item.final_url or self.item.url, self._headers(), (start, end))
                with self.opener.open(req, timeout=self.settings["timeout"]) as r:
                    if r.status != 206:
                        raise FatalError("Server stopped supporting resume (no HTTP 206)")
                    while not self.stop_event.is_set():
                        with self.lock:
                            want = seg.end - seg.pos + 1
                        if want <= 0:
                            break
                        data = r.read(min(self.limiter.chunk_size(), want))
                        if not data:
                            break
                        self.limiter.consume(len(data))
                        with self.lock:
                            allowed = seg.end - seg.pos + 1
                            pos = seg.pos
                        if allowed <= 0:
                            break
                        data = data[:allowed]
                        self._write_at(data, pos)
                        with self.lock:
                            seg.pos = min(seg.pos + len(data), seg.end + 1)
                        errors = 0
            except FatalError:
                raise
            except urllib.error.HTTPError as e:
                if e.code in (400, 401, 403, 404, 410, 416) and errors >= 2:
                    raise FatalError(f"HTTP {e.code} {e.reason}")
                errors += 1
                self._backoff(errors, retries, e)
            except OSError as e:
                if getattr(e, "errno", None) == 28:  # ENOSPC
                    raise FatalError("Disk is full")
                errors += 1
                self._backoff(errors, retries, e)

    _wlock = None

    def _write_at(self, data, pos):
        """pwrite() where available (Linux/macOS); Windows has no pwrite, so seek+write under a lock."""
        if hasattr(os, "pwrite"):
            os.pwrite(self.fd, data, pos)
            return
        if self._wlock is None:
            self._wlock = threading.Lock()
        with self._wlock:
            os.lseek(self.fd, pos, os.SEEK_SET)
            view = memoryview(data)
            while view:
                n = os.write(self.fd, view)
                view = view[n:]

    def _backoff(self, errors, retries, exc):
        if errors > retries:
            raise FatalError(_describe_error(exc))
        self.stop_event.wait(min(1.5 * errors, 15))

    # ---- single connection -------------------------------------------------
    def _single(self, part):
        it = self.item
        self.segments = []
        it.segments = []
        errors = 0
        while not self.stop_event.is_set():
            try:
                self.single_pos = 0
                with self.opener.open(make_request(it.final_url or it.url, self._headers()),
                                      timeout=self.settings["timeout"]) as r, \
                        open(part, "wb") as f:
                    while not self.stop_event.is_set():
                        data = r.read(self.limiter.chunk_size())
                        if not data:
                            break
                        self.limiter.consume(len(data))
                        f.write(data)
                        with self.lock:
                            self.single_pos += len(data)
                if self.stop_event.is_set():
                    return
                if it.size > 0 and self.single_pos < it.size:
                    raise ConnectionError("Connection closed early")
                if it.size <= 0:
                    it.size = self.single_pos
                return
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404, 410):
                    raise FatalError(f"HTTP {e.code} {e.reason}")
                errors += 1
                self._backoff(errors, self.settings["retries"], e)
            except OSError as e:
                errors += 1
                self._backoff(errors, self.settings["retries"], e)


def _describe_error(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} {e.reason}"
    if isinstance(e, urllib.error.URLError):
        return f"Connection error: {e.reason}"
    return str(e) or e.__class__.__name__
