"""GPS reader using gpspipe for location data."""

import json
import subprocess
import threading
import time


class GpsState:
    """Thread-safe GPS state."""
    def __init__(self, stale_secs=0):
        self.lat = 0.0
        self.lon = 0.0
        self.alt = 0.0
        self.speed = 0.0  # m/s
        self.satellites = 0
        self.fix_mode = 0  # 0=none, 2=2D, 3=3D
        self.timestamp = ""
        # A fix older than stale_secs is reported as no fix, so a frozen phone
        # position (screen locked, page backgrounded) is not recorded against
        # access points. 0 disables the check. _last_fix_at is monotonic time.
        self.stale_secs = stale_secs
        self._last_fix_at = 0.0
        self._lock = threading.Lock()

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            # A message carrying a position resets the freshness timer.
            if 'lat' in kwargs and 'lon' in kwargs:
                self._last_fix_at = time.monotonic()

    def _is_stale(self):
        return 0 < self.stale_secs < time.monotonic() - self._last_fix_at and self._last_fix_at > 0

    def copy(self):
        """Return a snapshot of current state. A stale position is reported as
        no fix (fix_mode 0), so downstream code treats it as no position."""
        with self._lock:
            s = GpsState()
            s.lat = self.lat
            s.lon = self.lon
            s.alt = self.alt
            s.speed = self.speed
            s.satellites = self.satellites
            s.fix_mode = 0 if self._is_stale() else self.fix_mode
            s.timestamp = self.timestamp
            return s

    @property
    def speed_mph(self):
        """Speed in mph."""
        with self._lock:
            return self.speed * 2.237

    @property
    def has_fix(self):
        with self._lock:
            return self.fix_mode >= 2 and not self._is_stale()


class GpsReader(threading.Thread):
    def __init__(self, device, baud, gps_state, stop_event, phone_gps=False):
        super().__init__(daemon=True)
        self.device = device
        self.baud = baud
        self.gps_state = gps_state
        self.stop_event = stop_event
        # With the bundled phone GPS server running, gpsd belongs to it: it is
        # attached to a pty rather than a serial device, and it supervises that
        # attachment itself. Restarting gpsd from here would silently replace a
        # working feed with one pointed at hardware that is not there.
        self.phone_gps = phone_gps
        self._process = None

    def run(self):
        self._ensure_gpsd()
        while not self.stop_event.is_set():
            try:
                self._read_gpspipe()
            except Exception:
                pass
            if not self.stop_event.is_set():
                time.sleep(2)

    def _ensure_gpsd(self):
        """Start gpsd if not running."""
        if self.phone_gps:
            self._wait_for_gpsd()
            return
        try:
            result = subprocess.run(['pgrep', '-x', 'gpsd'],
                                    capture_output=True, timeout=3)
            if result.returncode != 0:
                self.restart_gpsd()
        except Exception:
            pass

    def _wait_for_gpsd(self, timeout=20):
        """Wait for the phone GPS server to bring gpsd up."""
        deadline = time.time() + timeout
        while time.time() < deadline and not self.stop_event.is_set():
            try:
                result = subprocess.run(['pgrep', '-x', 'gpsd'],
                                        capture_output=True, timeout=3)
                if result.returncode == 0:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def restart_gpsd(self, device=None, baud=None):
        """Restart gpsd with given device. Does not modify system config."""
        if self.phone_gps:
            # Owned by the phone GPS server - leave it alone.
            return
        if device:
            self.device = device
        if baud and baud != 'auto':
            self.baud = baud
        try:
            subprocess.run(['killall', 'gpsd'], capture_output=True, timeout=3)
            time.sleep(0.5)
            subprocess.Popen(
                ['gpsd', '-n', '-b', self.device],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
        time.sleep(1)

    def _read_gpspipe(self):
        """Read JSON from gpspipe -w."""
        self._process = subprocess.Popen(
            ['gpspipe', '-w'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True
        )
        try:
            for line in self._process.stdout:
                if self.stop_event.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                cls = msg.get('class', '')

                if cls == 'TPV':
                    updates = {}
                    if 'lat' in msg:
                        updates['lat'] = msg['lat']
                    if 'lon' in msg:
                        updates['lon'] = msg['lon']
                    if 'alt' in msg or 'altHAE' in msg:
                        updates['alt'] = msg.get('altHAE', msg.get('alt', 0.0))
                    if 'speed' in msg:
                        updates['speed'] = msg['speed']
                    if 'mode' in msg:
                        updates['fix_mode'] = msg['mode']
                    if 'time' in msg:
                        updates['timestamp'] = msg['time']
                    if updates:
                        self.gps_state.update(**updates)

                elif cls == 'SKY':
                    sats = 0
                    for sat in msg.get('satellites', []):
                        if sat.get('used', False):
                            sats += 1
                    self.gps_state.update(satellites=sats)
        finally:
            if self._process:
                self._process.terminate()
                self._process = None

    def stop(self):
        """Stop the GPS reader."""
        if self._process:
            self._process.terminate()
