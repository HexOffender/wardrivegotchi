"""Handshake capture — runs full pcap + EAPOL detection, auto-converts with hcxpcapngtool."""

import os
import struct
import subprocess
import threading
import time
import queue
from datetime import datetime

from beacon_parser import eapol_bssid

# Only management/data frames can matter here, and EAPOL is small; a short snap
# is enough to see the radiotap header, the 802.11 header and the LLC/SNAP
# EtherType. The full frames for cracking come from the separate -w capture.
_EAPOL_SNAPLEN = 256
# Capture data frames only (EAPOL rides in a data frame). `wlan type data` is a
# real 802.11 primitive libpcap compiles correctly, unlike `ether proto`, which
# silently matches nothing on this radiotap link. Fallback drops the filter.
_EAPOL_FILTER = 'wlan type data'


class Capture(threading.Thread):
    def __init__(self, interface, capture_dir, output_queue, stop_event):
        super().__init__(daemon=True)
        self.interface = interface
        self.capture_dir = capture_dir
        self.output_queue = output_queue
        self.stop_event = stop_event
        self.handshake_count = 0
        self._pcap_process = None
        self._eapol_process = None
        self._eapol_use_filter = True   # dropped if this tcpdump rejects it
        self._seen_bssids = set()       # emit each handshake once for the live count
        self.pcap_path = None

    def run(self):
        os.makedirs(self.capture_dir, exist_ok=True)

        # Start full pcap capture for later cracking
        self._start_pcap()

        # Watch for EAPOL frames in parallel
        while not self.stop_event.is_set():
            try:
                self._watch_eapol()
            except Exception:
                pass
            if not self.stop_event.is_set():
                time.sleep(1)

        # On exit, stop pcap and convert
        self._stop_pcap()

    def _start_pcap(self):
        """Start full packet capture to pcap file."""
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.pcap_path = os.path.join(self.capture_dir, f'capture_{timestamp}.pcap')
        try:
            self._pcap_process = subprocess.Popen(
                ['tcpdump', '-i', self.interface, '-w', self.pcap_path, '-U'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            self._pcap_process = None

    def _stop_pcap(self):
        """Stop pcap capture and convert to hashcat format."""
        if self._pcap_process:
            self._pcap_process.terminate()
            self._pcap_process = None
            time.sleep(0.5)

        # Convert to .22000 format for hashcat
        if self.pcap_path and os.path.isfile(self.pcap_path):
            self._convert_pcap(self.pcap_path)

    def _eapol_args(self):
        args = ['tcpdump', '-i', self.interface, '-s', str(_EAPOL_SNAPLEN),
                '-w', '-', '-U', '--immediate-mode']
        if self._eapol_use_filter:
            args.append(_EAPOL_FILTER)
        return args

    def _watch_eapol(self):
        """Detect EAPOL (handshake) frames by parsing the raw capture stream.

        tcpdump's `ether proto 0x888e` matches nothing on this radiotap monitor
        interface (verified on-device), so instead of trusting the filter to
        find EAPOL, we read data frames as binary pcap and identify EAPOL from
        the 802.11 + LLC/SNAP bytes (see beacon_parser.eapol_bssid). Each BSSID
        is reported once; the full frames for cracking come from _start_pcap."""
        self._eapol_process = subprocess.Popen(
            self._eapol_args(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        try:
            # 24-byte pcap global header. A short read means tcpdump failed to
            # start - most likely it rejected the filter, so drop it and retry.
            header = self._eapol_process.stdout.read(24)
            if len(header) < 24:
                if self._eapol_use_filter:
                    self._eapol_use_filter = False
                return

            while not self.stop_event.is_set():
                pkt_header = self._eapol_process.stdout.read(16)
                if len(pkt_header) < 16:
                    break
                incl_len = struct.unpack('<IIII', pkt_header)[2]
                if incl_len == 0 or incl_len > _EAPOL_SNAPLEN * 4:
                    break  # not the pcap stream we expect; let run() restart us
                frame = self._eapol_process.stdout.read(incl_len)
                if len(frame) < incl_len:
                    break

                bssid = eapol_bssid(frame)
                if bssid:
                    self.handshake_count += 1
                    if bssid not in self._seen_bssids:
                        self._seen_bssids.add(bssid)
                        self.output_queue.put(bssid)
        finally:
            if self._eapol_process:
                self._eapol_process.terminate()
                self._eapol_process = None

    def _convert_pcap(self, pcap_path):
        """Convert pcap to hashcat 22000 format using hcxpcapngtool."""
        output_path = pcap_path.replace('.pcap', '.22000')
        try:
            result = subprocess.run(
                ['hcxpcapngtool', '-o', output_path, pcap_path],
                capture_output=True, timeout=60
            )
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return output_path
            else:
                # No handshakes in capture, remove empty file
                if os.path.isfile(output_path):
                    os.remove(output_path)
        except Exception:
            pass
        return None

    def stop(self):
        """Stop all capture processes."""
        if self._eapol_process:
            self._eapol_process.terminate()
        self._stop_pcap()
