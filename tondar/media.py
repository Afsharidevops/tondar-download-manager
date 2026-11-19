"""Video / audio grabbing through yt-dlp (YouTube and ~1800 other sites).

The official yt-dlp release (a single zipapp that already contains the
yt-dlp-ejs challenge solver) and Deno (the JavaScript runtime YouTube now
requires) are downloaded into ~/.local/share/tondar/bin on first use, so a
stale distro package never breaks YouTube downloads. "Tools > Update yt-dlp"
refreshes them.
"""
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import zipfile
import io

from .config import BIN_DIR, find_tool
from .engine import build_opener, sanitize_filename

YTDLP_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
YTDLP_ZIPAPP_URL = YTDLP_BASE + "yt-dlp"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-{arch}-unknown-linux-gnu.zip"


def _arch():
    return {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64",
            "arm64": "aarch64"}.get(platform.machine().lower())


# The standalone build bundles everything yt-dlp can use: pycryptodomex (AES-128
# encrypted HLS, used by many Iranian VOD services - without it yt-dlp hands the
# stream to ffmpeg: one connection and no progress), curl_cffi, brotli, websockets.
STANDALONE = {"x86_64": "yt-dlp_linux", "aarch64": "yt-dlp_linux_aarch64"}.get(_arch() or "")
STANDALONE_PATH = BIN_DIR / "yt-dlp_linux"
ZIPAPP_PATH = BIN_DIR / "yt-dlp"


class MediaError(Exception):
    pass


# --------------------------------------------------------------------------
# helper binaries
# --------------------------------------------------------------------------
def ytdlp_command():
    if STANDALONE_PATH.exists() and os.access(STANDALONE_PATH, os.X_OK):
        return [str(STANDALONE_PATH)]
    if ZIPAPP_PATH.exists():
        return [sys.executable, str(ZIPAPP_PATH)]   # zipapp; run with our python
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        return None


def js_runtime_args():
    deno = find_tool("deno")
    if deno:
        return ["--js-runtimes", f"deno:{deno}"]
    node = shutil.which("node") or shutil.which("nodejs")
    if node:
        return ["--no-js-runtimes", "--js-runtimes", f"node:{node}"]
    return []


def tools_status():
    return {
        "yt-dlp": bool(ytdlp_command()),
        "yt-dlp-version": ytdlp_version(),
        "deno": bool(find_tool("deno")),
        "node": bool(shutil.which("node") or shutil.which("nodejs")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }


def ytdlp_version():
    cmd = ytdlp_command()
    if not cmd:
        return ""
    try:
        return subprocess.run(cmd + ["--version"], capture_output=True, text=True,
                              timeout=60).stdout.strip()
    except Exception:
        return ""


def _fetch(url, settings, timeout=120):
    opener = build_opener(settings["proxy"], settings["use_system_proxy"])
    opener.addheaders = [("User-Agent", "tondar-dm")]
    with opener.open(url, timeout=timeout) as r:
        return r.read()


def _install_file(data, dest):
    tmp = dest.with_name(dest.name + ".new")
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    os.replace(tmp, dest)


def install_tools(settings, log=print, deno=True):
    """Download latest yt-dlp (+ Deno). Raises on failure."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    done = False
    if STANDALONE:
        log("Downloading latest yt-dlp (standalone build, ~40 MB) ...")
        try:
            _install_file(_fetch(YTDLP_BASE + STANDALONE, settings, 600), STANDALONE_PATH)
            done = True
            if ZIPAPP_PATH.exists():
                ZIPAPP_PATH.unlink()
        except Exception as e:  # noqa: BLE001
            log(f"Standalone build failed ({e}); using the small Python build instead.")
    if not done:
        log("Downloading latest yt-dlp ...")
        _install_file(_fetch(YTDLP_ZIPAPP_URL, settings), ZIPAPP_PATH)
    log(f"yt-dlp {ytdlp_version()} installed.")
    if deno and not shutil.which("deno") and not (BIN_DIR / "deno").exists():
        arch = _arch()
        if not arch:
            log("Deno has no build for this CPU; install nodejs instead (apt install nodejs).")
            return
        log("Downloading Deno JavaScript runtime (needed for YouTube) ...")
        z = zipfile.ZipFile(io.BytesIO(_fetch(DENO_URL.format(arch=arch), settings, 300)))
        _install_file(z.read("deno"), BIN_DIR / "deno")
        log("Deno installed.")


_install_lock = threading.Lock()


def _have_own_ytdlp():
    return STANDALONE_PATH.exists() if STANDALONE else ZIPAPP_PATH.exists()


def ensure_tools(settings, log=print):
    """First use (or upgrade from the small build): fetch our own up-to-date yt-dlp."""
    with _install_lock:
        if _have_own_ytdlp():
            return
        try:
            install_tools(settings, log=log)
        except Exception as e:  # noqa: BLE001
            if not ytdlp_command():
                raise MediaError(f"Could not download yt-dlp ({e}). Set a proxy in Options "
                                 "or install it: sudo apt install yt-dlp")


def auto_update(settings, max_age_days=7):
    """Refresh yt-dlp in the background when it is older than a week (sites change often)."""
    p = STANDALONE_PATH if STANDALONE_PATH.exists() else ZIPAPP_PATH
    stale = p.exists() and time.time() - p.stat().st_mtime > max_age_days * 86400
    if stale or not _have_own_ytdlp():
        def run():
            try:
                with _install_lock:
                    install_tools(settings, log=lambda *_: None, deno=not p.exists())
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()


def _base_args(settings, cookies_browser=True):
    cmd = ytdlp_command()
    if not cmd:
        raise MediaError("yt-dlp is not installed. Use Tools > Install/Update yt-dlp.")
    args = cmd + ["--no-warnings", "--ignore-config"] + js_runtime_args()
    if settings["proxy"]:
        args += ["--proxy", settings["proxy"]]
    if cookies_browser and settings.get("ytdlp_cookies_browser"):
        args += ["--cookies-from-browser", settings["ytdlp_cookies_browser"]]
    ff = shutil.which("ffmpeg")
    if ff:
        args += ["--ffmpeg-location", ff]
    extra = (settings.get("ytdlp_extra_args") or "").split()
    return args + extra


def _env():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    env["PATH"] = f"{BIN_DIR}:{env.get('PATH', '')}"
    return env


# --------------------------------------------------------------------------
# probing
# --------------------------------------------------------------------------
def _header_args(referer="", cookies="", user_agent="", headers=None):
    args = []
    for k, v in (headers or {}).items():
        if v and k.lower() not in ("referer", "cookie", "user-agent"):
            args += ["--add-header", f"{k}:{v}"]
    if referer:
        args += ["--referer", referer]
    if cookies:
        args += ["--add-header", f"Cookie:{cookies}"]
    if user_agent:
        args += ["--user-agent", user_agent]
    return args


def probe_media(url, settings, playlist=False, timeout=90, referer="", cookies="", headers=None):
    """Return {'title','ext','thumbnail','duration','options':[...]}"""
    ensure_tools(settings)
    args = _base_args(settings) + _header_args(referer, cookies, headers=headers) + \
        ["-J", "--no-playlist" if not playlist else "--flat-playlist", url]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_env())
    except subprocess.TimeoutExpired:
        raise MediaError("yt-dlp timed out while reading the page")
    if p.returncode != 0 or not p.stdout.strip():
        err = [ln for ln in p.stderr.splitlines() if "ERROR" in ln]
        raise MediaError((err[-1] if err else p.stderr.strip()[-400:]) or "yt-dlp failed")
    info = json.loads(p.stdout)
    return build_options(info)


def _fsize(f, duration=0):
    """(bytes, approximate?) - exact size, yt-dlp's estimate, or bitrate x duration."""
    if not f:
        return 0, False
    if f.get("filesize"):
        return int(f["filesize"]), False
    if f.get("filesize_approx"):
        return int(f["filesize_approx"]), True
    rate = f.get("tbr") or ((f.get("vbr") or 0) + (f.get("abr") or 0))
    if rate and duration:
        return int(rate * 1000 / 8 * duration), True     # kbit/s -> bytes
    return 0, True


def _is_stream(f):
    return str(f.get("protocol", "")).startswith(("m3u8", "http_dash_segments"))


def build_options(info):
    title = info.get("title") or "video"
    duration = info.get("duration") or 0
    formats = info.get("formats") or []
    if not formats and info.get("url"):
        formats = [info]
    has_ffmpeg = bool(shutil.which("ffmpeg"))
    options = []

    audio_only = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    video_only = [f for f in formats if f.get("acodec") == "none" and f.get("vcodec") not in (None, "none")]
    muxed = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("vcodec") not in (None, "none")]
    # sites that do not report codecs: treat as muxed
    unknown = [f for f in formats if f.get("vcodec") is None and f.get("acodec") is None
               and f.get("protocol") not in ("mhtml",)]
    muxed += unknown

    best_m4a = max((f for f in audio_only if f.get("ext") == "m4a"), key=lambda f: f.get("abr") or 0, default=None)
    best_audio = max(audio_only, key=lambda f: f.get("abr") or 0, default=None)
    pair_audio = best_m4a or best_audio

    by_height = {}
    if has_ffmpeg and pair_audio:
        for f in video_only:
            h = f.get("height") or 0
            if not h:
                continue
            cur = by_height.get(h)
            # prefer H.264 MP4 (plays everywhere), then direct files over HLS/DASH
            # fragments (known size, faster), then frame rate and bitrate
            score = (1 if (f.get("ext") == "mp4" and str(f.get("vcodec", "")).startswith("avc")) else 0,
                     0 if _is_stream(f) else 1, f.get("fps") or 0, f.get("tbr") or 0)
            if cur is None or score > cur[0]:
                by_height[h] = (score, f)
    for f in muxed:
        h = f.get("height") or 0
        cur = by_height.get(h)
        score = (2, 0 if _is_stream(f) else 1, f.get("fps") or 0, f.get("tbr") or 0)  # no merge needed
        if cur is None or (h and score > cur[0]):
            by_height[h] = (score, f)

    for h in sorted(by_height, reverse=True):
        f = by_height[h][1]
        needs_audio = f.get("acodec") == "none"
        ext = "mp4" if (needs_audio and f.get("ext") in ("mp4", "m4v")) or f.get("ext") == "mp4" else (
            "mkv" if needs_audio and f.get("ext") == "webm" and pair_audio and pair_audio.get("ext") != "webm"
            else f.get("ext") or "mp4")
        vsize, vapprox = _fsize(f, duration)
        asize, aapprox = _fsize(pair_audio, duration) if needs_audio else (0, False)
        # unknown video size -> report unknown, never just the audio part
        size, approx = (vsize + asize, vapprox or aapprox) if vsize else (0, True)
        sel = f"{f['format_id']}+{pair_audio['format_id']}" if needs_audio else f["format_id"]
        fps = f" {int(f['fps'])}fps" if f.get("fps") and f["fps"] > 30 else ""
        label = f"{ext.upper()} {h}p{fps}" if h else f"{ext.upper()} " + (
            f.get("format_note") or f.get("resolution") or "original quality")
        options.append({"id": sel, "label": label, "ext": ext, "size": size, "approx": approx,
                        "type": "video", "height": h})

    if pair_audio:
        abr = int(pair_audio.get("abr") or 0)
        asize, aapprox = _fsize(pair_audio, duration)
        options.append({"id": pair_audio["format_id"], "label": f"{pair_audio.get('ext', 'audio').upper()} audio"
                        + (f" {abr} kbps" if abr else ""), "ext": pair_audio.get("ext", "m4a"),
                        "size": asize, "approx": aapprox, "type": "audio"})
        if has_ffmpeg:
            # MP3 is re-encoded at ~VBR V0 (~245 kbps) - estimate from duration
            mp3 = int(245 * 1000 / 8 * duration) if duration else asize
            options.append({"id": "bestaudio/best", "label": "MP3 audio (converted)", "ext": "mp3",
                            "size": mp3, "approx": True, "type": "mp3"})
    if not options:
        size, approx = _fsize(info, duration)
        options.append({"id": "best", "label": "Best quality", "ext": info.get("ext") or "mp4",
                        "size": size, "approx": approx, "type": "video"})
    return {
        "title": title,
        "thumbnail": info.get("thumbnail") or "",
        "duration": info.get("duration") or 0,
        "webpage_url": info.get("webpage_url") or info.get("original_url") or "",
        "extractor": info.get("extractor_key") or "",
        "options": options,
    }


def media_filename(title, ext):
    return sanitize_filename(re.sub(r"[\\:*?\"<>|]", "_", title))[:180] + "." + ext


# --------------------------------------------------------------------------
# downloader (same interface as engine.HttpDownloader)
# --------------------------------------------------------------------------
PROG_RE = re.compile(r"^TDPROG (\S+) (\S+) (\S+) (\S+) (\S+)$")


class MediaDownloader:
    def __init__(self, item, settings, limiter, on_done):
        self.item = item
        self.settings = settings
        self.on_done = on_done
        self.proc = None
        self.thread = None
        self.stopped = False
        self.lock = threading.Lock()
        self.done_streams = {}      # format_id -> bytes
        self.cur_fmt = None
        self.cur_bytes = 0
        self.cur_total = 0
        self.last_err = ""
        self.tail = []              # last lines of yt-dlp output, for error messages
        self.last_prog = 0.0
        self.disk_bytes = 0

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _watch_disk(self, base):
        """Fallback progress: when yt-dlp hands a stream to ffmpeg it reports nothing,
        so measure the temporary files growing on disk instead."""
        d = self.item.save_dir
        while self.proc is None or self.proc.poll() is None:
            time.sleep(1)
            if time.monotonic() - self.last_prog < 3:
                continue
            total = 0
            try:
                for name in os.listdir(d):
                    if name.startswith(base) and (".part" in name or ".temp" in name or "Frag" in name
                                                  or name.endswith(".ytdl")):
                        try:
                            total += os.path.getsize(os.path.join(d, name))
                        except OSError:
                            pass
            except OSError:
                pass
            with self.lock:
                self.disk_bytes = total

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGINT)
            except Exception:
                self.proc.terminate()

    def downloaded(self):
        with self.lock:
            return max(sum(self.done_streams.values()) + self.cur_bytes, self.disk_bytes)

    def snapshot(self):
        return []

    def active_connections(self):
        return self.settings["max_connections"] if self.proc and self.proc.poll() is None else 0

    def _run(self):
        it = self.item
        try:
            ensure_tools(self.settings, log=lambda *_: None)
            os.makedirs(it.save_dir, exist_ok=True)
            base = os.path.splitext(it.filename)[0]
            ext = os.path.splitext(it.filename)[1].lstrip(".") or "mp4"
            args = _base_args(self.settings) + [
                "--no-playlist", "--newline", "--progress", "--continue", "--no-mtime",
                "--progress-template",
                "download:TDPROG %(info.format_id)s %(progress.downloaded_bytes)s "
                "%(progress.total_bytes)s %(progress.total_bytes_estimate)s %(progress.speed)s",
                "--print", "after_move:TDFILE %(filepath)s",
                "-N", str(max(1, min(16, self.settings["max_connections"]))),
                "-o", os.path.join(it.save_dir, base.replace("%", "%%") + ".%(ext)s"),
            ]
            lim = self.settings.speed_limit_bytes()
            if lim:
                args += ["-r", str(lim)]
            if it.media_format == "bestaudio/best" and ext == "mp3":
                args += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
            else:
                args += ["-f", it.media_format or "bv*+ba/b"]
                if "+" in (it.media_format or "+"):
                    args += ["--merge-output-format", ext if ext in ("mp4", "mkv", "webm") else "mp4"]
            args += _header_args(it.referer, it.cookies, it.user_agent, it.headers)
            args.append(it.page_url or it.url)
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, env=_env(), bufsize=1,
                                         start_new_session=True, encoding="utf-8", errors="replace")
            threading.Thread(target=self._watch_disk, args=(base,), daemon=True).start()
            final_path = None
            for line in self.proc.stdout:
                line = line.strip()
                m = PROG_RE.match(line)
                if m:
                    self.last_prog = time.monotonic()
                    self._progress(*m.groups())
                    continue
                if line.startswith("TDFILE "):
                    final_path = line[7:]
                elif line.startswith("ERROR"):
                    self.last_err = line
                if line:
                    self.tail = (self.tail + [line])[-15:]
            rc = self.proc.wait()
            if self.stopped:
                self.on_done(self, "stopped", None)
            elif rc == 0:
                if final_path and os.path.exists(final_path):
                    it.save_dir, it.filename = os.path.split(final_path)
                    it.size = os.path.getsize(final_path)
                    with self.lock:
                        self.done_streams = {"all": it.size}
                        self.cur_bytes = 0
                self.on_done(self, "completed", None)
            else:
                msg = self.last_err.replace("ERROR: ", "") or (self.tail[-1] if self.tail else "")
                self.on_done(self, "error", msg or f"yt-dlp exit code {rc}")
        except Exception as e:  # noqa: BLE001
            self.on_done(self, "error", str(e))

    def _progress(self, fmt, done, total, est, speed):
        def num(x):
            try:
                return float(x)
            except ValueError:
                return 0.0
        done, total, est = num(done), num(total), num(est)
        with self.lock:
            if fmt != self.cur_fmt:
                if self.cur_fmt is not None:
                    self.done_streams[self.cur_fmt] = self.cur_total or self.cur_bytes
                self.cur_fmt = fmt
            self.cur_bytes = int(done)
            self.cur_total = int(total or est)
            known = sum(self.done_streams.values()) + self.cur_total
            if known > 0 and (self.item.size <= 0 or total):
                self.item.size = max(known, sum(self.done_streams.values()) + self.cur_bytes)
