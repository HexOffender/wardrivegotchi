"""Tests for the GPX track writer. Run: python3 gpx_test.py"""
import os
import sys
import tempfile

from gpx_logger import GpxWriter, _haversine_m

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def main():
    d = tempfile.mkdtemp()
    w = GpxWriter(d, min_move_m=10.0)
    w.start_session()
    path = w.filepath

    check(w.add_point(45.0, -75.0, 100.0, "2026-01-01T00:00:00Z"), "first point written")
    check(not w.add_point(45.00001, -75.0), "near point skipped (< 10 m)")
    check(w.add_point(45.01, -75.0), "far point written")
    check(not w.add_point(0.0, 0.0), "0,0 point skipped")
    w.close()

    data = open(path).read()
    check(data.count("<trkpt") == 2, "two trkpts in file (%d)" % data.count("<trkpt"))
    check(data.strip().endswith("</gpx>"), "file is closed with </gpx>")
    check("<ele>100.0</ele>" in data, "elevation written when present")

    # Repair-on-start: an unclosed track from a crash gets closed next session.
    d2 = tempfile.mkdtemp()
    stale = os.path.join(d2, "track_20260101_000000.gpx")
    open(stale, "w").write('<?xml version="1.0"?>\n<gpx><trk><trkseg>\n'
                           '<trkpt lat="1" lon="2"></trkpt>\n')
    w2 = GpxWriter(d2)
    w2.start_session()
    check("</gpx>" in open(stale).read(), "unclosed prior track repaired on start")
    w2.close()

    # Haversine sanity: ~111 km per degree of latitude.
    check(abs(_haversine_m(0, 0, 1, 0) - 111195) < 500, "haversine ~111 km/deg")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
