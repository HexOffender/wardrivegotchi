"""Web server for wardrive — loot downloads, live stats, settings."""

import os
import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from config import LOOT_DIR, EXPORT_DIR, CAPTURE_DIR, DB_PATH, load_config, save_config


class LootHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self._serve_page()
        elif self.path == '/api/files':
            self._json_response(self._get_files())
        elif self.path == '/api/stats':
            self._json_response(self._get_stats())
        elif self.path == '/api/status':
            self._json_response(self._get_control_status())
        elif self.path == '/api/settings':
            self._json_response(self._safe_settings())
        elif self.path.startswith('/download/'):
            self._serve_file(self.path[10:])
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/settings':
            self._save_settings()
        elif self.path == '/api/command':
            self._handle_command()
        else:
            self.send_error(404)

    def _control(self):
        """The control channel, or None when the server has no app behind it."""
        return getattr(self.server, 'control', None)

    def _get_control_status(self):
        """Live status for the phone control. Safe to serve without a token:
        it carries no secrets, only what the dashboard already shows."""
        control = self._control()
        if control is None:
            return {'available': False}
        status = control.snapshot()
        status['available'] = True
        status['control_enabled'] = control.enabled
        return status

    def _read_body(self):
        """Read a request body whether it arrives with a Content-Length or as
        chunked transfer encoding. The GPS server proxies the phone's control
        POSTs and Go forwards them chunked, which BaseHTTPRequestHandler does
        not de-chunk on its own - without this the body reads empty and every
        command looks like it has no action."""
        te = self.headers.get('Transfer-Encoding', '')
        if 'chunked' in te.lower():
            data = b''
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                try:
                    size = int(line.strip().split(b';', 1)[0], 16)
                except ValueError:
                    break
                if size == 0:
                    self.rfile.readline()  # trailing CRLF after the last chunk
                    break
                data += self.rfile.read(size)
                self.rfile.readline()      # CRLF after each chunk
            return data
        length = int(self.headers.get('Content-Length', 0) or 0)
        return self.rfile.read(length) if length else b''

    def _handle_command(self):
        """Queue a scan command from the phone. Requires the shared token."""
        control = self._control()
        if control is None or not control.enabled:
            self._json_response({'status': 'error', 'message': 'control is disabled'}, 403)
            return

        # The token comes in a header so it never lands in a URL or a log.
        if not control.authorised(self.headers.get('X-Control-Token', '')):
            self._json_response({'status': 'error', 'message': 'bad token'}, 401)
            return

        try:
            raw = self._read_body()
            data = json.loads(raw.decode()) if raw else {}
        except Exception:
            self._json_response({'status': 'error', 'message': 'bad request'}, 400)
            return

        action = data.get('action', '')
        allowed = ('start', 'pause', 'resume', 'stop', 'export', 'upload', 'set_bands', 'buy', 'equip', 'unequip')
        if action not in allowed:
            self._json_response({'status': 'error', 'message': 'unknown action'}, 400)
            return

        if control.submit(action, data.get('params')):
            self._json_response({'status': 'ok', 'queued': action})
        else:
            self._json_response({'status': 'error', 'message': 'busy'}, 503)

    def _safe_settings(self):
        """Settings for the page with secrets redacted, so the Wigle token and
        the control token are never sent over the unauthenticated, plain-HTTP
        LAN. A blank secret on save is ignored (see _save_settings), so the
        stored value is kept."""
        cfg = dict(load_config())
        for secret in ('wigle_api_token', 'control_token'):
            if cfg.get(secret):
                cfg[secret] = ''
        return cfg

    def _save_settings(self):
        body = self._read_body().decode()
        try:
            data = json.loads(body)
            config = load_config()
            # Only update known keys
            for key in ('wigle_api_name', 'wigle_api_token', 'geiger_sound', 'web_server', 'brightness',
                        'screen_timeout', 'gps_enabled', 'gps_device', 'gps_baud',
                        'scan_2_4ghz', 'scan_5ghz', 'scan_6ghz', 'scan_mode',
                        'scan_interface', 'capture_interface', 'capture_enabled'):
                if key in data:
                    # A blank token means the redacted field was left untouched;
                    # keep the stored one instead of wiping it.
                    if key == 'wigle_api_token' and not data[key]:
                        continue
                    config[key] = data[key]
            save_config(config)
            self._json_response({'status': 'ok'})
        except Exception as e:
            self._json_response({'status': 'error', 'message': str(e)}, 400)

    def _get_stats(self):
        import sqlite3
        stats = {'total': 0, 'open': 0, 'wep': 0, 'wpa': 0, 'wpa3': 0, 'handshakes': 0}
        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute('''SELECT COUNT(*),
                SUM(CASE WHEN encryption='Open' THEN 1 ELSE 0 END),
                SUM(CASE WHEN encryption='WEP' THEN 1 ELSE 0 END),
                SUM(CASE WHEN encryption IN ('WPA','WPA2') THEN 1 ELSE 0 END),
                SUM(CASE WHEN encryption='WPA3' THEN 1 ELSE 0 END),
                SUM(handshake)
                FROM access_points''').fetchone()
            stats = {'total': row[0] or 0, 'open': row[1] or 0, 'wep': row[2] or 0,
                     'wpa': row[3] or 0, 'wpa3': row[4] or 0, 'handshakes': row[5] or 0}
            # Recent APs
            recent = conn.execute(
                'SELECT bssid,ssid,encryption,auth_mode,signal,channel,frequency FROM access_points ORDER BY last_seen DESC LIMIT 20'
            ).fetchall()
            stats['recent_aps'] = [
                {'bssid': r[0], 'ssid': r[1], 'encryption': r[2], 'auth_mode': r[3],
                 'signal': r[4], 'channel': r[5], 'frequency': r[6]} for r in recent
            ]
            conn.close()
        except Exception:
            pass
        return stats

    def _get_files(self):
        return {
            'wigle': self._list_dir(EXPORT_DIR, '.csv'),
            'gpx': self._list_dir(EXPORT_DIR, '.gpx'),
            'pcap': self._list_dir(CAPTURE_DIR, '.pcap'),
            'hashcat': self._list_dir(CAPTURE_DIR, '.22000'),
        }

    def _serve_file(self, path):
        filepath = os.path.join(LOOT_DIR, path)
        filepath = os.path.realpath(filepath)
        if not filepath.startswith(os.path.realpath(LOOT_DIR)):
            self.send_error(403)
            return
        if not os.path.isfile(filepath):
            self.send_error(404)
            return
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(filesize))
        self.end_headers()
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _serve_page(self):
        html = PAGE_HTML
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _list_dir(self, directory, extension):
        files = []
        if not os.path.isdir(directory):
            return files
        for name in sorted(os.listdir(directory), reverse=True):
            if name.endswith(extension):
                path = os.path.join(directory, name)
                size = os.path.getsize(path)
                files.append({'name': name, 'size': self._fmt_size(size)})
        return files

    def _fmt_size(self, size):
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        return f"{size / (1024 * 1024):.1f}MB"

    def log_message(self, format, *args):
        pass


PAGE_HTML = '''<!DOCTYPE html>
<html>
<head>
<title>Wardrive</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #c9d1d9; font-family: 'Courier New', monospace; }
.header { background: #161b22; padding: 15px 20px; border-bottom: 1px solid #30363d; }
.header h1 { color: #58a6ff; font-size: 20px; }
.tabs { display: flex; background: #161b22; border-bottom: 1px solid #30363d; }
.tab { padding: 12px 20px; cursor: pointer; color: #8b949e; border-bottom: 2px solid transparent; }
.tab:hover { color: #c9d1d9; }
.tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }
.content { padding: 20px; max-width: 800px; margin: 0 auto; }
.panel { display: none; }
.panel.active { display: block; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 12px; }
.card h3 { color: #58a6ff; margin-bottom: 10px; }
.stat { display: inline-block; margin: 5px 15px 5px 0; }
.stat .val { font-size: 24px; font-weight: bold; color: #58a6ff; }
.stat .lbl { font-size: 12px; color: #8b949e; }
.file { padding: 8px 0; border-bottom: 1px solid #21262d; display: flex; justify-content: space-between; }
.file a { color: #58a6ff; text-decoration: none; }
.file a:hover { color: #79c0ff; }
.file .sz { color: #8b949e; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px; color: #8b949e; border-bottom: 1px solid #30363d; }
td { padding: 6px 8px; border-bottom: 1px solid #21262d; }
.open { color: #f85149; } .wep { color: #d29922; } .wpa { color: #58a6ff; } .wpa3 { color: #3fb950; }
input, select { background: #0d1117; color: #c9d1d9; border: 1px solid #30363d; padding: 8px; border-radius: 4px; font-family: monospace; }
button { background: #238636; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-family: monospace; }
button:hover { background: #2ea043; }
.toggle { cursor: pointer; padding: 4px 12px; border-radius: 12px; display: inline-block; }
.toggle.on { background: #238636; color: #fff; }
.toggle.off { background: #30363d; color: #8b949e; }
.setting-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #21262d; }
.empty { color: #484f58; font-style: italic; padding: 10px 0; }
</style>
</head>
<body>
<div class="header"><h1>Wardrive</h1></div>
<div class="tabs">
  <div class="tab active" onclick="showTab('dashboard')">Dashboard</div>
  <div class="tab" onclick="showTab('loot')">Loot</div>
  <div class="tab" onclick="showTab('settings')">Settings</div>
</div>
<div class="content">

<!-- Dashboard -->
<div id="dashboard" class="panel active">
  <div class="card">
    <h3>Stats</h3>
    <div class="stat"><div class="val" id="s-total">-</div><div class="lbl">Total APs</div></div>
    <div class="stat"><div class="val open" id="s-open">-</div><div class="lbl">Open</div></div>
    <div class="stat"><div class="val wep" id="s-wep">-</div><div class="lbl">WEP</div></div>
    <div class="stat"><div class="val wpa" id="s-wpa">-</div><div class="lbl">WPA</div></div>
    <div class="stat"><div class="val wpa3" id="s-wpa3">-</div><div class="lbl">WPA3</div></div>
    <div class="stat"><div class="val" id="s-hs" style="color:#d29922">-</div><div class="lbl">Handshakes</div></div>
  </div>
  <div class="card">
    <h3>Recent APs</h3>
    <table>
      <thead><tr><th>BSSID</th><th>SSID</th><th>Auth</th><th>Signal</th><th>CH</th></tr></thead>
      <tbody id="ap-table"></tbody>
    </table>
  </div>
</div>

<!-- Loot -->
<div id="loot" class="panel">
  <div class="card"><h3>Wigle CSV Files</h3><div id="wigle-files"></div></div>
  <div class="card"><h3>GPX Tracks</h3><div id="gpx-files"></div></div>
  <div class="card"><h3>Packet Captures</h3><div id="pcap-files"></div></div>
  <div class="card"><h3>Hashcat Files</h3><div id="hashcat-files"></div></div>
</div>

<!-- Settings -->
<div id="settings" class="panel">
  <div class="card">
    <h3>Wigle API Credentials</h3>
    <div style="margin-top:8px">
      <input type="text" id="api-name" placeholder="API Name (AID...)" style="width:100%;margin-bottom:8px"><br>
      <input type="text" id="api-token" placeholder="API Token" style="width:100%;margin-bottom:8px"><br>
      <button onclick="saveApiCreds()">Save</button>
      <span id="key-status" style="margin-left:10px;color:#8b949e"></span>
    </div>
  </div>
  <div class="card">
    <h3>Device</h3>
    <div id="device-settings"></div>
  </div>
  <div class="card">
    <h3>Scan</h3>
    <div id="scan-settings"></div>
  </div>
  <div class="card">
    <h3>GPS</h3>
    <div id="gps-settings"></div>
  </div>
</div>

</div>
<script>
function showTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(name).classList.add('active');
  event.target.classList.add('active');
}

function fetchStats() {
  fetch('/api/stats').then(r=>r.json()).then(d => {
    document.getElementById('s-total').textContent = d.total;
    document.getElementById('s-open').textContent = d.open;
    document.getElementById('s-wep').textContent = d.wep;
    document.getElementById('s-wpa').textContent = d.wpa;
    document.getElementById('s-wpa3').textContent = d.wpa3;
    document.getElementById('s-hs').textContent = d.handshakes;
    var tb = document.getElementById('ap-table');
    tb.innerHTML = '';
    (d.recent_aps||[]).forEach(ap => {
      var cls = ap.encryption=='Open'?'open':ap.encryption=='WEP'?'wep':ap.encryption=='WPA3'?'wpa3':'wpa';
      tb.innerHTML += '<tr><td>'+ap.bssid+'</td><td>'+(ap.ssid||'<i>hidden</i>')+'</td><td class="'+cls+'">'+(ap.auth_mode||ap.encryption)+'</td><td>'+ap.signal+'</td><td>'+ap.channel+'</td></tr>';
    });
  }).catch(()=>{});
}

function fetchFiles() {
  fetch('/api/files').then(r=>r.json()).then(d => {
    ['wigle','gpx','pcap','hashcat'].forEach(type => {
      var el = document.getElementById(type+'-files');
      var files = d[type]||[];
      if(!files.length) { el.innerHTML='<div class="empty">None</div>'; return; }
      var dir = (type=='wigle'||type=='gpx') ? 'exports' : 'captures';
      el.innerHTML = files.map(f =>
        '<div class="file"><a href="/download/'+dir+'/'+f.name+'">'+f.name+'</a><span class="sz">'+f.size+'</span></div>'
      ).join('');
    });
  }).catch(()=>{});
}

function fetchSettings() {
  fetch('/api/settings').then(r=>r.json()).then(c => {
    document.getElementById('api-name').value = c.wigle_api_name||'';
    document.getElementById('api-token').value = c.wigle_api_token||'';
    var dev = document.getElementById('device-settings');
    dev.innerHTML = settingToggle('Sound','geiger_sound',c.geiger_sound)
      + settingToggle('Web Server','web_server',c.web_server)
      + settingRow('Brightness',c.brightness+'%')
      + settingRow('Screen Off',c.screen_timeout>0?c.screen_timeout+'s':'Never');
    var scan = document.getElementById('scan-settings');
    scan.innerHTML = settingRow('Mode',c.scan_mode)
      + settingRow('Scan Interface',c.scan_interface)
      + settingRow('Capture Interface',c.capture_interface)
      + settingToggle('2.4GHz','scan_2_4ghz',c.scan_2_4ghz)
      + settingToggle('5GHz','scan_5ghz',c.scan_5ghz)
      + settingToggle('6GHz','scan_6ghz',c.scan_6ghz)
      + settingToggle('Handshake Capture','capture_enabled',c.capture_enabled);
    var gps = document.getElementById('gps-settings');
    gps.innerHTML = settingToggle('GPS','gps_enabled',c.gps_enabled)
      + settingRow('Device',c.gps_device)
      + settingRow('Baud',c.gps_baud);
  }).catch(()=>{});
}

function settingToggle(label, key, val) {
  var cls = val?'on':'off';
  return '<div class="setting-row"><span>'+label+'</span><span class="toggle '+cls+'" onclick="toggleSetting(this,\\''+key+'\\','+!val+')">'+((val)?'ON':'OFF')+'</span></div>';
}
function settingRow(label, val) {
  return '<div class="setting-row"><span>'+label+'</span><span style="color:#58a6ff">'+val+'</span></div>';
}
function toggleSetting(el, key, val) {
  var data = {}; data[key] = val;
  fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
  .then(()=>fetchSettings());
}
function saveApiCreds() {
  var name = document.getElementById('api-name').value;
  var token = document.getElementById('api-token').value;
  fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({wigle_api_name:name,wigle_api_token:token})})
  .then(r=>r.json()).then(d=>{document.getElementById('key-status').textContent='Saved';setTimeout(()=>document.getElementById('key-status').textContent='',2000);});
}

fetchStats(); fetchFiles(); fetchSettings();
setInterval(fetchStats, 5000);
setInterval(fetchFiles, 30000);
</script>
</body>
</html>'''


class WebServer(threading.Thread):
    def __init__(self, port=8888, control=None):
        super().__init__(daemon=True)
        self.port = port
        self.control = control
        self.server = None

    def run(self):
        try:
            # Try to open firewall (may not be needed on all setups)
            import subprocess
            subprocess.run(['iptables', '-I', 'INPUT', '-p', 'tcp', '--dport', str(self.port), '-j', 'ACCEPT'],
                           capture_output=True, timeout=3)
        except Exception:
            pass
        try:
            self.server = HTTPServer(('0.0.0.0', self.port), LootHandler)
            self.server.control = self.control
            self.server.serve_forever()
        except OSError as e:
            # Port in use — try alternate
            try:
                self.port = self.port + 1
                self.server = HTTPServer(('0.0.0.0', self.port), LootHandler)
                self.server.control = self.control
                self.server.serve_forever()
            except Exception:
                pass
        except Exception:
            pass

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
