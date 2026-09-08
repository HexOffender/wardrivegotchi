"""Tests for the database: 0,0 back-fill, position rules, migration, averaging.
Run: python3 database_test.py
"""
import os
import sys
import tempfile

from database import Database, _rssi_weight

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


class G:
    def __init__(self, lat=0.0, lon=0.0, alt=0.0, mode=0):
        self.lat, self.lon, self.alt, self.fix_mode = lat, lon, alt, mode


def ap(bssid, sig, enc="WPA2"):
    return {"bssid": bssid, "ssid": "x", "channel": 6, "signal": sig, "encryption": enc}


def lat_of(db, bssid):
    return db.conn.execute("SELECT lat FROM access_points WHERE bssid=?", (bssid,)).fetchone()[0]


def main():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "t.db"))

    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(access_points)")}
    check({"obs_count", "w_sum", "wlat_sum", "wlon_sum", "walt_sum"} <= cols,
          "migration added the aggregate columns")

    # 0,0 back-fill on a later (even weaker) fix.
    db.upsert_ap(ap("A1", -60), G(mode=0))
    check(lat_of(db, "A1") == 0.0, "stored at 0,0 with no fix")
    db.upsert_ap(ap("A1", -85), G(45.0, -75.0, 100.0, 3))
    check(db.conn.execute("SELECT lat,lon FROM access_points WHERE bssid='A1'").fetchone() == (45.0, -75.0),
          "0,0 back-filled on a later weaker fix")

    # Default strongest-signal rule.
    db.upsert_ap(ap("A2", -50), G(10.0, 10.0, 0.0, 2))
    db.upsert_ap(ap("A2", -40), G(11.0, 11.0, 0.0, 2))
    check(lat_of(db, "A2") == 11.0, "stronger signal updates position")
    db.upsert_ap(ap("A2", -70), G(12.0, 12.0, 0.0, 2))
    check(lat_of(db, "A2") == 11.0, "weaker signal keeps position")

    # Migration is idempotent across reopen (and data survives).
    db.close()
    db = Database(os.path.join(d, "t.db"))
    check(lat_of(db, "A2") == 11.0, "reopen after migrate keeps data")

    # Averaging mode: RSSI-weighted centroid.
    d2 = tempfile.mkdtemp()
    dba = Database(os.path.join(d2, "a.db"), average_positions=True)
    dba.upsert_ap(ap("B1", -50), G(10.0, 20.0, 0.0, 2))
    dba.upsert_ap(ap("B1", -50), G(20.0, 40.0, 0.0, 2))
    lat, lon = dba.conn.execute("SELECT lat,lon FROM access_points WHERE bssid='B1'").fetchone()
    check(abs(lat - 15.0) < 1e-6 and abs(lon - 30.0) < 1e-6,
          "equal-weight centroid is the midpoint (%.3f,%.3f)" % (lat, lon))
    dba.upsert_ap(ap("B1", -20), G(20.0, 40.0, 0.0, 2))
    check(lat_of(dba, "B1") > 15.0, "a stronger fix pulls the average toward it (%.3f)" % lat_of(dba, "B1"))

    # Averaging mode still back-fills a 0,0 record.
    dba.upsert_ap(ap("B2", -60), G(mode=0))
    dba.upsert_ap(ap("B2", -60), G(30.0, 30.0, 0.0, 2))
    check(lat_of(dba, "B2") == 30.0, "averaging: 0,0 back-filled")

    check(_rssi_weight(-30) > _rssi_weight(-80), "stronger RSSI weighs more")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
