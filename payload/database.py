"""SQLite database for wardriving AP data."""

import os
import sqlite3
from datetime import datetime


def _rssi_weight(signal):
    """Weight a sighting by its RSSI so stronger (closer) fixes count more toward
    the averaged position. Clamped to a sane dBm range."""
    if signal is None:
        signal = -90
    s = max(-100, min(-30, int(signal)))
    return 10.0 ** (s / 10.0)


class Database:
    def __init__(self, db_path, average_positions=False):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.average_positions = average_positions
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Wait (up to 5s) rather than erroring when another connection - e.g. a
        # background export/upload - holds the write lock.
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        # Running stats so the dashboard/phone never re-scan the whole table.
        # Seeded once; kept in sync by upsert_ap / correlate / mark_handshake.
        self._stats = self._compute_stats()

    def _create_tables(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS access_points (
                bssid TEXT PRIMARY KEY,
                ssid TEXT,
                channel INTEGER,
                frequency INTEGER DEFAULT 0,
                encryption TEXT,
                auth_mode TEXT DEFAULT '',
                signal INTEGER,
                lat REAL,
                lon REAL,
                alt REAL,
                first_seen TEXT,
                last_seen TEXT,
                handshake INTEGER DEFAULT 0
            )
        ''')
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Add columns newer versions need to an existing database, and seed the
        position-averaging aggregates from each row's current best fix so a
        later switch to averaging starts consistent. Idempotent."""
        cols = {row[1] for row in self.conn.execute('PRAGMA table_info(access_points)')}
        added = []
        for name, decl in (('obs_count', 'INTEGER DEFAULT 0'),
                           ('w_sum', 'REAL DEFAULT 0'),
                           ('wlat_sum', 'REAL DEFAULT 0'),
                           ('wlon_sum', 'REAL DEFAULT 0'),
                           ('walt_sum', 'REAL DEFAULT 0'),
                           ('uploaded', 'INTEGER DEFAULT 0')):
            if name not in cols:
                self.conn.execute('ALTER TABLE access_points ADD COLUMN %s %s' % (name, decl))
                added.append(name)
        if 'w_sum' in added:  # only when the aggregate columns are newly added
            for bssid, lat, lon, alt, signal in self.conn.execute(
                    'SELECT bssid, lat, lon, alt, signal FROM access_points '
                    'WHERE lat != 0 OR lon != 0').fetchall():
                w = _rssi_weight(signal)
                self.conn.execute(
                    'UPDATE access_points SET obs_count=1, w_sum=?, wlat_sum=?, '
                    'wlon_sum=?, walt_sum=? WHERE bssid=?',
                    (w, (lat or 0.0) * w, (lon or 0.0) * w, (alt or 0.0) * w, bssid))
        # Index the column the recent-AP query orders by, so it stays fast as the
        # database grows.
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_ap_last_seen '
                          'ON access_points(last_seen)')
        self.conn.commit()

    def upsert_ap(self, ap, gps, commit=True):
        """Insert or update an AP record with GPS data."""
        now = datetime.utcnow().isoformat()
        bssid = ap['bssid']

        existing = self.conn.execute(
            'SELECT signal, lat, encryption FROM access_points WHERE bssid = ?', (bssid,)
        ).fetchone()
        is_new = existing is None

        lat = gps.lat if gps and gps.fix_mode >= 2 else 0.0
        lon = gps.lon if gps and gps.fix_mode >= 2 else 0.0
        alt = gps.alt if gps and gps.fix_mode >= 3 else 0.0

        freq = ap.get('frequency', 0)
        auth_mode = ap.get('auth_mode', '')

        have_fix = lat != 0.0
        if existing:
            old_signal = existing[0] or -100
            old_lat = existing[1] or 0.0
            if have_fix and self.average_positions:
                # Weighted-centroid position: fold this sighting into a running
                # RSSI-weighted average, so the stored position blends all
                # sightings. _migrate seeded the aggregates for pre-existing
                # rows; a 0,0 record has none yet, so its first fix simply
                # becomes the average - the back-fill still works.
                w = _rssi_weight(ap['signal'])
                agg = self.conn.execute(
                    'SELECT obs_count, w_sum, wlat_sum, wlon_sum, walt_sum '
                    'FROM access_points WHERE bssid=?', (bssid,)).fetchone()
                oc, ws, wla, wlo, wal = agg if agg else (0, 0.0, 0.0, 0.0, 0.0)
                oc = (oc or 0) + 1
                ws = (ws or 0.0) + w
                wla = (wla or 0.0) + lat * w
                wlo = (wlo or 0.0) + lon * w
                wal = (wal or 0.0) + alt * w
                clat, clon, calt = (wla / ws, wlo / ws, wal / ws) if ws else (lat, lon, alt)
                self.conn.execute('''
                    UPDATE access_points
                    SET ssid=?, channel=?, frequency=?, encryption=?, auth_mode=?,
                        signal=MAX(signal, ?), lat=?, lon=?, alt=?, last_seen=?,
                        obs_count=?, w_sum=?, wlat_sum=?, wlon_sum=?, walt_sum=?
                    WHERE bssid=?
                ''', (ap['ssid'], ap['channel'], freq, ap['encryption'],
                      auth_mode, ap['signal'], clat, clon, calt, now,
                      oc, ws, wla, wlo, wal, bssid))
            elif have_fix and (old_lat == 0.0 or ap['signal'] > old_signal):
                # Strongest-signal position (the default), with 0,0 back-fill: an
                # access point saved without a position gets one as soon as we
                # have a fix, even if this sighting's signal is weaker.
                self.conn.execute('''
                    UPDATE access_points
                    SET ssid=?, channel=?, frequency=?, encryption=?, auth_mode=?,
                        signal=?, lat=?, lon=?, alt=?, last_seen=?
                    WHERE bssid=?
                ''', (ap['ssid'], ap['channel'], freq, ap['encryption'],
                      auth_mode, ap['signal'], lat, lon, alt, now, bssid))
            else:
                self.conn.execute('''
                    UPDATE access_points
                    SET ssid=?, channel=?, frequency=?, encryption=?, auth_mode=?,
                        signal=MAX(signal, ?), last_seen=?
                    WHERE bssid=?
                ''', (ap['ssid'], ap['channel'], freq, ap['encryption'],
                      auth_mode, ap['signal'], now, bssid))
        else:
            self.conn.execute('''
                INSERT INTO access_points
                (bssid, ssid, channel, frequency, encryption, auth_mode,
                 signal, lat, lon, alt, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (bssid, ap['ssid'], ap['channel'], freq, ap['encryption'],
                  auth_mode, ap['signal'], lat, lon, alt, now, now))
            if have_fix and self.average_positions:
                # Seed the aggregates so the next sighting averages correctly.
                w = _rssi_weight(ap['signal'])
                self.conn.execute(
                    'UPDATE access_points SET obs_count=1, w_sum=?, '
                    'wlat_sum=?, wlon_sum=?, walt_sum=? WHERE bssid=?',
                    (w, lat * w, lon * w, alt * w, bssid))

        # Keep the running stats in sync (O(1)).
        new_enc = ap['encryption']
        if is_new:
            self._stats['total'] += 1
            self._bump_enc(new_enc, 1)
        elif existing[2] != new_enc:
            self._bump_enc(existing[2], -1)
            self._bump_enc(new_enc, 1)

        if commit:
            self.conn.commit()
        return is_new

    def mark_handshake(self, bssid):
        """Mark an AP as having a captured handshake. Return True only when
        this call is what set it, so a handshake is rewarded once."""
        row = self.conn.execute(
            'SELECT handshake FROM access_points WHERE bssid=?', (bssid,)).fetchone()
        already = bool(row and row[0])
        self.conn.execute(
            'UPDATE access_points SET handshake=1 WHERE bssid=?', (bssid,))
        self.conn.commit()
        if not already:
            self._stats['handshakes'] += 1
        return not already

    def correlate_open_bssids(self, limit=300):
        """Hidden 'Open' APs inherit encryption from a same-OUI sibling. Bounded
        per call, and the sibling lookup uses GLOB (a prefix pattern SQLite can
        serve from the bssid primary-key index) instead of a non-indexed LIKE,
        so it does not stall the main loop as the database grows. The old version
        scanned the whole table per hidden AP and could freeze it for seconds."""
        open_aps = self.conn.execute(
            "SELECT bssid FROM access_points WHERE encryption='Open' AND ssid='' LIMIT ?",
            (limit,)
        ).fetchall()
        changed = 0
        for (bssid,) in open_aps:
            sibling = self.conn.execute(
                "SELECT encryption, auth_mode FROM access_points "
                "WHERE bssid GLOB ? AND encryption != 'Open' LIMIT 1",
                (bssid[:14] + '*',)
            ).fetchone()
            if sibling:
                self.conn.execute(
                    "UPDATE access_points SET encryption=?, auth_mode=? WHERE bssid=?",
                    (sibling[0], sibling[1], bssid)
                )
                self._bump_enc('Open', -1)
                self._bump_enc(sibling[0], 1)
                changed += 1
        if changed:
            self.conn.commit()
        return changed

    def get_stats(self):
        """Aggregate stats for the dashboard - O(1), kept in sync incrementally.
        'wpa' and 'wpa2' both carry the combined WPA+WPA2 total (the Pager reads
        'wpa2'; the phone status/profile read 'wpa')."""
        return dict(self._stats)

    def clear(self):
        """Delete every access point and re-seed the running stats. Used by the
        'Clear Database' / 'Clear All Data' menu actions. Because get_stats() is
        now O(1) off in-memory counters, deleting rows out from under them (as
        the menu used to, via its own connection) would leave the dashboard
        showing pre-clear totals until restart; re-seeding here keeps them
        truthful."""
        self.conn.execute("DELETE FROM access_points")
        self.conn.commit()
        self._stats = self._compute_stats()

    def _compute_stats(self):
        """Compute the stats from the table once (the seed for the running
        counts). O(N) - called only when a connection opens, never per frame."""
        row = self.conn.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN encryption='Open' THEN 1 ELSE 0 END),
                SUM(CASE WHEN encryption='WEP' THEN 1 ELSE 0 END),
                SUM(CASE WHEN encryption IN ('WPA', 'WPA2') THEN 1 ELSE 0 END),
                SUM(CASE WHEN encryption='WPA3' THEN 1 ELSE 0 END),
                SUM(handshake)
            FROM access_points
        ''').fetchone()
        wpa = row[3] or 0
        return {
            'total': row[0] or 0,
            'open': row[1] or 0,
            'wep': row[2] or 0,
            'wpa': wpa,
            'wpa2': wpa,
            'wpa3': row[4] or 0,
            'handshakes': row[5] or 0,
        }

    def _bump_enc(self, encryption, delta):
        """Adjust the encryption buckets when a row is added or reclassified.
        WPA and WPA2 share the combined 'wpa'/'wpa2' counters; Unknown/other
        encryptions count toward 'total' only."""
        s = self._stats
        if encryption == 'Open':
            s['open'] += delta
        elif encryption == 'WEP':
            s['wep'] += delta
        elif encryption in ('WPA', 'WPA2'):
            s['wpa'] += delta
            s['wpa2'] += delta
        elif encryption == 'WPA3':
            s['wpa3'] += delta

    def get_all_aps(self):
        """Get all APs for export."""
        cursor = self.conn.execute(
            'SELECT * FROM access_points ORDER BY first_seen')
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_aps(self, bssids):
        """Full rows for the given BSSIDs - used to append just the newly-found
        access points to the live Wigle CSV without reloading the whole table."""
        bssids = list(bssids)
        out = []
        for i in range(0, len(bssids), 400):
            chunk = bssids[i:i + 400]
            ph = ','.join('?' * len(chunk))
            cur = self.conn.execute(
                'SELECT * FROM access_points WHERE bssid IN (%s)' % ph, chunk)
            cols = [d[0] for d in cur.description]
            out.extend(dict(zip(cols, row)) for row in cur.fetchall())
        return out

    def commit(self):
        """Commit a batch of writes made with commit=False."""
        self.conn.commit()

    def get_recent_aps(self, limit=150):
        """Recent APs for the phone's radar and network list, newest first.
        A compact projection - only the fields those views need."""
        cur = self.conn.execute(
            'SELECT bssid, ssid, encryption, signal, channel, lat, lon, handshake '
            'FROM access_points ORDER BY last_seen DESC LIMIT ?', (int(limit),))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_unuploaded_aps(self):
        """Access points with a position that have not yet been uploaded to
        Wigle. Rows still at 0,0 are excluded and stay pending until back-filled,
        so each network is uploaded once, when it first has a fix."""
        cur = self.conn.execute(
            'SELECT * FROM access_points '
            'WHERE uploaded = 0 AND (lat != 0 OR lon != 0) ORDER BY first_seen')
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def mark_uploaded(self, bssids):
        """Mark the given BSSIDs as uploaded so they are not sent to Wigle again.
        Only the ones actually written to the uploaded file are passed, so an
        access point found while an upload is in flight stays pending."""
        bssids = list(bssids)
        for i in range(0, len(bssids), 400):
            chunk = bssids[i:i + 400]
            placeholders = ','.join('?' * len(chunk))
            self.conn.execute(
                'UPDATE access_points SET uploaded = 1 WHERE bssid IN (%s)' % placeholders,
                chunk)
        self.conn.commit()
        return len(bssids)

    def checkpoint(self):
        """Fold the write-ahead log back into the main database file and truncate
        it. In WAL mode the -wal file grows as rows are written and is only
        reclaimed by a checkpoint; a periodic reader (the phone's /api/stats on
        its own connection) can keep SQLite's automatic passive checkpoint from
        ever truncating it, so over a long drive the WAL can grow large. Calling
        this on an interval keeps it small, so closing the database (e.g. when a
        new session archives it) never has to checkpoint a huge WAL to slow flash
        in one go - which froze the UI for ~30s. Best-effort: a busy checkpoint
        just does what it can and is retried next interval."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

    def close(self):
        self.conn.close()
