#!/bin/sh
# Tondar Download Manager installer for Ubuntu 22.04 - 26.04
#   curl -fsSL https://raw.githubusercontent.com/Afsharidevops/tondar-download-manager/main/install.sh | sh
set -eu

REPO="${TONDAR_REPO:-Afsharidevops/tondar-download-manager}"
URL="${TONDAR_DEB_URL:-https://github.com/$REPO/releases/latest/download/tondar_all.deb}"
API="https://api.github.com/repos/$REPO/releases/latest"

if ! command -v apt-get >/dev/null 2>&1; then
    echo "This installer needs an Ubuntu/Debian system (apt-get not found)." >&2
    exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    $SUDO apt-get update && $SUDO apt-get install -y curl
fi

# download URL FILE  (quietly fails with non-zero status)
download() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$2" "$1"
    else
        wget -q -O "$2" "$1"
    fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
chmod 755 "$TMP"                     # let apt's _apt user read the file
DEB="$TMP/tondar_all.deb"

echo "Downloading the latest Tondar Download Manager ..."
if ! download "$URL" "$DEB" 2>/dev/null; then
    # fall back to asking the GitHub API for the newest *_all.deb asset
    ASSET=""
    if download "$API" "$TMP/release.json"; then
        ASSET=$(grep -o '"browser_download_url": *"[^"]*_all\.deb"' "$TMP/release.json" \
                | head -n 1 | sed 's/.*"\(https:[^"]*\)"$/\1/')
    fi
    if [ -z "$ASSET" ]; then
        echo "No published release with a .deb was found." >&2
        echo "See https://github.com/$REPO/releases" >&2
        exit 1
    fi
    download "$ASSET" "$DEB"
fi
chmod 644 "$DEB"

echo "Installing (you may be asked for your password) ..."
$SUDO apt-get install -y "$DEB"

echo
echo "Done. Open 'Tondar Download Manager' from the applications menu, or run: tondar"
