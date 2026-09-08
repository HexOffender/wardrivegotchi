"""WiFi scanner — active (iw scan) and passive (raw beacon capture) modes."""

import os
import re
import struct
import subprocess
import threading
import time
import queue
from beacon_parser import parse_radiotap_and_beacon

# (1) Filter in tcpdump, not in Python. Only management beacon and probe-response
# frames carry AP info, so drop everything else in-kernel instead of shipping
# every data/control frame up the pipe - on a busy channel that is the
# difference between keeping up and dropping beacons. Snaplen keeps only the
# front of each frame (radiotap + header + the SSID/RSN/DS IEs). Some tcpdump
# builds or capture DLTs reject the 802.11 BPF primitives; PassiveScanner drops
# the filter and retries unfiltered if so, so scanning still works everywhere.
BEACON_FILTER = 'type mgt subtype beacon or type mgt subtype probe-resp'
SNAPLEN = 512


def detect_second_monitor(primary, base='/sys/class/net'):
    """Find a monitor-mode interface other than `primary` - e.g. a USB adapter
    that came up as wlan2mon - so a plugged-in radio is used automatically with
    no configuration. Returns its name, or '' if there is none. A radiotap
    monitor interface has sysfs type 803 (ARPHRD_IEEE80211_RADIOTAP)."""
    try:
        for name in sorted(os.listdir(base)):
            if name == primary:
                continue
            try:
                with open('%s/%s/type' % (base, name)) as f:
                    if f.read().strip() == '803':
                        return name
            except Exception:
                continue
    except Exception:
        pass
    return ''


class Scanner(threading.Thread):
    """Active scanner using iw scan on a managed interface."""

    def __init__(self, interface, channels, scan_interval, output_queue, stop_event):
        super().__init__(daemon=True)
        self.interface = interface
        self.channels = channels
        self.scan_interval = scan_interval
        self.output_queue = output_queue
        self.stop_event = stop_event
        self.current_channel = 0

    def run(self):
        while not self.stop_event.is_set():
            try:
                aps = self._scan()
                if aps:
                    self.output_queue.put(aps)
            except Exception:
                pass
            self.stop_event.wait(self.scan_interval)

    def _scan(self):
        """Run iw scan and parse results."""
        try:
            result = subprocess.run(
                ['iw', 'dev', self.interface, 'scan', 'ap-force'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ['iw', 'dev', self.interface, 'scan'],
                    capture_output=True, text=True, timeout=15
                )
            return parse_iw_scan(result.stdout)
        except subprocess.TimeoutExpired:
            return []
        except Exception:
            return []


class PassiveScanner(threading.Thread):
    """Passive scanner using tcpdump on a monitor interface with channel hopping."""

    def __init__(self, interface, channels, hop_interval, output_queue, stop_event,
                 priority=None, priority_weight=2):
        super().__init__(daemon=True)
        self.interface = interface
        self.channels = channels
        self.hop_interval = hop_interval  # seconds dwell per channel
        # (2) A prioritised hop order: the channels most APs sit on get visited
        # more often than the rest, so a sweep spends its time where the
        # networks are. See _build_hop_order.
        self.hop_order = _build_hop_order(channels, set(priority or ()), priority_weight)
        self.output_queue = output_queue
        self.stop_event = stop_event
        self.current_channel = 0
        self._tcpdump = None
        self._use_filter = True  # dropped automatically if this tcpdump rejects it
        self._seen_aps = {}  # bssid -> ap dict (running state)

    def run(self):
        # Start channel hopper
        hopper = threading.Thread(target=self._hop_channels, daemon=True)
        hopper.start()

        # Capture beacons
        while not self.stop_event.is_set():
            try:
                self._capture_beacons()
            except Exception:
                pass
            if not self.stop_event.is_set():
                time.sleep(1)

    def _hop_channels(self):
        """Hop through the prioritised channel order on the monitor interface."""
        order = self.hop_order or self.channels
        idx = 0
        while not self.stop_event.is_set():
            if order:
                ch = order[idx % len(order)]
                try:
                    subprocess.run(
                        ['iw', 'dev', self.interface, 'set', 'channel', str(ch)],
                        capture_output=True, timeout=2
                    )
                    self.current_channel = ch
                except Exception:
                    pass
                idx += 1
            self.stop_event.wait(self.hop_interval)

    def _tcpdump_args(self):
        args = ['tcpdump', '-i', self.interface, '-s', str(SNAPLEN),
                '-w', '-', '-U', '--immediate-mode']
        if self._use_filter:
            args.append(BEACON_FILTER)
        return args

    def _capture_beacons(self):
        """Capture raw beacon frames using tcpdump binary output and parse IEs."""
        # Raw pcap to stdout — we parse the binary frames for accurate encryption
        self._tcpdump = subprocess.Popen(
            self._tcpdump_args(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        batch_time = time.time()
        try:
            # tcpdump writes the 24-byte pcap global header as soon as it starts,
            # even before any packet, so a short read means it failed to start.
            header = self._tcpdump.stdout.read(24)
            if len(header) < 24:
                # A tcpdump build/DLT that rejects the beacon BPF filter dies at
                # once. Drop the filter so the next pass captures unfiltered.
                if self._use_filter:
                    self._use_filter = False
                return

            while not self.stop_event.is_set():
                # Read pcap packet header (16 bytes)
                pkt_header = self._tcpdump.stdout.read(16)
                if len(pkt_header) < 16:
                    break

                ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', pkt_header)

                # Read packet data
                pkt_data = self._tcpdump.stdout.read(incl_len)
                if len(pkt_data) < incl_len:
                    break

                # Parse radiotap + beacon
                signal, frequency, beacon = parse_radiotap_and_beacon(pkt_data)
                if beacon is None:
                    continue

                bssid = beacon['bssid']
                beacon['signal'] = signal or -80
                beacon['frequency'] = frequency or 0

                # Update or add
                existing = self._seen_aps.get(bssid)
                if not existing or beacon['signal'] > existing['signal']:
                    self._seen_aps[bssid] = beacon

                # Push batch every 2 seconds
                now = time.time()
                if now - batch_time >= 2 and self._seen_aps:
                    self.output_queue.put(list(self._seen_aps.values()))
                    self._seen_aps.clear()
                    batch_time = now

        finally:
            if self._tcpdump:
                self._tcpdump.terminate()
                self._tcpdump = None

    def stop(self):
        if self._tcpdump:
            self._tcpdump.terminate()


# ---------------------------------------------------------------------------
# Shared parsing for iw scan output
# ---------------------------------------------------------------------------

def _build_hop_order(channels, priority_set, weight):
    """Build the channel hop sequence. Channels in priority_set are interleaved
    `weight` times (round-robin) before each non-priority channel, so the busy
    channels (2.4 GHz 1/6/11, common 5 GHz) get far more airtime while the rest
    are still sampled. Returns the plain list when there is nothing to weight."""
    channels = list(channels)
    pri = [c for c in channels if c in priority_set]
    sec = [c for c in channels if c not in priority_set]
    if not pri or not sec or weight <= 0:
        return channels
    order = []
    pi = 0
    for s in sec:
        for _ in range(weight):
            order.append(pri[pi % len(pri)])
            pi += 1
        order.append(s)
    return order


def parse_iw_scan(output):
    """Parse iw scan output into AP dicts."""
    aps = []
    current = None

    for line in output.split('\n'):
        line = line.rstrip()

        m = re.match(r'^BSS ([0-9a-f:]{17})', line, re.IGNORECASE)
        if m:
            if current:
                current['encryption'] = _determine_encryption(current)
                aps.append(current)
            current = {
                'bssid': m.group(1).upper(),
                'ssid': '',
                'channel': 0,
                'signal': -100,
                'encryption': 'Open',
                '_has_rsn': False,
                '_has_wpa': False,
                '_has_privacy': False,
                '_has_sae': False,
            }
            continue

        if current is None:
            continue

        stripped = line.strip()

        if stripped.startswith('SSID:'):
            current['ssid'] = stripped[5:].strip()
        elif stripped.startswith('signal:'):
            m = re.search(r'(-?\d+)', stripped)
            if m:
                current['signal'] = int(m.group(1))
        elif stripped.startswith('DS Parameter set: channel'):
            m = re.search(r'channel (\d+)', stripped)
            if m:
                current['channel'] = int(m.group(1))
        elif stripped.startswith('primary channel:'):
            m = re.search(r'(\d+)', stripped)
            if m and current['channel'] == 0:
                current['channel'] = int(m.group(1))
        elif stripped.startswith('RSN:'):
            current['_has_rsn'] = True
        elif stripped.startswith('WPA:'):
            current['_has_wpa'] = True
        elif 'Privacy' in stripped and 'capability' in line.lower():
            current['_has_privacy'] = True
        elif 'SAE' in stripped or 'auth_alg: SAE' in stripped.lower():
            current['_has_sae'] = True

    if current:
        current['encryption'] = _determine_encryption(current)
        aps.append(current)

    # Clean up internal fields
    for ap in aps:
        for key in ('_has_rsn', '_has_wpa', '_has_privacy', '_has_sae'):
            ap.pop(key, None)

    return aps


def _determine_encryption(ap):
    """Determine encryption type from parsed flags."""
    if ap.get('_has_sae'):
        return 'WPA3'
    if ap.get('_has_rsn'):
        return 'WPA2'
    if ap.get('_has_wpa'):
        return 'WPA'
    if ap.get('_has_privacy'):
        return 'WEP'
    if not ap.get('ssid'):
        return 'Unknown'
    return 'Open'
