"""Tests for GpsState staleness. Run: python3 gps_test.py

No test runner on the Pager, so this is a plain script that exits non-zero on
any failure.
"""
import sys
import time

from gps_module import GpsState

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def main():
    # A fresh position reads through as a real fix.
    g = GpsState(stale_secs=5)
    g.update(lat=45.0, lon=-75.0, fix_mode=3)
    s = g.copy()
    check(s.fix_mode == 3 and s.has_fix, "fresh fix is valid")

    # Age the last position past the threshold: reported as no fix.
    g._last_fix_at = time.monotonic() - 10
    s = g.copy()
    check(s.fix_mode == 0 and not s.has_fix, "stale fix reads as no fix")
    check(g.copy().lat == 45.0, "last-known position still on the snapshot")

    # A new position clears staleness again.
    g.update(lat=46.0, lon=-76.0, fix_mode=2)
    check(g.copy().fix_mode == 2, "a new position clears staleness")

    # stale_secs = 0 disables the check.
    g2 = GpsState(stale_secs=0)
    g2.update(lat=1.0, lon=2.0, fix_mode=2)
    g2._last_fix_at = time.monotonic() - 100
    check(g2.copy().fix_mode == 2, "stale check disabled when stale_secs=0")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
