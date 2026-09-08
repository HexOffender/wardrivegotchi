#!/usr/bin/env python3
"""Wardrive — Wardriving dashboard for WiFi Pineapple Pager."""

import os
import subprocess
import json
import glob

import blocks
import palette
import sys
import time
import queue
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pagerctl import Pager
from config import (load_config, save_config, ensure_dirs, DB_PATH, EXPORT_DIR,
                    CHANNELS_2_4, CHANNELS_5, CHANNELS_6, PRIORITY_CHANNELS)
from database import Database
from scanner import Scanner, PassiveScanner, detect_second_monitor
from gps_module import GpsReader, GpsState
from capture import Capture
from dashboard import Dashboard
from settings_menu import SettingsMenu
from wigle_export import export_csv, upload_to_wigle, WigleWriter
from gpx_logger import GpxWriter
from web_server import WebServer
from control import ControlChannel
from player import Player
import profile_ui


# The main loop runs many times a second. Counting the whole database, re-running
# the hidden-BSSID correlation and republishing the phone snapshot on every frame
# is what makes the dashboard and menus lag as the database grows. These refresh
# on a short interval instead, which is indistinguishable to the eye.
STATS_INTERVAL = 1.5
CORRELATE_INTERVAL = 5.0
PUBLISH_INTERVAL = 1.0
# Dashboard processing/redraw cadence. Input is polled far more often than this
# (see run()), so a slower redraw does not hurt responsiveness - it helps it.
PROCESS_INTERVAL = 0.2

# Recent access points sent to the phone for its radar and network list. Capped
# and cached so the status snapshot stays small and the database is not queried
# on every publish.
RECENT_APS_LIMIT = 150
RECENT_APS_INTERVAL = 4.0


class Wardrive:
    def __init__(self):
        self.config = load_config()
        ensure_dirs()

        # Pager display
        self.pager = Pager()
        self.pager.init()
        self.pager.set_rotation(270)
        try:
            self.pager.set_brightness(self.config.get('brightness', 80))
        except Exception:
            pass

        # Database
        self.db = Database(DB_PATH, average_positions=self.config.get('gps_average_positions', False))

        # Shared state
        self.gps_state = GpsState(stale_secs=self.config.get('gps_stale_secs', 8))
        self.stop_event = threading.Event()
        self.scan_queue = queue.Queue()
        self.capture_queue = queue.Queue()

        # Threads (created on start)
        self.scanners = []
        self.gps_reader = None
        self.capture_thread = None

        # UI
        self.dashboard = Dashboard(self.pager)
        self.start_time = time.time()
        self.last_scan_time = ""
        self.current_channel = 0
        self.new_ap_count = 0  # New APs in last scan (for geiger sound)
        self.scan_state = 'stopped'  # 'scanning', 'paused', 'stopped'
        self.paused_elapsed = 0  # Accumulated time before pause
        self.wigle_writer = WigleWriter(EXPORT_DIR)
        self.gpx_writer = GpxWriter(EXPORT_DIR, min_move_m=self.config.get('gpx_min_move_m', 8.0))

        # Screen timeout
        self.last_activity = time.time()
        self.screen_off = False

        # Web server for downloading loot
        # The phone control channel. It is enabled only when control_token is
        # set, thus a fresh install accepts no remote commands.
        self.control = ControlChannel(self.config.get('control_token', ''))
        self._last_command_message = ''

        # Caches so the main loop does not query the database on every frame.
        self._stats_cache = None
        self._stats_at = 0.0
        self._correlate_at = 0.0
        self._publish_at = 0.0
        self._recent_aps_cache = None
        self._recent_aps_at = 0.0

        from config import LOOT_DIR
        self.player = Player.load(os.path.join(LOOT_DIR, 'player.json'))
        self.player.seed_from_stats(self.db.get_stats())

        self.web_server = None
        if self.config.get('web_server', True):
            self.web_server = WebServer(port=self.config.get('web_port', 8080),
                                        control=self.control)
            self.web_server.start()

    def _get_channels(self):
        """Build channel list from config."""
        channels = []
        if self.config['scan_2_4ghz']:
            channels.extend(CHANNELS_2_4)
        if self.config['scan_5ghz']:
            channels.extend(CHANNELS_5)
        if self.config['scan_6ghz']:
            channels.extend(CHANNELS_6)
        return channels or CHANNELS_2_4

    def _band_channels(self, two_four=False, five=False, six=False):
        """Channels for the requested bands (only those enabled in settings)."""
        chans = []
        if two_four and self.config['scan_2_4ghz']:
            chans.extend(CHANNELS_2_4)
        if five and self.config['scan_5ghz']:
            chans.extend(CHANNELS_5)
        if six and self.config['scan_6ghz']:
            chans.extend(CHANNELS_6)
        return chans

    def _add_passive(self, interface, channels):
        """Queue a passive scanner on one monitor interface."""
        self.scanners.append(PassiveScanner(
            interface, channels,
            self.config.get('hop_speed', 0.3),
            self.scan_queue, self.stop_event,
            priority=PRIORITY_CHANNELS,
            priority_weight=self.config.get('hop_priority_weight', 2),
        ))

    def _start_passive_scanners(self):
        """Build the passive scanner(s). With a second monitor radio present, the
        internal radio scans 2.4 GHz (and 6 GHz if enabled) while the second one
        scans 5 GHz, in parallel - both feed the same queue and the database
        de-dupes by BSSID. Falls back to one radio when the second is not
        configured or not plugged in."""
        mon = self.config['capture_interface']
        # Use the configured second radio, or auto-detect one (a USB adapter in
        # monitor mode, e.g. wlan2mon). No configuration needed: plug it in and
        # it is used; with none present, scanning uses the internal radio alone.
        mon5 = self.config.get('capture_interface_5ghz', '') or detect_second_monitor(mon)
        have_mon5 = bool(mon5) and os.path.exists('/sys/class/net/' + mon5)
        if have_mon5 and self.config['scan_5ghz'] and CHANNELS_5:
            self._add_passive(mon, self._band_channels(two_four=True, six=True)
                              or list(CHANNELS_2_4))
            self._add_passive(mon5, list(CHANNELS_5))
        else:
            self._add_passive(mon, self._get_channels())

    def _start_threads(self):
        """Start scanner, GPS, and capture threads."""
        # Scanner(s). Active mode uses the managed interface; stealth uses the
        # monitor radio(s) - two in parallel when a second one is configured.
        self.scanners = []
        if self.config.get('scan_mode', 'active') == 'stealth':
            self._start_passive_scanners()
        else:
            self.scanners.append(Scanner(
                self.config['scan_interface'],
                self._get_channels(),
                self.config['scan_interval'],
                self.scan_queue,
                self.stop_event,
            ))
        for scanner in self.scanners:
            scanner.start()

        # GPS — with the phone server the device is a pty it owns, so there is
        # nothing to detect. Serial mode still auto-detects a USB receiver.
        if self.config['gps_enabled']:
            phone_gps = self.config.get('gps_source', 'phone') == 'phone'
            gps_dev = self.config.get('gps_device', '')
            if not phone_gps and (not gps_dev or not os.path.exists(gps_dev)):
                gps_dev = self._auto_detect_gps()
                if gps_dev:
                    self.config['gps_device'] = gps_dev
                    save_config(self.config)
            self.gps_reader = GpsReader(
                gps_dev or '/dev/ttyACM0',
                self.config['gps_baud'],
                self.gps_state,
                self.stop_event,
                phone_gps=phone_gps
            )
            self.gps_reader.start()

        # Capture — uses monitor interface (for handshakes)
        if self.config['capture_enabled']:
            from config import CAPTURE_DIR
            self.capture_thread = Capture(
                self.config['capture_interface'],
                CAPTURE_DIR,
                self.capture_queue,
                self.stop_event
            )
            self.capture_thread.start()

    def _stop_threads(self):
        """Stop all background threads."""
        self.stop_event.set()
        for scanner in self.scanners:
            scanner.join(timeout=3)
        if self.gps_reader:
            self.gps_reader.stop()
            self.gps_reader.join(timeout=3)
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread.join(timeout=3)

    def _process_scan_results(self):
        """Drain scan queue and update database."""
        new_count = 0
        gps = self.gps_state.copy()

        while not self.scan_queue.empty():
            try:
                aps = self.scan_queue.get_nowait()
            except queue.Empty:
                break

            fresh = []
            for ap in aps:
                if self.db.upsert_ap(ap, gps):
                    fresh.append(ap)
                if ap.get('channel'):
                    self.current_channel = ap['channel']
            new_count += len(fresh)
            reached = self.player.award_aps(fresh)
            if reached:
                self._announce_level(reached)

        self.new_ap_count = new_count
        return new_count

    def _process_captures(self):
        """Drain capture queue and mark handshakes."""
        while not self.capture_queue.empty():
            try:
                bssid = self.capture_queue.get_nowait()
                if self.db.mark_handshake(bssid):
                    reached = self.player.award_handshake()
                    if reached:
                        self._announce_level(reached)
                # Handshake captured sound — distinct from geiger
                self._handshake_sound()
            except queue.Empty:
                break

    def _handshake_sound(self):
        """Play a distinct sound when a handshake is captured."""
        if not self.config.get('geiger_sound', True):
            return
        try:
            # Rising tone — clearly different from geiger clicks
            for freq in [800, 1000, 1200, 1500]:
                self.pager.beep(freq, 50)
                time.sleep(0.05)
        except Exception:
            pass

    def _show_scan_menu(self):
        """Show scan control popup with pause/stop/resume."""
        from config import SCREEN_W, SCREEN_H, FONT_TITLE, FONT_MENU
        selected = 0

        while True:
            # Build menu items based on current state
            if self.scan_state == 'scanning':
                items = ["Pause Scan", "Stop Scan", "Cancel"]
                status = "Scanning"
            elif self.scan_state == 'paused':
                items = ["Resume Scan", "Stop Scan", "Cancel"]
                status = "Paused"
            else:
                items = ["Start Scan", "Cancel"]
                status = "Stopped"

            if selected >= len(items):
                selected = 0

            # Draw
            blocks.background(self.pager, self.dashboard.bg_image)

            title_color = palette.rgb(self.pager, palette.ACCENT)
            unsel_color = palette.rgb(self.pager, palette.INK)

            tw = self.pager.ttf_width(status, FONT_TITLE, 28)
            self.pager.draw_ttf((SCREEN_W - tw) // 2, 40, status, title_color, FONT_TITLE, 28)

            for i, item in enumerate(items):
                y = 85 + i * 24
                if i == selected:
                    # A filled block, not a colour. Refer to blocks.py.
                    blocks.centered_button(self.pager, SCREEN_W, y, item, FONT_MENU, 18)
                else:
                    tw = self.pager.ttf_width(item, FONT_MENU, 18)
                    self.pager.draw_ttf((SCREEN_W - tw) // 2, y, item, unsel_color, FONT_MENU, 18)

            self.pager.flip()

            button = self.pager.wait_button()
            if button & self.pager.BTN_UP:
                selected = (selected - 1) % len(items)
            elif button & self.pager.BTN_DOWN:
                selected = (selected + 1) % len(items)
            elif button & self.pager.BTN_A:
                action = items[selected]
                if action == "Pause Scan":
                    self._scan_pause()
                    return
                elif action == "Resume Scan":
                    self._scan_resume()
                    return
                elif action == "Stop Scan":
                    self._scan_stop()
                    return
                elif action == "Start Scan":
                    self._scan_start()
                    return
                elif action == "Cancel":
                    return
            elif button & self.pager.BTN_B:
                return

    def _auto_detect_gps(self):
        """Auto-detect GPS device by excluding known internal devices."""
        import glob as _glob
        exclude = ['uart', 'jtag', 'spi', 'i2c', 'debug', 'ehci', 'hub',
                   'wireless_device', 'csr8510', 'bluetooth']
        for pattern in ['/dev/ttyACM*', '/dev/ttyUSB*']:
            for dev in sorted(_glob.glob(pattern)):
                try:
                    dev_name = os.path.basename(dev)
                    d = os.path.realpath(f'/sys/class/tty/{dev_name}/device')
                    for _ in range(5):
                        d = os.path.dirname(d)
                        pf = os.path.join(d, 'product')
                        if os.path.isfile(pf):
                            product = open(pf).read().strip().lower()
                            if not any(kw in product for kw in exclude):
                                return dev
                            break
                except Exception:
                    pass
        return None

    # The battery level changes slowly, thus a frame does not need a fresh
    # reading. Before this, every frame read sysfs, and a device without that
    # entry ran ubus through subprocess with a two-second timeout on each frame.
    _BATTERY_INTERVAL = 30.0

    def _get_battery(self):
        """Read the battery level as a percentage, or None.

        The value is cached. If a method fails, this does not try it again.
        """
        now = time.time()
        if now - getattr(self, '_battery_read_at', 0) < self._BATTERY_INTERVAL:
            return getattr(self, '_battery_value', None)

        self._battery_read_at = now
        self._battery_value = self._read_battery()
        return self._battery_value

    def _read_battery(self):
        """Read the battery level from the system."""
        if getattr(self, '_battery_sysfs', True):
            try:
                for path in glob.glob('/sys/class/power_supply/*/capacity'):
                    with open(path, 'r') as f:
                        return int(f.read().strip())
                self._battery_sysfs = False
            except Exception:
                self._battery_sysfs = False

        if getattr(self, '_battery_ubus', True):
            try:
                result = subprocess.run(['ubus', 'call', 'battery', 'info'],
                                        capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    return int(data.get('percent', data.get('capacity', -1)))
                self._battery_ubus = False
            except Exception:
                self._battery_ubus = False

        return None

    def _geiger_sound(self, new_count):
        """Play geiger counter clicks based on new AP count."""
        if not self.config.get('geiger_sound', True):
            return
        if new_count <= 0:
            return

        # More new APs = more rapid clicks
        clicks = min(new_count, 10)  # Cap at 10 clicks
        for i in range(clicks):
            try:
                freq = 600 + (i * 50)  # Slightly varying pitch
                self.pager.beep(freq, 15)  # Very short click
                time.sleep(0.05)
            except Exception:
                break

    # Scan transitions. The Pager menu and the phone control both call these,
    # so a change to how a scan starts or stops happens in one place.

    def _beep(self, freq, duration):
        try:
            self.pager.beep(freq, duration)
        except Exception:
            pass

    def _scan_start(self):
        """Start a fresh scan and a fresh Wigle session."""
        self.scan_state = 'scanning'
        self.wigle_writer.start_session()
        self.stop_event.clear()
        self._start_threads()
        self.start_time = time.time()
        self.paused_elapsed = 0
        self._stats_cache = None
        self._beep(1000, 200)

    def _scan_pause(self):
        """Pause a running scan and freeze the timer."""
        if self.scan_state != 'scanning':
            return
        self.scan_state = 'paused'
        self.paused_elapsed += int(time.time() - self.start_time)
        self._stop_threads()
        self._beep(600, 150)

    def _scan_resume(self):
        """Resume a paused scan and the timer."""
        if self.scan_state != 'paused':
            return
        self.scan_state = 'scanning'
        self.start_time = time.time()
        self.stop_event.clear()
        self._start_threads()
        self._beep(1000, 150)

    def _scan_stop(self):
        """Stop the scan and archive the session."""
        if self.scan_state == 'stopped':
            return
        self.scan_state = 'stopped'
        self._stop_threads()
        self.player.note_session_aps(self.db.get_stats().get('total', 0))
        self._archive_session()
        self.start_time = time.time()
        self.paused_elapsed = 0
        self._stats_cache = None
        self._recent_aps_cache = None
        self.gpx_writer.close()
        self._beep(400, 200)

    def _announce_level(self, level):
        """Mark a level-up: a message for the phone and a rising beep."""
        self._last_command_message = 'Level %d!' % level
        self._beep(1200, 120)

    def _apply_command(self, cmd):
        """Run one command from the phone control. Called on the main thread."""
        action = cmd.get('action')
        if action == 'start':
            self._scan_start()
        elif action == 'pause':
            self._scan_pause()
        elif action == 'resume':
            self._scan_resume()
        elif action == 'stop':
            self._scan_stop()
        elif action == 'buy':
            ok, msg = self.player.buy(cmd.get('params', {}).get('item_id', ''))
            self._last_command_message = msg
        elif action == 'equip':
            ok, msg = self.player.equip(cmd.get('params', {}).get('item_id', ''))
            self._last_command_message = msg
        elif action == 'unequip':
            ok, msg = self.player.unequip(cmd.get('params', {}).get('item_id', '')
                                          or cmd.get('params', {}).get('slot', ''))
            self._last_command_message = msg
        elif action == 'set_bands':
            params = cmd.get('params', {})
            for key, cfg_key in (('b24', 'scan_2_4ghz'),
                                 ('b5', 'scan_5ghz'),
                                 ('b6', 'scan_6ghz')):
                if key in params:
                    self.config[cfg_key] = bool(params[key])
            save_config(self.config)
        elif action in ('export', 'upload'):
            # These read files and, for upload, reach the network. Run them off
            # the main loop so the dashboard and the GPS feed do not stall.
            target = self._export_callback if action == 'export' else self._upload_callback
            threading.Thread(target=self._run_reported, args=(target,), daemon=True).start()

    def _run_reported(self, fn):
        """Run a callback and store its message for the status snapshot."""
        try:
            self._last_command_message = fn()
        except Exception as e:
            self._last_command_message = str(e)

    def _get_stats_cached(self, force=False):
        """Database stats, refreshed at most every STATS_INTERVAL (or at once
        when forced), so a growing database does not slow the main loop."""
        now = time.time()
        if force or self._stats_cache is None or now - self._stats_at > STATS_INTERVAL:
            self._stats_cache = self.db.get_stats()
            self._stats_at = now
        return self._stats_cache

    def _recent_aps_cached(self):
        """Recent APs for the phone radar/list, refreshed on an interval so the
        publish path does not query the database every time."""
        now = time.time()
        if (self._recent_aps_cache is None
                or now - self._recent_aps_at > RECENT_APS_INTERVAL):
            self._recent_aps_cache = self.db.get_recent_aps(RECENT_APS_LIMIT)
            self._recent_aps_at = now
        return self._recent_aps_cache

    def _control_status(self, stats, gps, elapsed):
        """Build the status snapshot the phone control reads."""
        return {
            'scan_state': self.scan_state,
            'elapsed': elapsed,
            'channel': self.current_channel,
            'total': stats.get('total', 0),
            'open': stats.get('open', 0),
            'wpa': stats.get('wpa', 0),
            'wpa3': stats.get('wpa3', 0),
            'handshakes': stats.get('handshakes', 0),
            'gps_fix': bool(gps and gps.fix_mode >= 2),
            'lat': round(gps.lat, 6) if gps else 0.0,
            'lon': round(gps.lon, 6) if gps else 0.0,
            'sats': gps.satellites if gps else 0,
            'bands': {'b24': self.config['scan_2_4ghz'],
                      'b5': self.config['scan_5ghz'],
                      'b6': self.config['scan_6ghz']},
            'message': getattr(self, '_last_command_message', ''),
            'player': self.player.snapshot(stats),
            'gps_source': self.config.get('gps_source', 'phone'),
            'recent_aps': self._recent_aps_cached(),
        }

    def _export_callback(self):
        """Export to Wigle CSV."""
        try:
            filepath = export_csv(self.db, EXPORT_DIR)
            return f"Exported: {os.path.basename(filepath)}"
        except Exception as e:
            return f"Export failed: {e}"

    def _upload_callback(self):
        """Upload latest export to Wigle."""
        name = self.config.get('wigle_api_name', '')
        token = self.config.get('wigle_api_token', '')
        if not name or not token:
            return "No API key set"
        # Find latest export
        try:
            exports = sorted([f for f in os.listdir(EXPORT_DIR) if f.endswith('.csv')])
            if not exports:
                return "No exports found"
            filepath = os.path.join(EXPORT_DIR, exports[-1])
            success, msg = upload_to_wigle(filepath, name, token)
            return msg
        except Exception as e:
            return f"Upload failed: {e}"

    def _ask_session(self):
        """Ask user to start new session or continue previous."""
        # Check if there's existing data
        existing = 0
        try:
            existing = self.db.get_stats()['total']
        except Exception:
            pass

        if existing == 0:
            return  # No existing data, just start fresh

        from config import SCREEN_W, SCREEN_H
        selected = 0  # 0=Continue, 1=New Session
        items = [f"Continue ({existing} APs)", "New Session"]

        while True:
            # Draw
            blocks.background(self.pager, self.dashboard.bg_image)

            from config import FONT_TITLE, FONT_MENU
            title_color = palette.rgb(self.pager, palette.ACCENT)
            unsel_color = palette.rgb(self.pager, palette.INK)

            tw = self.pager.ttf_width("Wardrive", FONT_TITLE, 28)
            self.pager.draw_ttf((SCREEN_W - tw) // 2, 28, "Wardrive", title_color, FONT_TITLE, 28)

            for i, item in enumerate(items):
                y = 80 + i * 24
                if i == selected:
                    # A filled block, not a colour. Refer to blocks.py.
                    blocks.centered_button(self.pager, SCREEN_W, y, item, FONT_MENU, 18)
                else:
                    tw = self.pager.ttf_width(item, FONT_MENU, 18)
                    self.pager.draw_ttf((SCREEN_W - tw) // 2, y, item, unsel_color, FONT_MENU, 18)

            self.pager.flip()

            button = self.pager.wait_button()
            if button & self.pager.BTN_UP or button & self.pager.BTN_DOWN:
                selected = 1 - selected
            elif button & self.pager.BTN_A:
                if selected == 1:
                    # New session — archive DB, start new wigle file
                    self._archive_session()
                    self.wigle_writer.start_session()
                else:
                    # Continue — resume existing wigle file
                    latest = self.wigle_writer.get_latest_file()
                    if latest:
                        self.wigle_writer.resume_session(latest)
                    else:
                        self.wigle_writer.start_session()
                return

    def _archive_session(self):
        """Archive current DB and exports, start fresh."""
        from datetime import datetime
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')

        # Finalize the current track for the archived session.
        self.gpx_writer.close()

        # Close current DB
        self.db.close()

        # Rename DB
        if os.path.isfile(DB_PATH):
            archive_path = DB_PATH.replace('.db', f'_{timestamp}.db')
            os.rename(DB_PATH, archive_path)

        # Rename latest CSV
        latest_csv = os.path.join(EXPORT_DIR, 'wardrive_latest.csv')
        if os.path.isfile(latest_csv):
            os.rename(latest_csv, os.path.join(EXPORT_DIR, f'wardrive_{timestamp}.csv'))

        # Reopen fresh DB
        self.db = Database(DB_PATH, average_positions=self.config.get('gps_average_positions', False))

    def run(self):
        """Main run loop."""
        self._ask_session()

        # If no wigle file started yet (first run with empty DB), start one
        if not self.wigle_writer.filepath:
            self.wigle_writer.start_session()

        # Start scanning immediately
        self.scan_state = 'scanning'
        self._start_threads()

        try:
            last_process = 0.0
            last_frame_sig = None
            while True:
                now = time.time()

                # Apply phone commands every iteration, so they stay responsive.
                applied = False
                for cmd in self.control.drain():
                    self._apply_command(cmd)
                    applied = True

                # The heavy work - scanning, stats, the dashboard redraw - runs
                # on a short cadence, not on every pass. Redrawing every pass
                # blocked the loop long enough to miss button taps, which is why
                # input felt unresponsive. Input is polled every iteration below.
                if applied or now - last_process >= PROCESS_INTERVAL:
                    last_process = now

                    new_aps = 0
                    if self.scan_state == 'scanning':
                        new_aps = self._process_scan_results()
                        self._process_captures()
                        if now - self._correlate_at > CORRELATE_INTERVAL:
                            self.db.correlate_open_bssids()
                            self._correlate_at = now
                        if new_aps > 0:
                            self.wigle_writer.append_aps(self.db.get_all_aps())
                        self._geiger_sound(new_aps)

                    stats = self._get_stats_cached(force=new_aps > 0)
                    gps = self.gps_state.copy()

                    # Drive track. fix_mode is already stale-adjusted by copy().
                    if (self.config.get('gpx_enabled', True)
                            and self.scan_state == 'scanning' and gps.fix_mode >= 2):
                        if not self.gpx_writer.filepath:
                            self.gpx_writer.start_session()
                        self.gpx_writer.add_point(gps.lat, gps.lon, gps.alt, gps.timestamp)

                    if self.scan_state == 'paused':
                        elapsed = self.paused_elapsed
                    else:
                        elapsed = self.paused_elapsed + int(now - self.start_time)

                    if applied or now - self._publish_at > PUBLISH_INTERVAL:
                        self.control.publish(self._control_status(stats, gps, elapsed))
                        self._publish_at = now

                    # Redraw only when something visible changed. The dashboard
                    # changes about once a second (the clock) or on a new find,
                    # so this keeps the expensive flip off the hot path and the
                    # loop free to catch button presses.
                    if not self.screen_off:
                        battery = self._get_battery()
                        sig = (elapsed, self.scan_state, self.current_channel,
                               stats.get('total', 0), stats.get('handshakes', 0),
                               gps.fix_mode, gps.satellites,
                               round(gps.lat, 4), round(gps.lon, 4), battery,
                               self.config['scan_2_4ghz'], self.config['scan_5ghz'],
                               self.config['scan_6ghz'])
                        if sig != last_frame_sig:
                            last_frame_sig = sig
                            scan_mode = self.config.get('scan_mode', 'active')
                            iface = (self.config['capture_interface']
                                     if scan_mode == 'stealth' else self.config['scan_interface'])
                            bands = {'2.4': self.config['scan_2_4ghz'],
                                     '5': self.config['scan_5ghz'],
                                     '6': self.config['scan_6ghz']}
                            self.dashboard.render(
                                stats, gps, elapsed, self.current_channel,
                                iface, bands, scan_mode, battery,
                                self.config.get('gps_enabled', True))

                    screen_timeout = self.config.get('screen_timeout', 60)
                    if (screen_timeout > 0 and not self.screen_off
                            and now - self.last_activity > screen_timeout):
                        self.pager.set_brightness(0)
                        self.screen_off = True

                # Input, every iteration, so short taps are not missed.
                _, pressed, _ = self.pager.poll_input()
                if not pressed:
                    time.sleep(0.015)
                    continue

                if self.screen_off:
                    # The first press only wakes the screen.
                    self.pager.set_brightness(self.config.get('brightness', 80))
                    self.screen_off = False
                    self.last_activity = time.time()
                    last_frame_sig = None
                    continue

                self.last_activity = time.time()
                entered = False
                if pressed & self.pager.BTN_A:
                    self._show_scan_menu()
                    entered = True
                elif pressed & self.pager.BTN_RIGHT:
                    profile_ui.show(self.pager, self.player, self.db.get_stats(),
                                    self.config.get('pager_avatar_png', True))
                    entered = True
                elif pressed & self.pager.BTN_B:
                    # Scan keeps running in background
                    settings = SettingsMenu(self.pager, self.config, self.gps_reader)
                    result = settings.show(export_callback=self._export_callback,
                                           upload_callback=self._upload_callback)
                    if result == '__exit__':
                        break
                    self.config = result
                    entered = True

                if entered:
                    # A menu may have previewed brightness; restore the saved
                    # value. Reset the activity timer so the screen does not
                    # blank the instant we return, force a redraw, and drain the
                    # button release so it does not leak into the dashboard.
                    self.pager.set_brightness(self.config.get('brightness', 80))
                    self.last_activity = time.time()
                    last_frame_sig = None
                    for _ in range(3):
                        self.pager.poll_input()
                        time.sleep(0.05)

        except KeyboardInterrupt:
            pass
        finally:
            self._stop_threads()
            self.gpx_writer.close()
            if self.web_server:
                self.web_server.stop()
            self.db.close()
            blocks.background(self.pager)
            self.pager.flip()
            self.pager.cleanup()


def main():
    app = Wardrive()
    app.run()


if __name__ == '__main__':
    main()
