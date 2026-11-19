"""Everything that differs between Linux, Windows (10+) and macOS (12+)."""
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC
FROZEN = bool(getattr(sys, "frozen", False))          # PyInstaller build (Windows / macOS app)


# ------------------------------------------------------------------ folders
# TONDAR_HOME=<dir> keeps settings + data in one folder (portable use, self-test)
_HOME = os.environ.get("TONDAR_HOME")


def config_dir(app_id):
    if _HOME:
        return Path(_HOME) / "config"
    if IS_WIN:
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "Tondar"
    if IS_MAC:
        return Path.home() / "Library/Application Support/Tondar"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / app_id


def data_dir(app_id):
    if _HOME:
        return Path(_HOME) / "data"
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Tondar"
    if IS_MAC:
        return Path.home() / "Library/Application Support/Tondar"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / app_id


def download_dir():
    if IS_WIN:
        try:   # the user may have moved "Downloads" to another drive
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                return Path(winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0])
        except Exception:
            return Path.home() / "Downloads"
    if IS_MAC:
        return Path.home() / "Downloads"
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2).stdout.strip()
        if out and out != str(Path.home()):
            return Path(out)
    except Exception:
        pass
    return Path.home() / "Downloads"


# ------------------------------------------------------------------ tools
def exe(name):
    return name + ".exe" if IS_WIN else name


def _extra_path():
    # apps started from Finder/Dock do not get Homebrew's PATH
    return ["/opt/homebrew/bin", "/usr/local/bin"] if IS_MAC else []


def which(name):
    found = shutil.which(name)
    if found:
        return found
    for d in _extra_path():
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def bundled_bin_dir():
    """Helpers shipped inside the Windows/macOS build (ffmpeg)."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "bin" if base else None


def find_tool(name, bin_dir):
    """Our private copy first (bin_dir, bin_dir/ffmpeg, the app bundle), then the system."""
    dirs = [bin_dir, bin_dir / "ffmpeg"]
    if bundled_bin_dir():
        dirs.append(bundled_bin_dir())
    for d in dirs:
        p = d / exe(name)
        if p.exists() and (IS_WIN or os.access(p, os.X_OK)):
            return str(p)
    return which(name)


def subprocess_kwargs():
    """No console windows popping up on Windows; own process group elsewhere (clean stop)."""
    if IS_WIN:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {"start_new_session": True}


def stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if IS_WIN:      # kill yt-dlp and the ffmpeg it started
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           **subprocess_kwargs())
        else:
            os.killpg(proc.pid, signal.SIGINT)
    except Exception:
        proc.terminate()


# ------------------------------------------------------------------ desktop
def open_folder(path):
    """Show the file selected in Explorer / Finder / the Linux file manager. Returns True if done."""
    try:
        if IS_WIN:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return True
        if IS_MAC:
            subprocess.Popen(["open", "-R", path])
            return True
        from urllib.parse import quote
        uri = "file://" + quote(os.path.abspath(path))
        r = subprocess.run(["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                            "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                            f"array:string:{uri}", "string:"], capture_output=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


def power(action):
    """action: shutdown | suspend"""
    if IS_WIN:
        cmd = (["shutdown", "/s", "/t", "60"] if action == "shutdown"
               else ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    elif IS_MAC:
        cmd = (["osascript", "-e", 'tell application "System Events" to shut down'] if action == "shutdown"
               else ["pmset", "sleepnow"])
    else:
        cmd = ["systemctl", "poweroff" if action == "shutdown" else "suspend"]
    subprocess.Popen(cmd, **subprocess_kwargs())


def firefox_command():
    """How to start Firefox (for installing the signed add-on on Windows/macOS)."""
    if IS_MAC:
        for app in ("/Applications/Firefox.app", str(Path.home() / "Applications/Firefox.app")):
            if os.path.isdir(app):
                return ["open", "-a", app]
        return None
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                p = os.path.join(base, "Mozilla Firefox", "firefox.exe")
                if os.path.exists(p):
                    return [p]
        return None
    f = which("firefox")
    return [f] if f else None
