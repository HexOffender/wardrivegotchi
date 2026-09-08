"""GPX track logging.

Records the drive as a GPX 1.1 track, next to the Wigle export. Points are
appended live so a crash loses at most the last point, and a track left open by
a crash is repaired (its closing tags appended) the next time a session starts.
Points are throttled by distance so idling does not pile up duplicates.
"""

import math
import os
from datetime import datetime, timezone

_FOOTER = '</trkseg></trk></gpx>\n'


def _haversine_m(lat1, lon1, lat2, lon2):
    """Distance in metres between two lat/lon points."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class GpxWriter:
    """Append-only GPX track writer, one track per scan session."""

    def __init__(self, export_dir, min_move_m=8.0):
        os.makedirs(export_dir, exist_ok=True)
        self.export_dir = export_dir
        self.min_move_m = min_move_m
        self.filepath = None
        self._last = None  # (lat, lon) of the last written point

    def start_session(self):
        """Repair any unfinished prior track, then open a new one."""
        self._repair_unclosed()
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.filepath = os.path.join(self.export_dir, 'track_%s.gpx' % timestamp)
        self._last = None
        try:
            with open(self.filepath, 'w') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<gpx version="1.1" creator="Wardrivegotchi" '
                        'xmlns="http://www.topografix.com/GPX/1/1">\n')
                f.write('<trk><name>wardrive %s</name><trkseg>\n' % timestamp)
        except Exception:
            self.filepath = None

    def add_point(self, lat, lon, alt=0.0, when=''):
        """Append a track point, unless it is at 0,0 or within min_move_m of the
        last one. Returns True if a point was written."""
        if not self.filepath:
            return False
        if lat == 0.0 and lon == 0.0:
            return False
        if self._last is not None:
            if _haversine_m(self._last[0], self._last[1], lat, lon) < self.min_move_m:
                return False
        t = when or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        try:
            with open(self.filepath, 'a') as f:
                f.write('<trkpt lat="%.6f" lon="%.6f">' % (lat, lon))
                if alt:
                    f.write('<ele>%.1f</ele>' % alt)
                f.write('<time>%s</time></trkpt>\n' % t)
        except Exception:
            return False
        self._last = (lat, lon)
        return True

    def close(self):
        """Write the closing tags and end the session."""
        if not self.filepath:
            return
        try:
            with open(self.filepath, 'a') as f:
                f.write(_FOOTER)
        except Exception:
            pass
        self.filepath = None
        self._last = None

    def _repair_unclosed(self):
        """Append closing tags to the most recent track if it has none, so a
        track left open by a crash becomes valid GPX."""
        try:
            tracks = sorted(f for f in os.listdir(self.export_dir)
                            if f.startswith('track_') and f.endswith('.gpx'))
        except Exception:
            return
        if not tracks:
            return
        path = os.path.join(self.export_dir, tracks[-1])
        try:
            with open(path, 'r') as f:
                data = f.read()
            if '</gpx>' not in data:
                with open(path, 'a') as f:
                    if not data.endswith('\n'):
                        f.write('\n')
                    f.write(_FOOTER)
        except Exception:
            pass
