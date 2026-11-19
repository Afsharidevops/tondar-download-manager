"""Build the Chrome (MV3 service worker) and Firefox (MV3 event page) extensions.

Usage: python3 extension/build.py   -> extension/build/{chrome,firefox}
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tondar import VERSION  # noqa: E402

BASE = {
    "manifest_version": 3,
    "name": "Tondar Download Manager integration",
    "short_name": "Tondar",
    "version": VERSION,
    "description": "Send downloads to Tondar Download Manager and grab videos/audio from web pages.",
    "permissions": ["downloads", "cookies", "storage", "contextMenus", "webRequest", "tabs"],
    "host_permissions": ["<all_urls>"],
    "action": {"default_popup": "popup.html", "default_title": "Tondar Download Manager",
               "default_icon": {"16": "icons/16.png", "32": "icons/32.png", "48": "icons/48.png"}},
    "icons": {"16": "icons/16.png", "32": "icons/32.png", "48": "icons/48.png", "128": "icons/128.png"},
    "content_scripts": [{
        "matches": ["http://*/*", "https://*/*"],
        "js": ["content.js"],
        "run_at": "document_idle",
        "all_frames": True,
    }],
}


def render_icons(dest):
    from tondar.qt import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841
    from tondar.ui import icons
    os.makedirs(dest, exist_ok=True)
    for s in (16, 32, 48, 128, 256):
        icons.pixmap("app", s).save(os.path.join(dest, f"{s}.png"))


def build(out_root=None):
    out_root = out_root or os.path.join(HERE, "build")
    shutil.rmtree(out_root, ignore_errors=True)
    for target in ("chrome", "firefox"):
        out = os.path.join(out_root, target)
        shutil.copytree(os.path.join(HERE, "src"), out)
        render_icons(os.path.join(out, "icons"))
        man = json.loads(json.dumps(BASE))
        if target == "chrome":
            man["background"] = {"service_worker": "background.js"}
            man["minimum_chrome_version"] = "110"
        else:
            man["background"] = {"scripts": ["background.js"]}
            man["browser_specific_settings"] = {"gecko": {"id": "tondar@tondar-dm.local",
                                                          "strict_min_version": "115.0"}}
        with open(os.path.join(out, "manifest.json"), "w") as f:
            json.dump(man, f, indent=2)
    print("built", out_root)
    return out_root


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else None)
