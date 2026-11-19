"""Paths, settings and file categories."""
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from . import APP_ID, API_PORT

from . import osutil

CONFIG_DIR = osutil.config_dir(APP_ID)
DATA_DIR = osutil.data_dir(APP_ID)
BIN_DIR = DATA_DIR / "bin"
STATE_FILE = DATA_DIR / "downloads.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
SOCKET_PATH = "" if osutil.IS_WIN else os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"{APP_ID}-{os.getuid()}.sock")


def xdg_download_dir() -> Path:
    return osutil.download_dir()


# Category name -> list of extensions (lower case, no dot). Order matters for UI.
DEFAULT_CATEGORIES = {
    "Compressed": "zip rar 7z tar gz tgz bz2 xz zst iso img lz lzma cab arj z".split(),
    "Documents": "pdf doc docx xls xlsx ppt pptx odt ods odp txt rtf epub mobi djvu csv md".split(),
    "Music": "mp3 m4a aac flac wav ogg oga opus wma ape mka mid".split(),
    "Programs": "deb rpm appimage snap flatpak run sh bin exe msi apk dmg jar".split(),
    "Video": "mp4 mkv webm avi mov wmv flv m4v mpg mpeg 3gp ts m2ts vob ogv".split(),
}
GENERAL = "General"

DEFAULT_SETTINGS = {
    "max_connections": 8,            # per download (IDM default 8)
    "max_simultaneous": 3,           # downloads running at once in the main queue
    "speed_limit_kbps": 0,           # 0 = unlimited
    "speed_limit_enabled": False,
    "retries": 20,
    "timeout": 30,
    "user_agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
    "proxy": "",                      # e.g. http://127.0.0.1:8080 or socks5://127.0.0.1:1080
    "use_system_proxy": True,
    "download_dir": "",               # empty -> XDG download dir + /Tondar
    "use_category_folders": True,
    "show_file_info_dialog": True,    # "Download File Info" before start
    "show_progress_dialog": True,
    "show_complete_dialog": True,
    "monitor_clipboard": False,
    "api_port": API_PORT,
    "capture_extensions": sorted({e for v in DEFAULT_CATEGORIES.values() for e in v}),
    "capture_min_size_kb": 0,
    "media_panel_enabled": True,
    "ytdlp_cookies_browser": "",      # e.g. "chrome", "firefox" -> --cookies-from-browser
    "ytdlp_extra_args": "",
    "temp_dir": "",
    "close_to_tray": True,
    "theme": "auto",                  # auto | light | dark | classic
    "notifications": "all",           # all | errors | none  (desktop notifications)
    "categories": DEFAULT_CATEGORIES,
    "scheduler": {
        "enabled": False,
        "start_time": "02:00",
        "stop_time": "",
        "days": [0, 1, 2, 3, 4, 5, 6],   # Mon..Sun
        "on_finish": "nothing",            # nothing | quit | shutdown | suspend
    },
}


class Settings:
    def __init__(self):
        self._lock = threading.RLock()
        self.data = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.load()

    def load(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in saved.items():
                if isinstance(v, dict) and isinstance(self.data.get(k), dict) and k != "categories":
                    self.data[k].update(v)
                else:
                    self.data[k] = v
        except FileNotFoundError:
            pass
        except Exception as e:  # corrupt file - keep defaults
            print("settings load error:", e)

    def save(self):
        with self._lock:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SETTINGS_FILE)

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def get(self, k, default=None):
        return self.data.get(k, default)

    # ---- helpers -------------------------------------------------------
    def base_dir(self) -> Path:
        d = self.data.get("download_dir")
        return Path(d).expanduser() if d else xdg_download_dir() / "Tondar"

    def category_for(self, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        for cat, exts in self.data["categories"].items():
            if ext in exts:
                return cat
        return GENERAL

    def dir_for_category(self, cat: str) -> Path:
        base = self.base_dir()
        if self.data.get("use_category_folders") and cat != GENERAL:
            return base / cat
        return base

    def speed_limit_bytes(self) -> int:
        if self.data.get("speed_limit_enabled") and self.data.get("speed_limit_kbps", 0) > 0:
            return int(self.data["speed_limit_kbps"]) * 1024
        return 0


def find_tool(name: str):
    """Look for a helper binary in our private bin dir first, then PATH."""
    return osutil.find_tool(name, BIN_DIR)
