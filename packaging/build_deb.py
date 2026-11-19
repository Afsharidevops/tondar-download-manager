"""Build tondar_<ver>_all.deb (works on Ubuntu 22.04, 24.04, 25.x, 26.04)."""
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tondar import VERSION, APP_NAME  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist")
PKG = os.path.join(OUT, "pkgroot")

CONTROL = f"""Package: tondar
Version: {VERSION}
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyqt6 | python3-pyqt5, xdg-utils
Recommends: ffmpeg, python3-socks, xdg-user-dirs
Suggests: nodejs
Installed-Size: {{size}}
Maintainer: Tondar DM <tondar@localhost>
Homepage: https://github.com/
Description: {APP_NAME} - segmented download accelerator
 Download manager with up to 32 connections per file and dynamic
 segmentation, pause/resume, queue and scheduler, speed limiter,
 categories, browser integration (Chrome/Chromium/Brave/Edge/Firefox)
 and a "Download this video" panel for YouTube and other sites
 (powered by yt-dlp, downloaded on first use).
"""

DESKTOP = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
GenericName=Download Manager
Comment=Download files and videos faster
Exec=tondar %U
Icon=tondar
Terminal=false
Categories=Network;FileTransfer;
Keywords=download;accelerator;youtube;video;idm;
StartupWMClass=tondar
"""

AUTOSTART = DESKTOP.replace("Exec=tondar %U", "Exec=tondar --minimized") + \
    "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n"

LAUNCHER = """#!/bin/sh
export PYTHONPATH=/usr/lib/tondar${PYTHONPATH:+:$PYTHONPATH}
exec /usr/bin/python3 -m tondar "$@"
"""

POSTINST = """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi
exit 0
"""


def w(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


def main():
    shutil.rmtree(PKG, ignore_errors=True)
    # python package
    dst = f"{PKG}/usr/lib/tondar/tondar"
    shutil.copytree(os.path.join(ROOT, "tondar"), dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # extension
    sys.path.insert(0, os.path.join(ROOT, "extension"))
    import build as extbuild
    ext = extbuild.build(f"{PKG}/usr/share/tondar/extension")
    with zipfile.ZipFile(f"{ext}/tondar-firefox.xpi", "w", zipfile.ZIP_DEFLATED) as z:
        base = f"{ext}/firefox"
        for d, _, files in os.walk(base):
            for fn in files:
                full = os.path.join(d, fn)
                z.write(full, os.path.relpath(full, base))
    # icons
    from tondar.qt import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841
    from tondar.ui import icons
    for s in (16, 24, 32, 48, 64, 128, 256):
        d = f"{PKG}/usr/share/icons/hicolor/{s}x{s}/apps"
        os.makedirs(d, exist_ok=True)
        icons.pixmap("app", s).save(f"{d}/tondar.png")
    w(f"{PKG}/usr/bin/tondar", LAUNCHER, 0o755)
    w(f"{PKG}/usr/share/applications/tondar.desktop", DESKTOP)
    w(f"{PKG}/etc/xdg/autostart/tondar.desktop", AUTOSTART)
    w(f"{PKG}/usr/share/doc/tondar/README.md", open(os.path.join(ROOT, "README.md")).read())
    size = int(subprocess.check_output(["du", "-sk", f"{PKG}/usr"]).split()[0])
    w(f"{PKG}/DEBIAN/control", CONTROL.replace("{size}", str(size)))
    w(f"{PKG}/DEBIAN/postinst", POSTINST, 0o755)
    w(f"{PKG}/DEBIAN/postrm", POSTINST, 0o755)
    w(f"{PKG}/DEBIAN/conffiles", "/etc/xdg/autostart/tondar.desktop\n")
    for d, dirs, files in os.walk(PKG):
        for x in dirs:
            os.chmod(os.path.join(d, x), 0o755)
    deb = os.path.join(OUT, f"tondar_{VERSION}_all.deb")
    subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", PKG, deb], check=True)
    shutil.rmtree(PKG)
    print(deb)


if __name__ == "__main__":
    main()
