"""Settings persistence and constants for Wardrive."""

import json
import os

PAYLOAD_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(PAYLOAD_DIR, 'settings.json')
# Our own loot namespace. The upstream 'wardrive' payload writes to
# /mmc/root/loot/wardrive with a different database schema, so we keep ours
# separate and the two can coexist. _resolve_loot_dir migrates a legacy
# loot/wardrive directory here once; if that move ever fails it keeps using the
# legacy directory, so an existing database is never left behind for an empty one.
LEGACY_LOOT_DIR = '/mmc/root/loot/wardrive'
PREFERRED_LOOT_DIR = '/mmc/root/loot/wardrivegotchi'


def _resolve_loot_dir():
    if os.path.isdir(PREFERRED_LOOT_DIR):
        return PREFERRED_LOOT_DIR
    if os.path.isdir(LEGACY_LOOT_DIR):
        try:
            os.rename(LEGACY_LOOT_DIR, PREFERRED_LOOT_DIR)
            return PREFERRED_LOOT_DIR
        except Exception:
            return LEGACY_LOOT_DIR
    return PREFERRED_LOOT_DIR


LOOT_DIR = _resolve_loot_dir()
DB_PATH = os.path.join(LOOT_DIR, 'wardrive.db')
CAPTURE_DIR = os.path.join(LOOT_DIR, 'captures')
EXPORT_DIR = os.path.join(LOOT_DIR, 'exports')

# Screen
SCREEN_W = 480
SCREEN_H = 222

# Fonts
FONT_TITLE = os.path.join(PAYLOAD_DIR, 'fonts', 'title.TTF')
FONT_MENU = os.path.join(PAYLOAD_DIR, 'fonts', 'menu.ttf')

# Images
BG_IMAGE = os.path.join(PAYLOAD_DIR, 'images', 'wardriving_bg.png')

# WiFi channels by band
CHANNELS_2_4 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
CHANNELS_5 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 149, 153, 157, 161, 165]
CHANNELS_6 = [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65, 69, 73, 77, 81, 85, 89, 93]

# The channels most access points sit on: 2.4 GHz 1/6/11 (the non-overlapping
# ones) and the common 5 GHz channels. The passive scanner dwells on these more
# than the rest (scanner._build_hop_order), so a sweep spends its time where the
# networks are. Only those also enabled for the scan are used.
PRIORITY_CHANNELS = [1, 6, 11, 36, 40, 44, 48, 149, 153, 157, 161]

# Bundled phone GPS server (mobile2gps). It serves an HTTPS page the phone
# opens; the browser's location becomes NMEA and is fed to gpsd, so no GPS
# hardware is needed. HTTPS is not optional here - the Geolocation API refuses
# to run outside a secure context.
GPS_SERVER_DIR = os.path.join(PAYLOAD_DIR, 'mobile2gps')
GPS_SERVER_BIN = os.path.join(GPS_SERVER_DIR, 'mobile2gps')
GPS_SERVER_LOG = '/tmp/mobile2gps.log'

DEFAULTS = {
    'gps_enabled': True,
    # 'phone' uses the bundled mobile2gps server, 'serial' a USB/serial GPS.
    'gps_source': 'phone',
    'gps_device': '',  # Auto-detected on first run (serial only)
    'gps_baud': 'auto',
    'scan_2_4ghz': True,
    'scan_5ghz': True,
    'scan_6ghz': False,
    'scan_mode': 'stealth',  # 'stealth' (passive, all bands) or 'active' (iw scan, 2.4GHz only w/o dongle)
    'hop_speed': 0.3,  # seconds dwelt per channel in stealth mode (lower sweeps faster)
    'hop_priority_weight': 2,  # extra visits to the busy channels per other channel
    'capture_enabled': False,
    'scan_interface': 'wlan0',
    'capture_interface': 'wlan1mon',
    # Second monitor-mode radio for parallel 5 GHz scanning (e.g. a USB adapter
    # as wlan2mon). Leave EMPTY to auto-detect it: if a second monitor interface
    # is present, the internal radio scans 2.4 GHz and the second scans 5 GHz in
    # parallel; with none present, the internal radio scans alone. Set a name to
    # force a specific interface. Ignored in active scan mode.
    'capture_interface_5ghz': '',
    'wigle_api_name': '',
    'wigle_api_token': '',
    'scan_interval': 5,
    'geiger_sound': True,
    'brightness': 80,
    'screen_timeout': 60,  # seconds, 0 = never
    # Backlight level when the screen times out. NEVER 0 - some Pager panels
    # read 0 as full brightness; 1 is the dimmest that still means "off".
    'screen_off_brightness': 1,
    'web_server': True,
    'web_port': 8080,
    # Phone control. Empty disables it, thus a fresh install accepts no remote
    # commands. Set a shared token here and enter the same token on the phone
    # page to turn the controls on. Refer to the README.
    'control_token': '',
    # In serial GPS mode, run the phone server anyway as a control dashboard
    # (without touching gpsd, so it does not fight the GPS module). No effect in
    # phone GPS mode, where the server always runs.
    'phone_dashboard': False,
    # Draw the Pager avatar from pre-rendered PNG layers (avatar_assets/lowres).
    # If layered transparency does not composite right on your unit, set this
    # false to use the built-in grid renderer, which looks identical.
    'pager_avatar_png': True,

    # Data quality.
    # gps_stale_secs: if no fresh position arrives from the phone within this
    # many seconds, treat the fix as lost, so access points are not tagged
    # against a frozen position (they are stored at 0,0 and back-filled when a
    # fix returns). 0 disables the check.
    'gps_stale_secs': 8,
    # gpx_*: log the drive route to a GPX track in the exports directory.
    'gpx_enabled': True,
    'gpx_min_move_m': 8.0,
    # gps_average_positions: store each access point's position as the
    # RSSI-weighted average of its sightings instead of the single strongest.
    'gps_average_positions': False,
}


def load_config():
    """Load settings from disk, with defaults for missing keys."""
    config = dict(DEFAULTS)
    if os.path.isfile(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
            config.update(saved)
        except Exception:
            pass
    return config


def save_config(config):
    """Save settings to disk atomically, so a crash or power loss mid-write
    cannot truncate settings.json - which would lose the Wigle keys and the
    control token on the next load."""
    tmp = SETTINGS_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


def ensure_dirs():
    """Create loot directories if they don't exist."""
    for d in [LOOT_DIR, CAPTURE_DIR, EXPORT_DIR]:
        os.makedirs(d, exist_ok=True)
