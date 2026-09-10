#!/bin/sh
# This script installs the payload on a WiFi Pineapple Pager.
#
# This script gets the pager control library and the fonts from the repository
# of brAinphreAk. This repository does not contain those files. The files are in
# an MIT repository. But an MIT licence does not give rights that the author did
# not have. Refer to CREDITS.md.
set -e

UPSTREAM="https://raw.githubusercontent.com/brainphreak/pineapple_pager_wardrive/main/payloads/user/reconnaissance/wardrive"
DEST="${DEST:-/root/payloads/user/reconnaissance/wardrivegotchi}"
SRC="$(cd "$(dirname "$0")" && pwd)"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ -d "$SRC/payload" ] || die "start this script from a copy of the repository"

# The source tree and the installed payload are different directories: the
# repository keeps gps-server/ and payload/ as separate trees and the install
# flattens them into DEST. Refuse to copy a tree onto itself.
if [ "$(cd "$SRC" && pwd)" = "$(cd "$DEST" 2>/dev/null && pwd)" ]; then
    die "clone the repository outside $DEST, then run install.sh from there"
fi

say "Install location: $DEST"
mkdir -p "$DEST" "$DEST/lib" "$DEST/fonts" "$DEST/images" "$DEST/mobile2gps"

# The files of this repository.
cp "$SRC"/payload/*.py "$SRC"/payload/payload.sh "$DEST/"
# A custom background is optional: the screens draw their own by default.
if ls "$SRC"/payload/images/*.png >/dev/null 2>&1; then
    cp "$SRC"/payload/images/*.png "$DEST/images/"
fi
chmod +x "$DEST/payload.sh"

# Avatar art. The Pager reads avatar_assets/lowres/ for the owl and worn items;
# without it the avatar just shows the placeholder. (The phone page has the art
# embedded, so it needs nothing here.)
if [ -d "$SRC/payload/avatar_assets" ]; then
    mkdir -p "$DEST/avatar_assets/lowres"
    cp "$SRC/payload/avatar_assets/manifest.json" "$DEST/avatar_assets/" 2>/dev/null || true
    if ls "$SRC"/payload/avatar_assets/lowres/*.png >/dev/null 2>&1; then
        cp "$SRC"/payload/avatar_assets/lowres/*.png "$DEST/avatar_assets/lowres/"
    fi
fi

# The page of the GPS server. The binary file is a build product. This
# repository does not contain it. Refer to the README.
cp "$SRC/gps-server/index.html" "$DEST/mobile2gps/"
if [ -f "$SRC/gps-server/mobile2gps" ]; then
    cp "$SRC/gps-server/mobile2gps" "$DEST/mobile2gps/"
    chmod +x "$DEST/mobile2gps/mobile2gps"
    say "The GPS server binary file is installed"
else
    say "NOTE: the file gps-server/mobile2gps is absent."
    say "      Build it with 'make -C gps-server build'. You can also download it."
    say "      Then copy it to $DEST/mobile2gps/ and make it executable."
fi

# Third-party files. This script gets them at installation.
fetch() {
    dest="$1"; url="$2"
    [ -f "$dest" ] && { say "  present: $(basename "$dest")"; return 0; }
    say "  get: $(basename "$dest")"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$dest" "$url" || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$dest" "$url" || return 1
    else
        die "neither curl nor wget is available"
    fi
}

say "Get the pager control library and the fonts from the source project"
missing=0
fetch "$DEST/lib/libpagerctl.so" "$UPSTREAM/lib/libpagerctl.so" || missing=1
fetch "$DEST/lib/pagerctl.py"    "$UPSTREAM/lib/pagerctl.py"    || missing=1
fetch "$DEST/fonts/title.TTF"    "$UPSTREAM/fonts/title.TTF"    || missing=1
fetch "$DEST/fonts/menu.ttf"     "$UPSTREAM/fonts/menu.ttf"     || missing=1

if [ "$missing" -ne 0 ]; then
    say ""
    say "The script cannot get some files. The Pager must have internet access."
    say "Set the Pager to Client Mode. You can also copy the files from:"
    say "  https://github.com/brainphreak/pineapple_pager_wardrive"
    exit 1
fi

# OpenWrt divides the Python standard library into separate packages. The Pager
# does not have all of them. The payload cannot import wardrive.py without
# urllib. An absent package looks the same as a program failure.
if ! python3 -c "import urllib.request, ssl, sqlite3, ctypes" 2>/dev/null; then
    say ""
    say "Some Python modules are absent. Install them:"
    say "  opkg update && opkg -d mmc install python3"
fi

say ""
say "The installation is complete. Start the Wardrivegotchi payload and push green."
