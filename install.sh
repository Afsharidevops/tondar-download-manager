#!/bin/sh
# Tondar Download Manager installer for Ubuntu 22.04 - 26.04
#   curl -fsSL https://raw.githubusercontent.com/Afsharidevops/tondar-download-manager/main/install.sh | sh
set -eu

REPO="${TONDAR_REPO:-Afsharidevops/tondar-download-manager}"
URL="${TONDAR_DEB_URL:-https://github.com/$REPO/releases/latest/download/tondar_all.deb}"

if ! command -v apt-get >/dev/null 2>&1; then
    echo "This installer needs an Ubuntu/Debian system (apt-get not found)." >&2
    exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
chmod 755 "$TMP"                     # let apt's _apt user read the file

echo "Downloading the latest Tondar Download Manager ..."
if command -v curl >/dev/null 2>&1; then
    curl -fL --progress-bar -o "$TMP/tondar_all.deb" "$URL"
elif command -v wget >/dev/null 2>&1; then
    wget -q --show-progress -O "$TMP/tondar_all.deb" "$URL"
else
    $SUDO apt-get update && $SUDO apt-get install -y curl
    curl -fL --progress-bar -o "$TMP/tondar_all.deb" "$URL"
fi
chmod 644 "$TMP/tondar_all.deb"

echo "Installing (you may be asked for your password) ..."
$SUDO apt-get install -y "$TMP/tondar_all.deb"

echo
echo "Done. Open 'Tondar Download Manager' from the applications menu, or run: tondar"
