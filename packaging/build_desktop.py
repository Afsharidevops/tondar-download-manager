"""Build the Windows installer / macOS disk image (also runs on Linux for testing the frozen app).

    python packaging/build_desktop.py            -> dist/Tondar(.app) + installer/dmg/zip

Windows: dist/Tondar-Setup-<ver>.exe (Inno Setup, Windows 10+) and a portable zip
macOS:   dist/Tondar-<ver>-macOS-<arch>.dmg (macOS 12+)
"""
import glob
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tondar import VERSION, APP_NAME  # noqa: E402

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
ARCH = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                  platform.machine())


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def icons():
    from tondar.qt import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841
    from tondar.ui import icons as ic
    d = os.path.join(BUILD, "icons")
    os.makedirs(d, exist_ok=True)
    for s in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        ic.pixmap("app", s).save(os.path.join(d, f"{s}.png"))
    if IS_WIN or not IS_MAC:
        from PIL import Image
        Image.open(os.path.join(d, "256.png")).save(
            os.path.join(d, "tondar.ico"), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    if IS_MAC:
        iconset = os.path.join(d, "tondar.iconset")
        os.makedirs(iconset, exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            shutil.copy(os.path.join(d, f"{s}.png"), os.path.join(iconset, f"icon_{s}x{s}.png"))
            shutil.copy(os.path.join(d, f"{s * 2}.png"), os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
        run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(d, "tondar.icns")])
    return os.path.join(d, "tondar.icns" if IS_MAC else "tondar.ico")


def extension():
    sys.path.insert(0, os.path.join(ROOT, "extension"))
    import build as extbuild
    out = os.path.join(BUILD, "extension")
    extbuild.build(out)
    signed = os.path.join(HERE, "firefox", "tondar-firefox-signed.xpi")
    if os.path.exists(signed):
        shutil.copy(signed, os.path.join(out, "tondar-firefox-signed.xpi"))
    return out


def ffmpeg():
    """A static ffmpeg for this OS/CPU, taken from the imageio-ffmpeg wheel."""
    import imageio_ffmpeg
    bins = glob.glob(os.path.join(os.path.dirname(imageio_ffmpeg.__file__), "binaries", "ffmpeg-*"))
    if not bins:
        raise SystemExit("imageio-ffmpeg wheel without ffmpeg binary")
    d = os.path.join(BUILD, "bin")
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "ffmpeg.exe" if IS_WIN else "ffmpeg")
    shutil.copy(bins[0], dst)
    os.chmod(dst, 0o755)
    return dst


def pyinstaller(icon, ext_dir, ffmpeg_path):
    sep = ";" if IS_WIN else ":"
    launcher = os.path.join(HERE, "tondar_launcher.py")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", "Tondar", "--icon", icon,
           "--distpath", DIST, "--workpath", os.path.join(BUILD, "pyinstaller"),
           "--specpath", os.path.join(BUILD, "pyinstaller"),
           "--paths", ROOT,
           "--add-data", f"{ext_dir}{sep}extension",
           "--add-binary", f"{ffmpeg_path}{sep}bin"]
    for mod in ("tondar.app", "tondar.ui.main_window", "tondar.ui.dialogs", "tondar.ui.theme",
                "tondar.selftest", "tondar.server", "tondar.manager", "tondar.media", "tondar.listio",
                "tondar.telegram", "tondar.ui.telegram_dialog",
                "truststore", "certifi", "socks", "sockshandler"):
        cmd += ["--hidden-import", mod]
    for mod in ("PyQt6.QtWebEngineCore", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtMultimedia",
                "PyQt6.QtBluetooth", "PyQt6.QtPdf", "PyQt6.Qt3DCore", "tkinter", "PyQt5"):
        cmd += ["--exclude-module", mod]
    if IS_MAC:
        cmd += ["--osx-bundle-identifier", "com.github.afsharidevops.tondar"]
    cmd.append(launcher)
    run(cmd)


def mac_bundle():
    app = os.path.join(DIST, "Tondar.app")
    pl = os.path.join(app, "Contents", "Info.plist")
    with open(pl, "rb") as f:
        info = plistlib.load(f)
    info.update({
        "CFBundleName": "Tondar", "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "12.0", "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Tondar Download Manager",
        "LSApplicationCategoryType": "public.app-category.utilities",
    })
    with open(pl, "wb") as f:
        plistlib.dump(info, f)
    # ad-hoc signature (required to run on Apple Silicon); no Apple Developer ID needed
    run(["codesign", "--force", "--deep", "--sign", "-", app])
    stage = os.path.join(BUILD, "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run(["ditto", app, os.path.join(stage, "Tondar.app")])
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    dmg = os.path.join(DIST, f"Tondar-{VERSION}-macOS-{'apple-silicon' if ARCH == 'arm64' else 'intel'}.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    run(["hdiutil", "create", "-volname", f"Tondar {VERSION}", "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
    return dmg


def windows_installer(icon):
    iscc = shutil.which("iscc") or next((p for p in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                                                     r"C:\Program Files\Inno Setup 6\ISCC.exe")
                                         if os.path.exists(p)), None)
    if not iscc:
        raise SystemExit("Inno Setup (iscc) not found")
    run([iscc, f"/DMyAppVersion={VERSION}", f"/DSrcDir={os.path.join(DIST, 'Tondar')}",
         f"/DIconFile={icon}", f"/DOutDir={DIST}", os.path.join(HERE, "windows", "tondar.iss")])
    # portable zip as well
    z = os.path.join(DIST, f"Tondar-{VERSION}-windows-portable.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        base = os.path.join(DIST, "Tondar")
        for d, _, files in os.walk(base):
            for fn in files:
                full = os.path.join(d, fn)
                zf.write(full, os.path.join("Tondar", os.path.relpath(full, base)))
    return os.path.join(DIST, f"Tondar-Setup-{VERSION}.exe")


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(DIST, exist_ok=True)
    icon = icons()
    ext = extension()
    ff = ffmpeg()
    pyinstaller(icon, ext, ff)
    if IS_MAC:
        print("built", mac_bundle())
    elif IS_WIN:
        print("built", windows_installer(icon))
    else:
        print("built", os.path.join(DIST, "Tondar"))


if __name__ == "__main__":
    main()
