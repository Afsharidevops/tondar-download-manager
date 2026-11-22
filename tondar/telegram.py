"""Optional Telegram support, through tdl (https://github.com/iyear/tdl, AGPL-3.0).

Nothing here runs unless the user opens Tasks > Telegram... and sets it up:
tdl is downloaded on request into Tondar's private bin dir, the Telegram login
is kept in Tondar's own data dir (DATA_DIR/telegram, not ~/.tdl) and "Log out"
deletes it.

tdl keeps its session in a bolt database that only one process can open, so all
tdl runs inside Tondar take TDL_LOCK and Telegram downloads go one at a time.
"""
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile

from .config import BIN_DIR, DATA_DIR
from . import osutil

TDL_BASE = "https://github.com/iyear/tdl/releases/latest/download/"
STORE_DIR = DATA_DIR / "telegram"
NAMESPACE = "tondar"
TDL_LOCK = threading.Lock()
TDL_PATH = BIN_DIR / ("tdl.exe" if osutil.IS_WIN else "tdl")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class TelegramError(Exception):
    pass


# ----------------------------------------------------------------- the tool
def _asset():
    m = platform.machine().lower()
    arch = {"x86_64": "64bit", "amd64": "64bit", "aarch64": "arm64", "arm64": "arm64"}.get(m)
    if not arch:
        return None
    if osutil.IS_WIN:
        return f"tdl_Windows_{arch}.zip"
    if osutil.IS_MAC:
        return f"tdl_MacOS_{arch}.tar.gz"
    return f"tdl_Linux_{arch}.tar.gz"


def tdl_path():
    if TDL_PATH.exists():
        return str(TDL_PATH)
    return osutil.which("tdl")


def install_tdl(settings, log=print):
    """Download the latest tdl release. Raises on failure."""
    from .media import _fetch, _install_file
    asset = _asset()
    if not asset:
        raise TelegramError(f"tdl has no build for this computer ({platform.machine()})")
    log(f"Downloading {asset} ...")
    data = _fetch(TDL_BASE + asset, settings, timeout=300)
    want = TDL_PATH.name
    blob = None
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if os.path.basename(n) == want:
                    blob = z.read(n)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            for m in t.getmembers():
                if m.isfile() and os.path.basename(m.name) == want:
                    blob = t.extractfile(m).read()
    if not blob:
        raise TelegramError(f"{want} not found in {asset}")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    _install_file(blob, TDL_PATH)
    if osutil.IS_MAC:
        subprocess.run(["xattr", "-d", "com.apple.quarantine", str(TDL_PATH)], capture_output=True)
    log(f"Installed {TDL_PATH}")
    return str(TDL_PATH)


def tdl_version():
    exe = tdl_path()
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=30,
                             **osutil.subprocess_kwargs()).stdout
        m = re.search(r"Version:\s*(\S+)", ANSI_RE.sub("", out))
        return m.group(1) if m else ""
    except Exception:
        return ""


def proxy_of(settings):
    p = (settings.get("telegram_proxy") or "").strip()
    if not p and (settings.get("proxy") or "").startswith("socks5"):
        p = settings["proxy"]
    return p


def base_args(settings):
    exe = tdl_path()
    if not exe:
        raise TelegramError("tdl is not installed")
    args = [exe, "--storage", f"type=bolt,path={STORE_DIR / 'data'}", "-n", NAMESPACE,
            "--reconnect-timeout", "90s"]
    p = proxy_of(settings)
    if p:
        args += ["--proxy", p]
    return args


def has_session():
    """A login was saved (not a proof that Telegram still accepts it)."""
    d = STORE_DIR / "data"
    try:
        return d.is_dir() and any(f.stat().st_size > 0 for f in d.iterdir())
    except OSError:
        return False


def logout():
    """Forget the saved login. (The session stays listed in Telegram > Devices until ended there.)"""
    with TDL_LOCK:
        shutil.rmtree(STORE_DIR, ignore_errors=True)


def clean(text):
    return ANSI_RE.sub("", text or "").replace("\r", "\n")


def _error_line(out):
    lines = [l.strip() for l in clean(out).splitlines() if l.strip()]
    for l in reversed(lines):
        if l.lower().startswith("error") or "not authorized" in l:
            return re.sub(r"^error:\s*", "", l, flags=re.I)
    return lines[-1] if lines else ""


def _run(args, timeout, cancel=None):
    """Run tdl under the lock; returns (exit code, output)."""
    if not TDL_LOCK.acquire(timeout=3):
        raise TelegramError("Tondar is busy with another Telegram download - wait until it finishes "
                            "(or stop it) and try again.")
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", **osutil.subprocess_kwargs())
        out = []
        reader = threading.Thread(target=lambda: out.append(proc.stdout.read()), daemon=True)
        reader.start()
        t0 = time.monotonic()
        while proc.poll() is None:
            if (cancel and cancel()) or time.monotonic() - t0 > timeout:
                osutil.stop_process(proc)
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise TelegramError("Cancelled" if cancel and cancel() else
                                    "Telegram did not answer in time - check your internet connection "
                                    "or set a SOCKS5 proxy for Telegram.")
            time.sleep(0.2)
        reader.join(5)
        return proc.returncode, "".join(out)
    finally:
        TDL_LOCK.release()


def check_login(settings, cancel=None):
    """True if logged in; raises TelegramError with a readable reason otherwise."""
    if not has_session():
        return False
    rc, out = _run(base_args(settings) + ["chat", "ls", "-o", "json", "-f", "false"], 120, cancel)
    if "not authorized" in out:
        return False
    if rc != 0:
        raise TelegramError(_error_line(out) or f"tdl exit code {rc}")
    return True


# ------------------------------------------------------------------ login
def login_command(settings, mode):
    """mode: qr | code | desktop"""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    return base_args(settings) + ["login", "-T", mode]


def _posix_script(cmd):
    import shlex
    return (shlex.join(cmd) + "; echo; echo 'You can close this window and click \"Check login\" in Tondar.';"
            " read -r _")


def open_terminal(cmd, title="Tondar - Telegram login"):
    """Run an interactive command in a visible terminal window. Returns True if one was opened."""
    if osutil.IS_WIN:
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
        line = subprocess.list2cmdline(cmd)
        # a plain string goes to CreateProcess as is (a list would escape the inner quotes with \,
        # which cmd.exe doesn't understand); cmd /k strips only the outer pair of quotes
        subprocess.Popen(f'cmd.exe /k "title {title} & {line}"', creationflags=flags)
        return True
    script = _posix_script(cmd)
    if osutil.IS_MAC:
        esc = script.replace("\\", "\\\\").replace('"', '\\"')
        r = subprocess.run(["osascript", "-e", f'tell application "Terminal" to do script "{esc}"',
                            "-e", 'tell application "Terminal" to activate'], capture_output=True)
        return r.returncode == 0
    env = dict(os.environ)
    for k in ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH"):
        env.pop(k, None)
    sh = ["sh", "-c", script]
    candidates = [
        ["ptyxis", "--new-window", "--"] + sh,
        ["gnome-terminal", f"--title={title}", "--"] + sh,
        ["kgx", "--"] + sh,
        ["konsole", "-e"] + sh,
        ["xfce4-terminal", f"--title={title}", "-x"] + sh,
        ["mate-terminal", "-x"] + sh,
        ["tilix", "-e"] + sh,
        ["x-terminal-emulator", "-e"] + sh,
        ["xterm", "-T", title, "-e"] + sh,
    ]
    for c in candidates:
        if osutil.which(c[0]):
            try:
                subprocess.Popen(c, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return True
            except OSError:
                continue
    return False


# ------------------------------------------------------------- chats/files
LINK_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/(?:s/)?(.+)$", re.I)


def parse_chat(text):
    """'@name', 'name', 'https://t.me/name', 'https://t.me/name/123', 'https://t.me/c/123/45'
    -> (chat, message id or None). Raises ValueError."""
    t = (text or "").strip()
    if t.lower() in ("", "me", "self", "saved", "saved messages", "پیام‌های ذخیره‌شده", "پیام های ذخیره شده"):
        return "me", None
    m = LINK_RE.match(t)
    if m:
        parts = [p for p in m.group(1).split("?")[0].split("/") if p]
        if parts and parts[0] == "c" and len(parts) >= 2 and parts[1].isdigit():
            msg = next((int(p) for p in parts[2:][::-1] if p.isdigit()), None)
            return parts[1], msg
        if parts and parts[0] not in ("joinchat", "addstickers", "share") and not parts[0].startswith("+"):
            msg = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
            return parts[0], msg
        raise ValueError("Invite links can't be listed - join the chat in Telegram first, "
                         "then use its @name or a message link.")
    t = t.lstrip("@")
    if re.match(r"^-?\d+$", t) or re.match(r"^[A-Za-z][A-Za-z0-9_]{3,}$", t):
        return t, None
    raise ValueError("Enter a channel/group @name, a t.me link or a message link.")


def message_link(chat, chat_id, msg_id):
    if chat == "me":
        return f"tdl://saved/{msg_id}"          # Saved Messages have no t.me link
    if chat and not chat.lstrip("-").isdigit():
        return f"https://t.me/{chat}/{msg_id}"
    cid = str(chat_id or chat)
    cid = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return f"https://t.me/c/{cid}/{msg_id}"


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _media_facts(raw):
    """Size, MIME type, duration and resolution from a raw MTProto message (best effort)."""
    facts = {"size": -1, "mime": "", "duration": 0, "w": 0, "h": 0}
    if not isinstance(raw, dict):
        return facts
    media = raw.get("Media") or raw.get("media") or {}
    for d in _walk(media):
        keys = {k.lower(): k for k in d}
        if "mimetype" in keys and "size" in keys and facts["size"] < 0:
            facts["mime"] = str(d[keys["mimetype"]] or "")
            try:
                facts["size"] = int(d[keys["size"]])
            except (TypeError, ValueError):
                pass
        if "duration" in keys and not facts["duration"]:
            try:
                facts["duration"] = int(float(d[keys["duration"]]))
                facts["w"] = int(d.get(keys.get("w", ""), 0) or 0)
                facts["h"] = int(d.get(keys.get("h", ""), 0) or 0)
            except (TypeError, ValueError):
                pass
    if facts["size"] < 0:            # photos: the largest size
        sizes = [int(d[k]) for d in _walk(media) for k in d if k.lower() == "size"
                 and isinstance(d[k], (int, float))]
        if sizes:
            facts["size"] = max(sizes)
            facts["mime"] = facts["mime"] or "image/jpeg"
    return facts


def kind_of(name, mime):
    from .config import file_type
    return file_type(name, mime)


_GENERIC = re.compile(r"^(?:\d+|video|file|document|photo|audio|IMG|VID)?[\d_\- .()]*$", re.I)
_BAD = re.compile(r'[<>:"/\\|?*{}\x00-\x1f]')


def safe_name(name):
    name = _BAD.sub("_", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return name[:180] or "telegram"


def suggest_name(file_name, caption, mime, msg_id):
    base, ext = os.path.splitext(file_name or "")
    if not ext:
        ext = {"video/mp4": ".mp4", "video/x-matroska": ".mkv", "audio/mpeg": ".mp3",
               "audio/ogg": ".ogg", "image/jpeg": ".jpg"}.get(mime, "")
    if base and not _GENERIC.match(base):
        return safe_name(base) + ext
    lines = []
    for l in (caption or "").splitlines():       # e.g. series name / season / episode
        l = re.sub(r"[^\w\s\-.,()\[\]&+#'!]", " ", l, flags=re.U)      # drop emoji and quotes
        l = re.sub(r"\s+", " ", l).strip(" -.,")
        if re.search(r"\w", l) and not l.startswith(("http", "@")) and l not in lines:
            lines.append(l)
        if len(lines) == 3:
            break
    first = " - ".join(lines)[:120].strip(" -")
    return safe_name(f"{first} ({msg_id})" if first else f"telegram {msg_id}") + ext


def list_files(settings, chat_text, last=100, cancel=None):
    """Media messages of a chat. Returns (title, [entry...]); an entry has
    id, link, name, size, mime, kind, duration, w, h, caption, date."""
    chat, msg = parse_chat(chat_text)
    fd, out_json = tempfile.mkstemp(prefix="tondar-tg-", suffix=".json")
    os.close(fd)
    try:
        args = base_args(settings) + ["chat", "export", "-o", out_json, "--with-content", "--raw"]
        if chat != "me":                         # no -c: Saved Messages
            args += ["-c", chat]
        if msg:
            args += ["-T", "id", "-i", f"{msg},{msg}"]
        else:
            args += ["-T", "last", "-i", str(max(1, int(last)))]
        rc, out = _run(args, 600, cancel)
        if "not authorized" in out:
            raise TelegramError("Not logged in to Telegram.")
        try:
            with open(out_json, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        if rc != 0 or not isinstance(data, dict):
            raise TelegramError(_error_line(out) or f"tdl exit code {rc}")
    finally:
        try:
            os.remove(out_json)
        except OSError:
            pass
    chat_id = data.get("id")
    entries = []
    for m in data.get("messages") or []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        f = _media_facts(m.get("raw"))
        file_name = m.get("file") or ""
        caption = m.get("text") or ""
        entries.append({
            "id": m["id"], "chat_id": chat_id, "link": message_link(chat, chat_id, m["id"]),
            "name": suggest_name(file_name, caption, f["mime"], m["id"]),
            "file": file_name, "size": f["size"], "mime": f["mime"],
            "kind": kind_of(file_name, f["mime"]), "duration": f["duration"], "w": f["w"], "h": f["h"],
            "caption": caption, "date": m.get("date") or 0,
        })
    return chat, entries


# --------------------------------------------------------------- download
class TelegramDownloader:
    """Downloads one Telegram file with `tdl dl` (same interface as HttpDownloader).

    tdl writes <name>.tmp and renames it when done; progress is the .tmp file's size.
    tdl can't continue a half-downloaded file, so a stopped download starts that file again."""

    def __init__(self, item, settings, limiter, on_done):
        self.item = item
        self.settings = settings
        self.on_done = on_done
        self.proc = None
        self.thread = None
        self.stopped = False
        self.lock = threading.Lock()
        self.bytes = 0
        self.tail = []

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped = True
        osutil.stop_process(self.proc)

    def downloaded(self):
        with self.lock:
            return self.bytes

    def snapshot(self):
        return []

    def active_connections(self):
        return int(self.settings.get("telegram_threads") or 4) if self.proc and self.proc.poll() is None else 0

    def _watch(self, tmp):
        while self.proc is None or self.proc.poll() is None:
            time.sleep(0.7)
            try:
                n = os.path.getsize(tmp)
            except OSError:
                continue
            with self.lock:
                self.bytes = n if self.item.size <= 0 else min(n, self.item.size)

    def _run(self):
        it = self.item
        got_lock = False
        try:
            while not self.stopped:
                if TDL_LOCK.acquire(timeout=1):
                    got_lock = True
                    break
                it.error = "Waiting for the other Telegram download to finish"
            if self.stopped:
                self.on_done(self, "stopped", None)
                return
            it.error = ""
            os.makedirs(it.save_dir, exist_ok=True)
            final = os.path.join(it.save_dir, it.filename)
            tmp = final + ".tmp"
            threads = max(1, min(8, int(self.settings.get("telegram_threads") or 4)))
            src = ["-u", it.url]
            h = it.headers or {}
            if h.get("tg_chat") and h.get("tg_msg"):
                # an export-style list works for every chat, also Saved Messages and private chats
                fd, self.src_json = tempfile.mkstemp(prefix="tondar-tg-", suffix=".json")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"id": int(h["tg_chat"]), "messages": [
                        {"id": int(h["tg_msg"]), "type": "message", "file": it.filename}]}, f)
                src = ["-f", self.src_json]
            args = base_args(self.settings) + [
                "dl", *src, "-d", it.save_dir, "--template", it.filename,
                "--restart", "-l", "1", "-t", str(threads)]
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                         errors="replace", **osutil.subprocess_kwargs())
            threading.Thread(target=self._watch, args=(tmp,), daemon=True).start()
            for line in self.proc.stdout:
                for l in clean(line).splitlines():
                    l = l.strip()
                    if l and not re.match(r"^[\s\d.%/:|\-\[\]#=>MKGiB]*$", l):   # skip bare progress bars
                        self.tail = (self.tail + [l])[-20:]
            rc = self.proc.wait()
            if self.stopped:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                with self.lock:
                    self.bytes = 0
                self.on_done(self, "stopped", None)
            elif os.path.exists(final) and (it.size <= 0 or os.path.getsize(final) >= it.size):
                it.size = os.path.getsize(final)
                with self.lock:
                    self.bytes = it.size
                self.on_done(self, "completed", None)
            else:
                text = "\n".join(self.tail)
                if "not authorized" in text:
                    msg = "Not logged in to Telegram - open Tasks > Telegram... and log in"
                else:
                    msg = _error_line(text) or f"tdl exit code {rc}"
                self.on_done(self, "error", msg)
        except Exception as e:  # noqa: BLE001
            self.on_done(self, "error", str(e))
        finally:
            if getattr(self, "src_json", None):
                try:
                    os.remove(self.src_json)
                except OSError:
                    pass
            if got_lock:
                TDL_LOCK.release()
