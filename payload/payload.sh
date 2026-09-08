#!/bin/sh
# Title: Wardrivegotchi
# Description: Wardrivegotchi - wardriving with a levelling owl, phone GPS, handshake capture, Wigle upload
# Author: HexOffender
# Version: 2.2
# Category: Reconnaissance
# Library: libpagerctl.so (pagerctl)
#
# Based on pineapple_pager_wardrive by brAinphreAk (MIT) and mobile2gps by
# Ryan Pohlner (GPL-3.0). See CREDITS.md for full attribution.

_PAYLOAD_TITLE="Wardrivegotchi"
_PAYLOAD_AUTHOR_NAME="HexOffender"
_PAYLOAD_VERSION="2.2"
_PAYLOAD_DESCRIPTION="Wardrivegotchi - wardriving dashboard with a levelling owl"

# Where this payload is installed. It lives under its own name, so it never
# collides with the upstream 'wardrive' (pineapple_pager_wardrive) payload or a
# standalone 'mobile2gps' payload; all three can be installed side by side.
# The path is resolved from this script when possible, so the payload is
# relocatable, and falls back to the install location if the launcher sourced us
# and $0 is not our own path.
PAYLOAD_DIR="/root/payloads/user/reconnaissance/wardrivegotchi"
_self_dir="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
[ -n "$_self_dir" ] && [ -f "$_self_dir/wardrive.py" ] && PAYLOAD_DIR="$_self_dir"
DATA_DIR="$PAYLOAD_DIR/data"
GPS_BIN="$PAYLOAD_DIR/mobile2gps/mobile2gps"

cd "$PAYLOAD_DIR" || {
    LOG "red" "ERROR: $PAYLOAD_DIR not found"
    exit 1
}

# Setup pagerctl
PAGERCTL_FOUND=false
for dir in "$PAYLOAD_DIR/lib" "/mmc/root/payloads/user/reconnaissance/wardrivegotchi/lib"; do
    if [ -f "$dir/libpagerctl.so" ] && [ -f "$dir/pagerctl.py" ]; then
        PAGERCTL_DIR="$dir"
        PAGERCTL_FOUND=true
        break
    fi
done

if [ "$PAGERCTL_FOUND" = false ]; then
    LOG ""
    LOG "red" "=== MISSING DEPENDENCY ==="
    LOG "red" "libpagerctl.so / pagerctl.py not found!"
    LOG ""
    LOG "Press any button to exit..."
    WAIT_FOR_INPUT >/dev/null 2>&1
    exit 1
fi

# Environment
export PATH="/mmc/usr/bin:$PAYLOAD_DIR/bin:$PATH"
export PYTHONPATH="$PAYLOAD_DIR/lib:$PAYLOAD_DIR:$PYTHONPATH"
export LD_LIBRARY_PATH="/mmc/usr/lib:$PAYLOAD_DIR/lib:$LD_LIBRARY_PATH"

# Check and install missing Python modules
MISSING=""
python3 -c "import sqlite3" 2>/dev/null || MISSING="$MISSING python3-sqlite3"
python3 -c "import ctypes" 2>/dev/null || MISSING="$MISSING python3-ctypes"
if [ -n "$MISSING" ]; then
    LOG "Installing:$MISSING"
    opkg update 2>/dev/null
    for pkg in $MISSING; do
        opkg -d mmc install $pkg 2>/dev/null
    done
fi

# Check Python3
if ! command -v python3 >/dev/null 2>&1; then
    LOG "red" "Python3 not found"
    LOG "green" "GREEN = Install"
    LOG "red" "RED = Exit"
    while true; do
        BUTTON=$(WAIT_FOR_INPUT 2>/dev/null)
        case "$BUTTON" in
            "GREEN"|"A")
                LOG "Installing Python3..."
                opkg update 2>&1 | while IFS= read -r line; do LOG "  $line"; done
                opkg -d mmc install python3 python3-ctypes 2>&1 | while IFS= read -r line; do LOG "  $line"; done
                if command -v python3 >/dev/null 2>&1; then
                    LOG "green" "Python3 installed!"
                    sleep 1
                    break
                else
                    LOG "red" "Failed"
                    sleep 2
                    exit 1
                fi
                ;;
            "RED"|"B") exit 0 ;;
        esac
    done
fi

# Info screen
LOG ""
LOG "green" "Wardrivegotchi v$_PAYLOAD_VERSION"
LOG "cyan" "Wardriving Dashboard"
LOG ""
LOG "green" "GREEN = Start"
LOG "red" "RED = Exit"
LOG ""

while true; do
    BUTTON=$(WAIT_FOR_INPUT 2>/dev/null)
    case "$BUTTON" in
        "GREEN"|"A") break ;;
        "RED"|"B") LOG "Exiting."; exit 0 ;;
    esac
done

# Cleanup
cleanup() {
    # Only stop the GPS server if this payload started it - it is useful on its
    # own, and the user may have had it running beforehand.
    if [ -n "$GPS_SERVER_STARTED" ]; then
        killall mobile2gps 2>/dev/null
    fi
    if ! pgrep -x pineapple >/dev/null; then
        /etc/init.d/pineapplepager start 2>/dev/null
    fi
}
trap cleanup EXIT

# Loot directories - including our own namespace and a one-time migration from a
# legacy loot/wardrive directory - are created by wardrive.py at startup (see
# config.py), before the database is opened. Creating them here would pre-empt
# that migration, so we do not.

# Stop pager service
SPINNER_ID=$(START_SPINNER "Starting Wardrive...")
/etc/init.d/pineapplepager stop 2>/dev/null
sleep 0.5
STOP_SPINNER "$SPINNER_ID" 2>/dev/null

# Phone GPS. Started after the pager service stops, because stopping it brings
# the Pager's own device-less gpsd back - that instance holds port 2947 and
# never reports a fix, so the server has to claim the port after it, not before.
# mobile2gps keeps checking and takes the port back if it is displaced again.
GPS_SOURCE=$(python3 -c "import json;print(json.load(open('settings.json')).get('gps_source','phone'))" 2>/dev/null || echo phone)

# The web port the control panel is proxied to. The GPS server relays the
# phone's control calls here, because a browser will not let the HTTPS page call
# this plain-HTTP port directly.
WEB_PORT=$(python3 -c "import json;c=json.load(open('settings.json'));print(c.get('web_port',8080) if c.get('web_server',True) else '')" 2>/dev/null || echo 8080)
CONTROL_ARG=""
if [ -n "$WEB_PORT" ]; then
    CONTROL_ARG="-control-proxy http://127.0.0.1:$WEB_PORT"
fi

# Whether to run the phone server in serial GPS mode (as a dashboard only).
PHONE_DASH=$(python3 -c "import json;print('1' if json.load(open('settings.json')).get('phone_dashboard',False) else '')" 2>/dev/null || echo '')

# Decide whether and how to run the phone server.
#   phone GPS  -> full mode: it owns gpsd and feeds position.
#   serial GPS + phone_dashboard -> control-only mode: -no-gps, so it serves the
#     page and relays controls without touching the module's gpsd.
#   serial GPS, no dashboard -> do not run it.
GPS_MODE=""
if [ "$GPS_SOURCE" = "phone" ]; then
    GPS_MODE="full"
elif [ -n "$PHONE_DASH" ]; then
    GPS_MODE="dashboard"
fi

if [ -n "$GPS_MODE" ] && [ -x "$GPS_BIN" ]; then
    NOGPS_ARG=""
    [ "$GPS_MODE" = "dashboard" ] && NOGPS_ARG="-no-gps"

    if pgrep -x mobile2gps >/dev/null; then
        LOG "green" "Phone server already running"
    else
        LOG "Starting phone server..."
        ( cd "$PAYLOAD_DIR/mobile2gps" && ./mobile2gps $NOGPS_ARG $CONTROL_ARG > /tmp/mobile2gps.log 2>&1 & )
        GPS_SERVER_STARTED=1
        sleep 3
    fi

    if pgrep -x mobile2gps >/dev/null; then
        if [ "$GPS_MODE" = "full" ]; then
            LOG "cyan" "Open on your phone for GPS + dashboard, then tap Start:"
        else
            LOG "cyan" "Open on your phone for the dashboard:"
        fi
        "$GPS_BIN" -urls 2>/dev/null | while IFS= read -r url; do
            LOG "cyan" "  $url"
        done
        [ "$GPS_MODE" = "full" ] && LOG "yellow" "Keep the page open with NoSleep on."
    else
        LOG "red" "Phone server failed to start - see /tmp/mobile2gps.log"
    fi
    sleep 2
fi

# Run
python3 wardrive.py

exit 0
