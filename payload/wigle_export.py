"""Wigle CSV export and API upload."""

import csv
import os
import urllib.request
import urllib.error
import base64
from datetime import datetime


class WigleWriter:
    """Append-only Wigle CSV writer. Writes new APs incrementally."""

    def __init__(self, export_dir):
        os.makedirs(export_dir, exist_ok=True)
        self.export_dir = export_dir
        self.filepath = None
        self._written_bssids = set()

    def start_session(self):
        """Start a new CSV file with header."""
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.filepath = os.path.join(self.export_dir, f'wigle_{timestamp}.csv')
        self._written_bssids = set()

        with open(self.filepath, 'w', newline='') as f:
            f.write('WigleWifi-1.6,appRelease=1.0,model=pineapplepager,'
                    'release=1.0,device=pineapplepager,display=pagerctl,'
                    'board=mipsel,brand=Hak5,star=Sol,body=3,subBody=0\n')
            writer = csv.writer(f)
            writer.writerow([
                'MAC', 'SSID', 'AuthMode', 'FirstSeen', 'Channel', 'Frequency',
                'RSSI', 'CurrentLatitude', 'CurrentLongitude', 'AltitudeMeters',
                'AccuracyMeters', 'RCOIs', 'MfgrId', 'Type'
            ])

    def resume_session(self, filepath):
        """Resume appending to an existing CSV file."""
        self.filepath = filepath
        self._written_bssids = set()
        # Read existing BSSIDs so we don't duplicate
        if os.path.isfile(filepath):
            try:
                with open(filepath, 'r') as f:
                    reader = csv.reader(f)
                    next(reader)  # skip wigle header
                    next(reader)  # skip column header
                    for row in reader:
                        if row:
                            self._written_bssids.add(row[0])
            except Exception:
                pass

    def append_aps(self, aps):
        """Append new APs to the CSV file. Only writes APs not already in the file."""
        if not self.filepath:
            return 0

        # If the session file was removed out from under us (e.g. the user
        # cleared Wigle files from the Data menu mid-scan), appending would
        # silently recreate it in 'a' mode with no WigleWifi/column header -
        # a malformed CSV that Wigle rejects. Start a fresh, valid session
        # instead; start_session() also resets the de-dup set so the new file
        # gets a clean header and the APs seen from here on.
        if not os.path.isfile(self.filepath):
            self.start_session()

        new_rows = []
        for ap in aps:
            bssid = ap['bssid']
            if bssid in self._written_bssids:
                continue

            lat = ap.get('lat', 0.0) or 0.0
            lon = ap.get('lon', 0.0) or 0.0
            # Skip access points logged before the first GPS fix: they sit at
            # 0,0 (the Gulf of Guinea) and must never reach Wigle. They are NOT
            # marked as written, so once upsert_ap backfills a real position the
            # next pass writes them with their coordinates.
            if lat == 0.0 and lon == 0.0:
                continue

            self._written_bssids.add(bssid)

            auth = ap.get('auth_mode') or _auth_mode_string(ap.get('encryption', 'Open'))
            freq = ap.get('frequency') or _channel_to_freq(ap.get('channel', 0))
            # Format timestamp to match pager format (YYYY-MM-DD HH:MM:SS)
            first_seen = ap.get('first_seen', '')
            if 'T' in first_seen:
                first_seen = first_seen.replace('T', ' ').split('.')[0]
            new_rows.append([
                bssid,
                ap.get('ssid', ''),
                auth,
                first_seen,
                ap.get('channel', 0),
                freq,
                ap.get('signal', -80),
                lat,
                lon,
                ap.get('alt', 0.0) or 0.0,
                0,  # accuracy
                '',  # RCOIs
                '',  # MfgrId
                'WIFI'
            ])

        if new_rows:
            try:
                with open(self.filepath, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerows(new_rows)
            except Exception:
                pass

        return len(new_rows)

    def get_latest_file(self):
        """Find the most recent wigle CSV in the export dir."""
        try:
            csvs = sorted([f for f in os.listdir(self.export_dir)
                           if f.startswith('wigle_') and f.endswith('.csv')])
            if csvs:
                return os.path.join(self.export_dir, csvs[-1])
        except Exception:
            pass
        return None


def export_ap_list(aps, export_dir, filename=None):
    """Write the given access-point dicts to a new Wigle CSV and return the path.
    Access points at 0,0 (logged before a GPS fix) are skipped."""
    os.makedirs(export_dir, exist_ok=True)
    if filename:
        filepath = os.path.join(export_dir, filename)
    else:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(export_dir, f'wigle_{timestamp}.csv')

    with open(filepath, 'w', newline='') as f:
        f.write('WigleWifi-1.6,appRelease=1.0,model=pineapplepager,'
                'release=1.0,device=pineapplepager,display=pagerctl,'
                'board=mipsel,brand=Hak5,star=Sol,body=3,subBody=0\n')
        writer = csv.writer(f)
        writer.writerow([
            'MAC', 'SSID', 'AuthMode', 'FirstSeen', 'Channel', 'Frequency',
            'RSSI', 'CurrentLatitude', 'CurrentLongitude', 'AltitudeMeters',
            'AccuracyMeters', 'RCOIs', 'MfgrId', 'Type'
        ])
        for ap in aps:
            lat = ap.get('lat') or 0.0
            lon = ap.get('lon') or 0.0
            if lat == 0.0 and lon == 0.0:
                continue
            auth = ap.get('auth_mode') or _auth_mode_string(ap.get('encryption', 'Open'))
            freq = ap.get('frequency') or _channel_to_freq(ap.get('channel', 0))
            first_seen = ap.get('first_seen', '')
            if 'T' in first_seen:
                first_seen = first_seen.replace('T', ' ').split('.')[0]
            writer.writerow([
                ap['bssid'], ap.get('ssid', ''), auth, first_seen,
                ap.get('channel', 0), freq, ap.get('signal', -80),
                lat, lon, ap.get('alt', 0.0) or 0.0,
                0, '', '', 'WIFI'
            ])

    return filepath


def export_csv(db, export_dir, filename=None):
    """Full export — every AP in the DB to a new CSV (for a manual, complete
    export). The incremental Wigle upload uses export_ap_list on the pending
    rows instead, so networks are not re-sent."""
    return export_ap_list(db.get_all_aps(), export_dir, filename)


def upload_to_wigle(filepath, api_name, api_token):
    """Upload a Wigle CSV file to wigle.net.
    Args: filepath, api_name (AID...), api_token
    Returns (success: bool, message: str)."""
    if not api_name or not api_token:
        return False, "API name and token required"
    if not os.path.isfile(filepath):
        return False, "File not found"

    url = 'https://api.wigle.net/api/v2/file/upload'

    with open(filepath, 'rb') as f:
        file_data = f.read()

    boundary = '----WardrivePagerBoundary'
    filename = os.path.basename(filepath)

    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f'Content-Type: text/csv\r\n\r\n'
    ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()

    # Wigle Basic Auth: API Name as username, API Token as password
    auth = base64.b64encode(f'{api_name}:{api_token}'.encode()).decode()

    headers = {
        'Authorization': f'Basic {auth}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    }

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = resp.read().decode()
            if resp.status == 200:
                return True, "Upload successful"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, str(e)


def _channel_to_freq(channel):
    """Best-effort WiFi channel -> MHz. Only a fallback for the rare scan that
    reports no frequency; the scanner normally supplies the real one. Channel
    numbers alone cannot distinguish 2.4 from 6 GHz, so unknown channels return
    0 rather than a wrong value."""
    if 1 <= channel <= 13:
        return 2407 + channel * 5
    if channel == 14:
        return 2484
    if 36 <= channel <= 177:
        return 5000 + channel * 5
    return 0


def _auth_mode_string(encryption):
    """Convert encryption type to Wigle AuthMode format."""
    modes = {
        'Open': '[ESS]',
        'WEP': '[WEP][ESS]',
        'WPA': '[WPA-PSK-TKIP][ESS]',
        'WPA2': '[WPA2-PSK-CCMP][ESS]',
        'WPA3': '[WPA3-SAE-CCMP][ESS]',
    }
    return modes.get(encryption, '[ESS]')
