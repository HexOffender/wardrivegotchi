"""Settings menu UI for wardriving payload — grouped submenus."""

import glob
import os
import subprocess
import time

import blocks
import palette
from config import BG_IMAGE, SCREEN_W, SCREEN_H, FONT_MENU, FONT_TITLE, save_config





class SettingsMenu:
    """LCD settings menu with grouped submenus."""

    def __init__(self, pager, config, gps_reader=None):
        self.pager = pager
        self.config = config
        self.gps_reader = gps_reader
        self.font = FONT_MENU
        self.title_font = FONT_TITLE
        # The paper background. The active pager theme is dark and this
        # palette is dark ink, thus the theme cannot be used here.
        self.bg_image = BG_IMAGE if os.path.isfile(BG_IMAGE) else None

        # Colors
        self.TITLE_COLOR = palette.rgb(pager, palette.ACCENT)
        self.OK_TEXT = palette.rgb(pager, palette.OK)
        self.UNSELECTED = palette.rgb(pager, palette.INK)
        self.DIM = palette.rgb(pager, palette.INK_MUTED)

    def _draw_bg(self):
        """Draw the background."""
        blocks.background(self.pager, self.bg_image)

    def _draw_menu(self, title, items, selected, scroll_offset=0):
        """Draw a menu screen with title and scrolling items."""
        self._draw_bg()

        # Title
        tw = self.pager.ttf_width(title, self.title_font, 28)
        self.pager.draw_ttf((SCREEN_W - tw) // 2, 28, title, self.TITLE_COLOR, self.title_font, 28)

        # Items — centered, font size 18, max 5 visible
        start_y = 70
        item_height = 24
        fs = 18
        max_visible = 5

        visible = min(max_visible, len(items))

        for i in range(visible):
            idx = scroll_offset + i
            if idx >= len(items):
                break
            y = start_y + i * item_height
            label = items[idx]['label']
            if idx == selected:
                # A filled block, not a colour. Refer to blocks.py.
                blocks.centered_button(self.pager, SCREEN_W, y, label, self.font, fs)
            else:
                tw = self.pager.ttf_width(label, self.font, fs)
                self.pager.draw_ttf((SCREEN_W - tw) // 2, y, label, self.UNSELECTED, self.font, fs)

        # Scroll indicators
        if scroll_offset > 0:
            self.pager.draw_ttf(SCREEN_W - 25, start_y, "^", self.DIM, self.font, 12)
        if scroll_offset + visible < len(items):
            self.pager.draw_ttf(SCREEN_W - 25, start_y + (visible - 1) * item_height, "v", self.DIM, self.font, 12)

        self.pager.flip()

    def _show_message(self, text, duration=1.5):
        """Show a brief centered message."""
        self._draw_bg()
        tw = self.pager.ttf_width(text, self.font, 18)
        self.pager.draw_ttf((SCREEN_W - tw) // 2, 100, text, self.OK_TEXT, self.font, 18)
        self.pager.flip()
        time.sleep(duration)

    def _run_submenu(self, title, items_fn, action_fn):
        """Generic submenu loop. items_fn returns current items, action_fn handles selection."""
        selected = 0
        scroll_offset = 0
        max_visible = 5

        while True:
            items = items_fn()
            if selected >= len(items):
                selected = len(items) - 1

            # Keep selected in view
            if selected < scroll_offset:
                scroll_offset = selected
            elif selected >= scroll_offset + max_visible:
                scroll_offset = selected - max_visible + 1

            self._draw_menu(title, items, selected, scroll_offset)

            button = self.pager.wait_button()
            if button & self.pager.BTN_UP:
                selected = (selected - 1) % len(items)
            elif button & self.pager.BTN_DOWN:
                selected = (selected + 1) % len(items)
            elif button & self.pager.BTN_A:
                result = action_fn(items[selected])
                if result == '__back__':
                    return
                if result == '__exit__':
                    return '__exit__'
            elif button & self.pager.BTN_LEFT or button & self.pager.BTN_RIGHT:
                item = items[selected]
                if item.get('type') == 'cycle':
                    opts = item['options']
                    if opts:
                        current = self.config[item['key']]
                        try:
                            idx = opts.index(current)
                        except ValueError:
                            idx = -1
                        if button & self.pager.BTN_RIGHT:
                            self.config[item['key']] = opts[(idx + 1) % len(opts)]
                        else:
                            self.config[item['key']] = opts[(idx - 1) % len(opts)]
                        save_config(self.config)
            elif button & self.pager.BTN_B:
                return

    # ------------------------------------------------------------------
    # Interface / device detection
    # ------------------------------------------------------------------

    def _detect_wifi_interfaces(self):
        """Detect all WiFi interfaces (monitor + managed)."""
        ifaces = []
        try:
            result = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=3)
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Interface'):
                    ifaces.append(line.split()[-1])
        except Exception:
            pass
        return ifaces or ['wlan0mon', 'wlan1mon']

    def _get_gpsd_baud(self):
        """Get the baud rate gpsd auto-detected from the GPS device."""
        try:
            import json as _json
            result = subprocess.run(['gpspipe', '-w', '-n', '5'],
                                    capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if '"DEVICE"' in line or '"bps"' in line:
                    try:
                        data = _json.loads(line)
                        if 'devices' in data:
                            for dev in data['devices']:
                                if 'bps' in dev:
                                    return dev['bps']
                        elif 'bps' in data:
                            return data['bps']
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    def _detect_gps_devices(self):
        """Detect serial devices, filtering out known internal/non-GPS devices."""
        # Known internal pager devices to exclude
        exclude_keywords = ['uart', 'jtag', 'spi', 'i2c', 'debug', 'ehci', 'hub',
                            'wireless_device', 'csr8510', 'bluetooth']
        devices = []

        for pattern in ['/dev/ttyACM*', '/dev/ttyUSB*']:
            for dev in sorted(glob.glob(pattern)):
                product = self._get_device_product(dev).lower()
                if product and any(kw in product for kw in exclude_keywords):
                    continue  # Skip known non-GPS devices
                devices.append(dev)

        return devices

    def _is_monitor_mode(self, iface):
        """Check if interface is in monitor mode."""
        try:
            result = subprocess.run(['iw', 'dev', iface, 'info'],
                                    capture_output=True, text=True, timeout=3)
            return 'type monitor' in result.stdout
        except Exception:
            return False

    def _enable_monitor_mode(self, iface):
        """Enable monitor mode on an interface."""
        mon_iface = iface + 'mon' if not iface.endswith('mon') else iface
        try:
            # If already monitor, done
            if self._is_monitor_mode(iface):
                return iface

            # Try creating a monitor interface
            subprocess.run(['iw', 'dev', iface, 'interface', 'add', mon_iface, 'type', 'monitor'],
                           capture_output=True, timeout=5)
            subprocess.run(['ip', 'link', 'set', mon_iface, 'up'],
                           capture_output=True, timeout=3)
            return mon_iface
        except Exception:
            return iface

    # ------------------------------------------------------------------
    # Main settings menu
    # ------------------------------------------------------------------

    def show(self, export_callback=None, upload_callback=None):
        """Run the main settings menu. Returns config dict or '__exit__'."""
        # Reload config from disk in case web UI changed it
        from config import load_config
        fresh = load_config()
        self.config.update(fresh)

        self._export_callback = export_callback
        self._upload_callback = upload_callback

        def items_fn():
            return [
                {'label': 'GPS Settings', 'action': 'gps'},
                {'label': 'Scan Settings', 'action': 'scan'},
                {'label': 'Wigle', 'action': 'wigle'},
                {'label': 'Device', 'action': 'device'},
                {'label': 'Data', 'action': 'data'},
                {'label': 'Exit Wardrive', 'action': 'exit'},
            ]

        def action_fn(item):
            action = item.get('action')
            if action == 'back':
                return '__back__'
            elif action == 'exit':
                return '__exit__'
            elif action == 'gps':
                self._show_gps_settings()
            elif action == 'scan':
                self._show_scan_settings()
            elif action == 'wigle':
                result = self._show_wigle_settings()
                if result == '__exit__':
                    return '__exit__'
            elif action == 'device':
                self._show_device_settings()
            elif action == 'data':
                self._show_data_settings()
            return None

        result = self._run_submenu("Settings", items_fn, action_fn)
        if result == '__exit__':
            return '__exit__'
        return self.config

    # ------------------------------------------------------------------
    # GPS submenu
    # ------------------------------------------------------------------

    def _show_gps_settings(self):
        c = self.config

        def items_fn():
            dev = c['gps_device']
            if dev and os.path.exists(dev):
                product = self._get_device_product(dev)
                short = os.path.basename(dev)
                if product:
                    # Shorten: remove common suffixes, truncate to ~15 chars
                    for strip in [' Receiver', ' receiver', ' Module', ' module',
                                  ' - GPS/GNSS', ' GPS/GNSS', '/GNSS', ' - GPS']:
                        product = product.replace(strip, '')
                    if len(product) > 14:
                        product = product[:14].rstrip()
                    dev_label = f"{product} ({short})"
                else:
                    dev_label = short
            else:
                dev_label = "Not set"
            # Get detected baud from gpsd if available
            detected_baud = self._get_gpsd_baud()
            baud_val = c['gps_baud']
            if baud_val == 0 or baud_val == 'auto':
                baud_label = f"Baud: Auto ({detected_baud})" if detected_baud else "Baud: Auto"
            else:
                baud_label = f"Baud: {baud_val}"

            return [
                {'label': f"GPS: {'ON' if c['gps_enabled'] else 'OFF'}",
                 'key': 'gps_enabled', 'type': 'toggle', 'action': 'toggle'},
                {'label': f"Device: {dev_label}", 'action': 'pick_device'},
                {'label': baud_label, 'key': 'gps_baud', 'type': 'cycle',
                 'options': ['auto', 4800, 9600, 38400, 115200], 'action': 'cycle'},
                {'label': "Restart gpsd", 'action': 'restart_gpsd'},
            ]

        def action_fn(item):
            action = item.get('action')
            if action == 'back':
                return '__back__'
            elif action == 'toggle':
                self.config[item['key']] = not self.config[item['key']]
                save_config(self.config)
            elif action == 'cycle':
                opts = item.get('options', [])
                if opts:
                    current = self.config[item['key']]
                    try:
                        idx = opts.index(current)
                    except ValueError:
                        idx = -1
                    self.config[item['key']] = opts[(idx + 1) % len(opts)]
                    save_config(self.config)
            elif action == 'pick_device':
                self._pick_gps_device()
            elif action == 'restart_gpsd':
                self._show_message("Restarting gpsd...")
                if self.gps_reader:
                    self.gps_reader.restart_gpsd(c['gps_device'], c['gps_baud'])
                self._show_message("gpsd restarted")
            return None

        self._run_submenu("GPS", items_fn, action_fn)

    def _pick_gps_device(self):
        """Scan for GPS devices and let user pick one."""
        self._show_message("Scanning for GPS...", 0.5)
        devices = self._detect_gps_devices()

        if not devices:
            self._show_message("No GPS devices found")
            return

        # Build picker with device names
        def items_fn():
            items = []
            for dev in devices:
                # Try to get product name
                label = self._get_device_name(dev)
                items.append({'label': label, 'action': 'select', 'device': dev})
            return items

        def action_fn(item):
            if item.get('action') == 'select':
                self.config['gps_device'] = item['device']
                save_config(self.config)
                self._show_message(f"Set: {item['device']}")
                # Restart gpsd with new device
                if self.gps_reader:
                    self.gps_reader.restart_gpsd(item['device'], self.config['gps_baud'])
                return '__back__'
            return None

        self._run_submenu("Select GPS", items_fn, action_fn)

    def _get_device_product(self, dev_path):
        """Get USB product name for a serial device via sysfs."""
        dev_name = os.path.basename(dev_path)
        try:
            # Walk up from the tty device to find the USB product name
            device_link = os.path.realpath(f'/sys/class/tty/{dev_name}/device')
            d = device_link
            for _ in range(5):
                d = os.path.dirname(d)
                product_file = os.path.join(d, 'product')
                if os.path.isfile(product_file):
                    with open(product_file) as f:
                        return f.read().strip()
        except Exception:
            pass
        return ""

    def _get_device_name(self, dev_path):
        """Get a friendly name for a serial device — product name (ttyACMx)."""
        product = self._get_device_product(dev_path)
        short = os.path.basename(dev_path)
        if product:
            return f"{product} ({short})"
        return short

    # ------------------------------------------------------------------
    # Scan submenu
    # ------------------------------------------------------------------

    def _show_scan_settings(self):
        c = self.config
        all_ifaces = self._detect_wifi_interfaces()
        managed_ifaces = [i for i in all_ifaces if not self._is_monitor_mode(i)]
        monitor_ifaces = [i for i in all_ifaces if self._is_monitor_mode(i)]
        if not managed_ifaces:
            managed_ifaces = ['wlan0']
        if not monitor_ifaces:
            monitor_ifaces = ['wlan1mon']

        def items_fn():
            mode = c.get('scan_mode', 'stealth')
            if mode == 'stealth':
                mode_label = "Stealth (all bands)"
            else:
                mode_label = "Active (2.4 only*)"
            items = [
                {'label': f"Mode: {mode_label}", 'key': 'scan_mode', 'type': 'cycle',
                 'options': ['stealth', 'active'], 'action': 'cycle'},
            ]
            if mode == 'active':
                items.append({'label': f"Scan: {c['scan_interface']}", 'key': 'scan_interface',
                              'type': 'cycle', 'options': managed_ifaces, 'action': 'cycle'})
            items.append({'label': f"Monitor: {c['capture_interface']}", 'key': 'capture_interface',
                          'type': 'cycle', 'options': monitor_ifaces, 'action': 'cycle'})
            items.extend([
                {'label': f"2.4GHz: {'ON' if c['scan_2_4ghz'] else 'OFF'}",
                 'key': 'scan_2_4ghz', 'type': 'toggle', 'action': 'toggle'},
                {'label': f"5GHz: {'ON' if c['scan_5ghz'] else 'OFF'}",
                 'key': 'scan_5ghz', 'type': 'toggle', 'action': 'toggle'},
                {'label': f"6GHz: {'ON' if c['scan_6ghz'] else 'OFF'}",
                 'key': 'scan_6ghz', 'type': 'toggle', 'action': 'toggle'},
                {'label': f"Handshake: {'ON' if c['capture_enabled'] else 'OFF'}",
                 'key': 'capture_enabled', 'type': 'toggle', 'action': 'toggle'},
                {'label': "Back", 'action': 'back'},
            ])
            return items

        def action_fn(item):
            action = item.get('action')
            if action == 'back':
                return '__back__'
            elif action == 'toggle':
                self.config[item['key']] = not self.config[item['key']]
                save_config(self.config)
            elif action == 'cycle':
                opts = item.get('options', [])
                if opts:
                    current = self.config[item['key']]
                    try:
                        idx = opts.index(current)
                    except ValueError:
                        idx = -1
                    self.config[item['key']] = opts[(idx + 1) % len(opts)]
                    save_config(self.config)
            return None

        self._run_submenu("Scan Settings", items_fn, action_fn)

    # ------------------------------------------------------------------
    # Wigle submenu
    # ------------------------------------------------------------------

    def _show_data_settings(self):
        """Data management — clear handshakes, wigle files, database, all."""
        from config import EXPORT_DIR, CAPTURE_DIR, DB_PATH
        import shutil

        def _count_files(directory, ext):
            try:
                return len([f for f in os.listdir(directory) if f.endswith(ext)])
            except Exception:
                return 0

        def items_fn():
            wigle_count = _count_files(EXPORT_DIR, '.csv')
            pcap_count = _count_files(CAPTURE_DIR, '.pcap')
            hash_count = _count_files(CAPTURE_DIR, '.22000')
            return [
                {'label': f"Clear Wigle Files ({wigle_count})", 'action': 'clear_wigle'},
                {'label': f"Clear Captures ({pcap_count})", 'action': 'clear_pcap'},
                {'label': f"Clear Hashcat ({hash_count})", 'action': 'clear_hashcat'},
                {'label': "Clear Database", 'action': 'clear_db'},
                {'label': "Clear All Data", 'action': 'clear_all'},
                {'label': "Back", 'action': 'back'},
            ]

        def action_fn(item):
            action = item.get('action')
            if action == 'back':
                return '__back__'
            elif action == 'clear_wigle':
                if self._confirm("Clear all Wigle files?"):
                    self._clear_dir(EXPORT_DIR, '.csv')
                    self._show_message("Wigle files cleared")
            elif action == 'clear_pcap':
                if self._confirm("Clear all captures?"):
                    self._clear_dir(CAPTURE_DIR, '.pcap')
                    self._show_message("Captures cleared")
            elif action == 'clear_hashcat':
                if self._confirm("Clear all hashcat files?"):
                    self._clear_dir(CAPTURE_DIR, '.22000')
                    self._show_message("Hashcat files cleared")
            elif action == 'clear_db':
                if self._confirm("Clear database?"):
                    try:
                        import sqlite3
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute("DELETE FROM access_points")
                        conn.commit()
                        conn.close()
                        self._show_message("Database cleared")
                    except Exception:
                        self._show_message("Failed to clear DB")
            elif action == 'clear_all':
                if self._confirm("Clear ALL data?"):
                    self._clear_dir(EXPORT_DIR, '.csv')
                    self._clear_dir(CAPTURE_DIR, '.pcap')
                    self._clear_dir(CAPTURE_DIR, '.22000')
                    try:
                        import sqlite3
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute("DELETE FROM access_points")
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
                    self._show_message("All data cleared")
            return None

        self._run_submenu("Data", items_fn, action_fn)

    def _confirm(self, prompt):
        """Show YES/NO confirmation. Returns True if YES."""
        selected = 1  # Default to NO

        while True:
            self._draw_bg()
            ink = palette.rgb(self.pager, palette.INK)

            tw = self.pager.ttf_width(prompt, self.font, 16)
            self.pager.draw_ttf((SCREEN_W - tw) // 2, 70, prompt, ink, self.font, 16)

            # Two buttons, as on the phone page: the selected one has the
            # accent fill and the other one has the surface fill.
            center = SCREEN_W // 2
            blocks.text_button(self.pager, center - 60, 110, "YES", self.font, 18,
                               fill=palette.BRAND if selected == 0 else palette.SURFACE,
                               pad_y=4, offset=3)
            blocks.text_button(self.pager, center + 30, 110, "NO", self.font, 18,
                               fill=palette.BRAND if selected == 1 else palette.SURFACE,
                               pad_y=4, offset=3)
            self.pager.flip()

            button = self.pager.wait_button()
            if button & (self.pager.BTN_LEFT | self.pager.BTN_RIGHT | self.pager.BTN_UP | self.pager.BTN_DOWN):
                selected = 1 - selected
            elif button & self.pager.BTN_A:
                return selected == 0
            elif button & self.pager.BTN_B:
                return False

    def _clear_dir(self, directory, extension):
        """Remove all files with given extension from directory."""
        try:
            for f in os.listdir(directory):
                if f.endswith(extension):
                    os.remove(os.path.join(directory, f))
        except Exception:
            pass

    def _show_device_settings(self):
        """Device settings — web server, sound, brightness, screen timeout."""
        c = self.config

        def items_fn():
            timeout_str = f"{c['screen_timeout']}s" if c['screen_timeout'] > 0 else "Never"
            return [
                {'label': f"Web Server: {'ON' if c['web_server'] else 'OFF'}",
                 'key': 'web_server', 'type': 'toggle', 'action': 'toggle'},
                {'label': f"Sound: {'ON' if c['geiger_sound'] else 'OFF'}",
                 'key': 'geiger_sound', 'type': 'toggle', 'action': 'toggle'},
                {'label': f"Brightness: {c['brightness']}%", 'action': 'brightness'},
                {'label': f"Screen Off: {timeout_str}", 'key': 'screen_timeout', 'type': 'cycle',
                 'options': [0, 30, 60, 120, 300], 'action': 'cycle'},
                {'label': "Back", 'action': 'back'},
            ]

        def action_fn(item):
            action = item.get('action')
            if action == 'back':
                return '__back__'
            elif action == 'toggle':
                self.config[item['key']] = not self.config[item['key']]
                save_config(self.config)
            elif action == 'cycle':
                opts = item.get('options', [])
                if opts:
                    current = self.config[item['key']]
                    try:
                        idx = opts.index(current)
                    except ValueError:
                        idx = -1
                    self.config[item['key']] = opts[(idx + 1) % len(opts)]
                    save_config(self.config)
            elif action == 'brightness':
                self._adjust_brightness()
            return None

        self._run_submenu("Device", items_fn, action_fn)

    def _adjust_brightness(self):
        """Brightness adjustment with LEFT/RIGHT."""
        c = self.config
        brightness = c.get('brightness', 80)

        while True:
            self._draw_bg()
            title_color = palette.rgb(self.pager, palette.ACCENT)
            fill_color = palette.rgb(self.pager, palette.BRAND)
            unsel_color = palette.rgb(self.pager, palette.INK)

            tw = self.pager.ttf_width("Brightness", self.title_font, 28)
            self.pager.draw_ttf((SCREEN_W - tw) // 2, 28, "Brightness", title_color, self.title_font, 28)

            # Bar
            bar_x, bar_y, bar_w, bar_h = 80, 90, 320, 16
            self.pager.fill_rect(bar_x, bar_y, bar_w, bar_h, palette.rgb(self.pager, palette.FILL))
            fill_w = int(bar_w * brightness / 100)
            self.pager.fill_rect(bar_x, bar_y, fill_w, bar_h, fill_color)
            self.pager.rect(bar_x, bar_y, bar_w, bar_h, unsel_color)

            pct = f"{brightness}%"
            tw = self.pager.ttf_width(pct, self.font, 18)
            self.pager.draw_ttf((SCREEN_W - tw) // 2, 115, pct, unsel_color, self.font, 18)

            hint = "LEFT/RIGHT to adjust, GREEN to save"
            tw = self.pager.ttf_width(hint, self.font, 14)
            self.pager.draw_ttf((SCREEN_W - tw) // 2, 150, hint, self.DIM, self.font, 14)

            self.pager.flip()

            button = self.pager.wait_button()
            if button & self.pager.BTN_LEFT:
                brightness = max(5, brightness - 5)
                self.pager.set_brightness(brightness)
            elif button & self.pager.BTN_RIGHT:
                brightness = min(100, brightness + 5)
                self.pager.set_brightness(brightness)
            elif button & self.pager.BTN_A:
                self.config['brightness'] = brightness
                save_config(self.config)
                return
            elif button & self.pager.BTN_B:
                # Cancel: revert the live preview to the saved brightness.
                self.pager.set_brightness(c.get('brightness', 80))
                return

    def _show_wigle_settings(self):
        c = self.config

        def items_fn():
            has_creds = c.get('wigle_api_name') and c.get('wigle_api_token')
            cred_status = "set" if has_creds else "not set"
            wigle_files = self._get_wigle_files()
            items = [
                {'label': f"API Credentials: {cred_status}", 'action': 'info'},
                {'label': f"Upload Files ({len(wigle_files)})", 'action': 'upload_picker'},
                {'label': "Upload All", 'action': 'upload_all'},
                {'label': "Back", 'action': 'back'},
            ]
            return items

        def action_fn(item):
            action = item.get('action')
            if action == 'back':
                return '__back__'
            elif action == 'info':
                if c.get('wigle_api_name'):
                    self._show_message(f"Name: ...{c['wigle_api_name'][-8:]}")
                else:
                    self._show_message("Set via web UI :8888")
            elif action == 'upload_picker':
                self._show_upload_picker()
            elif action == 'upload_all':
                self._upload_all_files()
            return None

        return self._run_submenu("Wigle", items_fn, action_fn)

    def _get_wigle_files(self):
        """Find all wigle CSV files in export dir."""
        from config import EXPORT_DIR
        files = []
        try:
            for f in sorted(os.listdir(EXPORT_DIR)):
                if f.startswith('wigle_') and f.endswith('.csv'):
                    files.append(f)
        except Exception:
            pass
        return files

    def _show_upload_picker(self):
        """Show list of wigle files to upload individually."""
        from config import EXPORT_DIR

        def items_fn():
            files = self._get_wigle_files()
            items = [{'label': f, 'action': 'upload_file', 'file': f} for f in files]
            if not items:
                items = [{'label': "No files found", 'action': 'noop'}]
            return items

        def action_fn(item):
            action = item.get('action')
            if action == 'back':
                return '__back__'
            elif action == 'upload_file':
                filepath = os.path.join(EXPORT_DIR, item['file'])
                self._upload_single_file(filepath, item['file'])
            return None

        self._run_submenu("Upload", items_fn, action_fn)

    def _upload_single_file(self, filepath, filename):
        """Upload a single wigle file."""
        name = self.config.get('wigle_api_name', '')
        token = self.config.get('wigle_api_token', '')
        if not name or not token:
            self._show_message("Set API creds via web UI")
            return
        self._show_message(f"Uploading {filename}...")
        from wigle_export import upload_to_wigle
        success, msg = upload_to_wigle(filepath, name, token)
        self._show_message(msg)

    def _upload_all_files(self):
        """Upload all wigle files."""
        from config import EXPORT_DIR
        from wigle_export import upload_to_wigle
        name = self.config.get('wigle_api_name', '')
        token = self.config.get('wigle_api_token', '')
        if not name or not token:
            self._show_message("Set API creds via web UI")
            return
        files = self._get_wigle_files()
        if not files:
            self._show_message("No files to upload")
            return
        success_count = 0
        for f in files:
            filepath = os.path.join(EXPORT_DIR, f)
            self._show_message(f"Uploading {f}...", 0.5)
            ok, msg = upload_to_wigle(filepath, name, token)
            if ok:
                success_count += 1
        self._show_message(f"Uploaded {success_count}/{len(files)} files")
