#!/bin/sh
# Deploy the working tree to a WiFi Pineapple Pager over SSH.
#
# Pushes the payload, the phone page and the avatar art to the installed
# location in a single SSH connection (one auth prompt). It does NOT touch
# settings.json on the device (your Wigle keys and control token stay put), nor
# the third-party lib/ and fonts/ (install.sh fetches those once).
#
#   ./deploy.sh                     deploy to root@172.16.52.1
#   HOST=root@10.0.0.5 ./deploy.sh  deploy to another address
#   ./deploy.sh --binary            also push the built GPS-server binary
#
# After it finishes, restart the payload on the Pager (exit and press green) so
# Python re-imports the changed modules.
set -e

HOST="${HOST:-root@172.16.52.1}"
DEST="/mmc/root/payloads/user/reconnaissance/wardrivegotchi"
SRC="$(cd "$(dirname "$0")" && pwd)"

WITH_BINARY=0
for a in "$@"; do
    [ "$a" = "--binary" ] && WITH_BINARY=1
done

say() { printf '\033[36m%s\033[0m\n' "$*"; }
[ -d "$SRC/payload" ] || { echo "run this from the repository root" >&2; exit 1; }

# Stage the files in the on-device layout, then ship them in one tar stream.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/mobile2gps" "$TMP/avatar_assets/lowres"

cp "$SRC"/payload/*.py "$SRC"/payload/payload.sh "$TMP/"
cp "$SRC"/gps-server/index.html "$TMP/mobile2gps/"
cp "$SRC"/payload/avatar_assets/manifest.json "$TMP/avatar_assets/" 2>/dev/null || true
if ls "$SRC"/payload/avatar_assets/lowres/*.png >/dev/null 2>&1; then
    cp "$SRC"/payload/avatar_assets/lowres/*.png "$TMP/avatar_assets/lowres/"
fi
if [ "$WITH_BINARY" = 1 ]; then
    if [ -f "$SRC/gps-server/mobile2gps" ]; then
        cp "$SRC/gps-server/mobile2gps" "$TMP/mobile2gps/"
    else
        echo "  (no gps-server/mobile2gps - build it with 'make -C gps-server build')" >&2
    fi
fi

say "Deploying $(find "$TMP" -type f | wc -l | tr -d ' ') files to $HOST:$DEST"
tar czf - -C "$TMP" . | ssh "$HOST" "
    mkdir -p '$DEST' &&
    tar xzf - -C '$DEST' &&
    chmod +x '$DEST/payload.sh' 2>/dev/null;
    [ -f '$DEST/mobile2gps/mobile2gps' ] && chmod +x '$DEST/mobile2gps/mobile2gps';
    echo '  extracted on device'
"

say "Done - restart the payload on the Pager to pick up the changes."
say "(settings.json on the device was left untouched.)"
