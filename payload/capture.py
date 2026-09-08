"""Handshake capture — runs full pcap + EAPOL detection, auto-converts with hcxpcapngtool."""

import os
import re
import subprocess
import threading
import time
import queue
from datetime import datetime


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

    def _watch_eapol(self):
        """Watch for EAPOL (handshake) frames using tcpdump."""
        self._eapol_process = subprocess.Popen(
            ['tcpdump', '-i', self.interface, '-e', '-l',
             'ether proto 0x888e'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True
        )
        try:
            for line in self._eapol_process.stdout:
                if self.stop_event.is_set():
                    break
                bssid = self._extract_bssid(line)
                if bssid:
                    self.handshake_count += 1
                    self.output_queue.put(bssid)
        finally:
            if self._eapol_process:
                self._eapol_process.terminate()
                self._eapol_process = None

    def _extract_bssid(self, line):
        """Extract BSSID from tcpdump EAPOL line."""
        m = re.search(r'([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})',
                       line, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        return None

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
