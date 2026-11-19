#!/usr/bin/python3
"""Add / remove the Tondar add-on in Firefox's system policy file.

/etc/firefox/policies/policies.json is read by every Firefox on Ubuntu:
the snap (default), the Mozilla .deb and tarball builds. The signed .xpi
is copied next to it because the snap can only read that folder.
Existing policies written by the admin or other software are preserved.
"""
import json
import os
import shutil
import sys

POLICY_DIR = "/etc/firefox/policies"
POLICY_FILE = os.path.join(POLICY_DIR, "policies.json")
XPI_SRC = "/usr/share/tondar/extension/tondar-firefox-signed.xpi"
XPI_DST = os.path.join(POLICY_DIR, "tondar-firefox.xpi")
ADDON_ID = "tondar@tondar-dm.local"


def load():
    try:
        with open(POLICY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"policies": {}}
    except ValueError:
        print(f"tondar: {POLICY_FILE} is not valid JSON, leaving it alone", file=sys.stderr)
        return None


def save(data):
    tmp = POLICY_FILE + ".tondar-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, POLICY_FILE)


def install():
    if not os.path.exists(XPI_SRC):
        return
    os.makedirs(POLICY_DIR, exist_ok=True)
    shutil.copyfile(XPI_SRC, XPI_DST)
    os.chmod(XPI_DST, 0o644)
    data = load()
    if data is None:
        return
    ext = data.setdefault("policies", {}).setdefault("ExtensionSettings", {})
    ext[ADDON_ID] = {
        "installation_mode": "normal_installed",
        "install_url": "file://" + XPI_DST,
    }
    save(data)


def remove():
    try:
        os.remove(XPI_DST)
    except FileNotFoundError:
        pass
    data = load()
    if not data:
        return
    pol = data.get("policies", {})
    ext = pol.get("ExtensionSettings", {})
    if ext.pop(ADDON_ID, None) is None:
        return
    if not ext:
        pol.pop("ExtensionSettings", None)
    if not pol:
        os.remove(POLICY_FILE)
        try:
            os.rmdir(POLICY_DIR)
        except OSError:
            pass
    else:
        save(data)


if __name__ == "__main__":
    {"install": install, "remove": remove}[sys.argv[1]]()
