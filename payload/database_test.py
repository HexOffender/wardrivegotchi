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

    # ---- incremental Wigle upload tracking ----
    d3 = tempfile.mkdtemp()
    u = Database(os.path.join(d3, "u.db"))
    cols = {r[1] for r in u.conn.execute("PRAGMA table_info(access_points)")}
    check("uploaded" in cols, "migration added the uploaded column")

    u.upsert_ap(ap("U1", -50), G(45.0, -75.0, 0.0, 2))   # has GPS
    u.upsert_ap(ap("U2", -55), G(46.0, -76.0, 0.0, 2))   # has GPS
    u.upsert_ap(ap("U3", -60), G(mode=0))                # no fix -> 0,0
    pending = {a["bssid"] for a in u.get_unuploaded_aps()}
    check(pending == {"U1", "U2"}, "pending = GPS'd, not-yet-uploaded (0,0 excluded): %s" % pending)

    u.mark_uploaded(["U1", "U2"])
    check(u.get_unuploaded_aps() == [], "after upload, nothing pending")

    # A new GPS'd AP becomes pending; the 0,0 one only after it is back-filled.
    u.upsert_ap(ap("U4", -50), G(47.0, -77.0, 0.0, 2))
    u.upsert_ap(ap("U3", -70), G(48.0, -78.0, 0.0, 2))   # back-fill U3's position
    pending2 = {a["bssid"] for a in u.get_unuploaded_aps()}
    check(pending2 == {"U3", "U4"}, "back-filled + new become pending, already-sent do not: %s" % pending2)

    # Reopen must not re-wipe the averaging aggregates (migration decoupling).
    u.conn.execute("UPDATE access_points SET obs_count=5 WHERE bssid='U1'")
    u.conn.commit(); u.close()
    u = Database(os.path.join(d3, "u.db"))
    check(u.conn.execute("SELECT obs_count FROM access_points WHERE bssid='U1'").fetchone()[0] == 5,
          "reopen does not reset aggregates when a column is added")

    # ---- running (O(1)) stats stay in sync with a fresh table COUNT ----
    sdb = Database(os.path.join(tempfile.mkdtemp(), "s.db"))
    def put(b, enc, ssid='x', sig=-50):
        sdb.upsert_ap({'bssid': b, 'ssid': ssid, 'channel': 6, 'signal': sig, 'encryption': enc},
                      G(45.0, -75.0, 0.0, 2))
    put("S1", "WPA2"); put("S2", "Open"); put("S3", "WEP"); put("S4", "WPA3"); put("S5", "WPA")
    put("S2", "WPA2")                         # reclassify Open -> WPA2
    sdb.mark_handshake("S1"); sdb.mark_handshake("S1")   # only the first counts
    put("CC:CC:CC:CC:CC:01", "Open", ssid='')  # hidden, will be correlated
    put("CC:CC:CC:CC:CC:02", "WPA2")           # its sibling
    sdb.correlate_open_bssids()
    check(sdb.get_stats() == sdb._compute_stats(),
          "running stats match a fresh COUNT after add/reclassify/handshake/correlate")
    check(sdb.get_stats()['total'] == 7 and sdb.get_stats()['handshakes'] == 1,
          "running stats values are correct")

    # clear() must wipe the table AND re-seed the O(1) running stats, so the
    # dashboard does not keep showing pre-clear totals (the Data-menu wipe path).
    sdb.clear()
    check(sdb.conn.execute("SELECT COUNT(*) FROM access_points").fetchone()[0] == 0,
          "clear() empties the table")
    check(sdb.get_stats() == sdb._compute_stats(),
          "clear() re-seeds running stats to match a fresh COUNT")
    check(sdb.get_stats()['total'] == 0 and sdb.get_stats()['handshakes'] == 0,
          "stats are all zero after clear()")
    # And the running counts stay correct as new APs arrive post-clear.
    put("Z1", "WPA2"); put("Z2", "Open")
    check(sdb.get_stats() == sdb._compute_stats(),
          "running stats match a fresh COUNT after clear() + new adds")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
