import os
import re
import threading
import time
import subprocess
import json
import signal
import hmac
import hashlib
import secrets
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 10000))
SERVER_LOG = "/data/logs/server.log"
PLAYIT_LOG = "/data/logs/playit.log"
DASHBOARD_USER = os.environ.get("DASHBOARD_USERNAME", "").strip()
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASSWORD", "").strip()
SECRET_KEY = secrets.token_hex(16)


def get_auth_token():
    if not DASHBOARD_USER or not DASHBOARD_PASS:
        return None
    return hmac.new(SECRET_KEY.encode(), f"{DASHBOARD_USER}:{DASHBOARD_PASS}".encode(), hashlib.sha256).hexdigest()


def is_authenticated(headers):
    expected = get_auth_token()
    if not expected:
        return True  # Auth disabled if env vars are not set
    cookie_str = headers.get("Cookie", "")
    if cookie_str:
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_str)
            if "auth_token" in cookie:
                return hmac.compare_digest(cookie["auth_token"].value, expected)
        except Exception:
            pass
    return False


def build_login_html(error_msg=""):
    err_html = f'<div style="color:#ef4444;background:#2a0a0a;border:1px solid #7f1d1d;padding:8px 12px;border-radius:6px;margin-bottom:16px;font-size:13px;">{error_msg}</div>' if error_msg else ''
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard Login</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:#0d0f14; --surface:#161920; --border:#252830; --text:#e2e8f0; --muted:#64748b;
    --blue:#3b82f6; --red:#ef4444; --mono:'IBM Plex Mono',monospace; --sans:'Inter',sans-serif;
  }}
  body {{ background:var(--bg); color:var(--text); font-family:var(--sans); font-size:14px; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:16px; }}
  .login-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:32px; width:100%; max-width:380px; box-shadow:0 10px 25px rgba(0,0,0,0.5); }}
  .header-icon {{ font-size:36px; text-align:center; margin-bottom:8px; }}
  .login-title {{ font-size:20px; font-weight:600; text-align:center; margin-bottom:4px; }}
  .login-sub {{ font-size:12px; color:var(--muted); text-align:center; font-family:var(--mono); margin-bottom:24px; }}
  .form-group {{ margin-bottom:16px; }}
  .form-label {{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); margin-bottom:6px; }}
  .form-input {{ width:100%; background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:10px 14px; color:var(--text); font-family:var(--mono); font-size:14px; outline:none; transition:border 0.15s; }}
  .form-input:focus {{ border-color:var(--blue); }}
  .submit-btn {{ width:100%; background:var(--blue); color:#fff; padding:10px; border:none; border-radius:6px; font-weight:600; font-size:14px; cursor:pointer; margin-top:8px; }}
  .submit-btn:hover {{ opacity:0.9; }}
</style>
</head>
<body>
<div class="login-card">
  <div class="header-icon">🔒</div>
  <div class="login-title">Bedrock Server</div>
  <div class="login-sub">Authentication Required</div>
  {err_html}
  <form method="POST" action="/login">
    <div class="form-group">
      <label class="form-label">Username</label>
      <input type="text" name="username" class="form-input" required autofocus>
    </div>
    <div class="form-group">
      <label class="form-label">Password</label>
      <input type="password" name="password" class="form-input" required>
    </div>
    <button type="submit" class="submit-btn">Login →</button>
  </form>
</div>
</body>
</html>"""

claim_link = None
tunnel_address = None
recent_server_lines = []
recent_playit_lines = []
online_players = []
restart_status = {"restarting": False, "time": 0}
lock = threading.Lock()


# ── Log followers ─────────────────────────────────────────────────────────────

def follow_file(path, label, target_list, max_lines=80):
    global claim_link, tunnel_address, online_players

    while not os.path.exists(path):
        time.sleep(2)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)  # Seek to end of file to read only live new events
        while True:
            line = f.readline()
            if line:
                line = line.strip()
                if not line:
                    continue

                with lock:
                    target_list.append(line)
                    if len(target_list) > max_lines:
                        target_list.pop(0)

                    m = re.search(r'https?://[^\s]*playit\.gg/claim/[^\s"\')]+', line, re.IGNORECASE)
                    if m:
                        claim_link = m.group(0)

                    a = re.search(r'([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*\.(?:ply\.gg|joinmc\.link)(?::\d+)?)', line)
                    if a:
                        tunnel_address = a.group(1)
                        if ':' not in tunnel_address:
                            tunnel_address += ":19132"

                    joined = re.search(r'Player (?:connected|Spawned):\s*(.+?)(?:\s+xuid:|,|$)', line)
                    left   = re.search(r'Player disconnected:\s*(.+?)(?:\s+xuid:|,|$)', line)
                    if joined:
                        name = joined.group(1).strip()
                        if name not in online_players:
                            online_players.append(name)
                    if left:
                        name = left.group(1).strip()
                        if name in online_players:
                            online_players.remove(name)
            else:
                time.sleep(0.4)


START_TIME = time.time()

# ── System metrics ────────────────────────────────────────────────────────────

def get_metrics():
    metrics = {}
    try:
        ram_used_bytes = 0
        ram_total_bytes = 0
        if os.path.exists("/sys/fs/cgroup/memory.current"):
            try:
                with open("/sys/fs/cgroup/memory.current") as f:
                    ram_used_bytes = int(f.read().strip())
                with open("/sys/fs/cgroup/memory.max") as f:
                    val = f.read().strip()
                    ram_total_bytes = 512 * 1024 * 1024 if val == "max" else int(val)
            except:
                pass
        elif os.path.exists("/sys/fs/cgroup/memory/memory.usage_in_bytes"):
            try:
                with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
                    ram_used_bytes = int(f.read().strip())
                with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
                    ram_total_bytes = int(f.read().strip())
            except:
                pass

        if ram_total_bytes <= 0 or ram_total_bytes > 100 * 1024 * 1024 * 1024:
            ram_total_bytes = 512 * 1024 * 1024

        if ram_used_bytes <= 0:
            with open("/proc/meminfo") as f:
                mem = {}
                for line in f:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0])
                total = mem.get("MemTotal", 0) * 1024
                avail = mem.get("MemAvailable", 0) * 1024
                ram_used_bytes = total - avail

        metrics["ram_used_mb"]  = round(ram_used_bytes / (1024 * 1024))
        metrics["ram_total_mb"] = round(ram_total_bytes / (1024 * 1024))
        metrics["ram_pct"]      = min(round(metrics["ram_used_mb"] / metrics["ram_total_mb"] * 100), 100) if metrics["ram_total_mb"] else 0
    except Exception:
        metrics.update({"ram_used_mb": 0, "ram_total_mb": 512, "ram_pct": 0})

    try:
        def read_cpu():
            with open("/proc/stat") as f:
                parts = f.readline().split()
            vals = list(map(int, parts[1:]))
            return vals[3], sum(vals)
        i1, t1 = read_cpu()
        time.sleep(0.3)
        i2, t2 = read_cpu()
        dt = t2 - t1
        metrics["cpu_pct"] = round((1 - (i2 - i1) / dt) * 100) if dt else 0
    except Exception:
        metrics["cpu_pct"] = 0

    try:
        st = os.statvfs("/data")
        total = st.f_blocks * st.f_frsize
        free  = st.f_bavail * st.f_frsize
        used  = total - free
        total_gb = round(total / 1024**3, 1)
        if total_gb > 50:
            result = subprocess.check_output(["du", "-sb", "/data"], text=True, stderr=subprocess.DEVNULL)
            used_bytes = int(result.split()[0])
            metrics["disk_used_gb"]  = round(used_bytes / 1024**3, 2)
            metrics["disk_total_gb"] = 1.0
            metrics["disk_pct"]      = round((used_bytes / (1024**3)) * 100)
        else:
            metrics["disk_used_gb"]  = round(used / 1024**3, 1)
            metrics["disk_total_gb"] = total_gb
            metrics["disk_pct"]      = round(used / total * 100) if total else 0
    except Exception:
        metrics.update({"disk_used_gb": 0, "disk_total_gb": 1.0, "disk_pct": 0})

    try:
        secs = time.time() - START_TIME
        metrics["uptime"] = f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"
    except Exception:
        metrics["uptime"] = "—"

    try:
        out = subprocess.check_output(["pgrep", "-x", "bedrock_server"], text=True)
        metrics["bds_running"] = bool(out.strip())
    except Exception:
        metrics["bds_running"] = False

    try:
        result = subprocess.check_output(["du", "-sh", "/data/worlds"], text=True, stderr=subprocess.DEVNULL)
        metrics["world_size"] = result.split()[0]
    except Exception:
        metrics["world_size"] = "—"

    return metrics


# ── HTML builder ──────────────────────────────────────────────────────────────

def build_html(metrics, players, server_lines, playit_lines, tunnel, claim, restarting):

    if tunnel:
        host, port = (tunnel.rsplit(":", 1) if ":" in tunnel else (tunnel, "19132"))
        status_html = f"""
        <div class="status-banner online">
            <span class="status-dot"></span>
            <span>Server Online</span>
            <span class="tunnel-addr">{host} : {port}</span>
        </div>"""
        connect_html = f"""
        <div class="connect-box">
            <div class="connect-label">Connect in Minecraft → Servers → Add Server</div>
            <div class="connect-row">
                <div class="connect-field"><span class="field-label">Address</span><span class="field-val">{host}</span></div>
                <div class="connect-field"><span class="field-label">Port</span><span class="field-val">{port}</span></div>
            </div>
        </div>"""
    elif claim:
        status_html = f"""
        <div class="status-banner claiming">
            <span class="status-dot"></span>
            <span>Tunnel needs claiming</span>
        </div>"""
        connect_html = f"""
        <div class="connect-box">
            <a href="{claim}" target="_blank" class="claim-btn">Claim Tunnel →</a>
        </div>"""
    else:
        status_html = """
        <div class="status-banner starting">
            <span class="status-dot"></span>
            <span>Starting up…</span>
        </div>"""
        connect_html = ""

    bds_status = "● Running" if metrics["bds_running"] else "○ Stopped"
    bds_class  = "running" if metrics["bds_running"] else "stopped"
    player_items = "".join(f'<li class="player-item">⛏ {p}</li>' for p in players) \
                   or '<li class="player-item empty">No players online</li>'

    restart_banner = ""
    if restarting:
        restart_banner = """
        <div class="status-banner restarting">
            <span class="status-dot"></span>
            <span>Restarting server... Page will refresh automatically.</span>
        </div>"""

    def gauge(pct, color):
        return f'<div class="gauge-track"><div class="gauge-fill" style="width:{pct}%;background:{color}"></div></div>'

    ram_color  = "#ef4444" if metrics["ram_pct"]  > 85 else "#22c55e"
    cpu_color  = "#ef4444" if metrics["cpu_pct"]  > 85 else "#3b82f6"
    disk_color = "#ef4444" if metrics["disk_pct"] > 85 else "#a855f7"

    def log_block(lines, label):
        content = "\n".join(lines[-40:]) if lines else "No output yet…"
        return f"""
        <div class="log-section">
            <div class="log-label">{label}</div>
            <pre class="log-pre" id="log-{label.lower().replace(' ','_')}">{content}</pre>
        </div>"""

    logout_html = '<a href="/logout" style="margin-left:auto;color:var(--red);text-decoration:none;font-size:12px;font-weight:600;border:1px solid #7f1d1d;padding:6px 12px;border-radius:6px;background:#2a0a0a;">Logout 🚪</a>' if (DASHBOARD_USER and DASHBOARD_PASS) else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bedrock Server Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:#0d0f14; --surface:#161920; --border:#252830; --text:#e2e8f0; --muted:#64748b;
    --green:#22c55e; --blue:#3b82f6; --purple:#a855f7; --yellow:#eab308; --red:#ef4444;
    --mono:'IBM Plex Mono',monospace; --sans:'Inter',sans-serif;
  }}
  body {{ background:var(--bg); color:var(--text); font-family:var(--sans); font-size:14px; min-height:100vh; padding:24px 16px 48px; }}
  .header {{ display:flex; align-items:center; gap:12px; margin-bottom:20px; }}
  .header-icon {{ font-size:28px; }}
  .header h1 {{ font-size:18px; font-weight:600; letter-spacing:0.02em; }}
  .header-sub {{ font-size:12px; color:var(--muted); font-family:var(--mono); }}
  .status-banner {{ display:flex; align-items:center; gap:10px; padding:10px 16px; border-radius:8px; font-weight:500; font-size:13px; margin-bottom:20px; border:1px solid var(--border); }}
  .status-banner.online   {{ background:#052e16; border-color:#166534; color:var(--green); }}
  .status-banner.claiming {{ background:#1c1a06; border-color:#854d0e; color:var(--yellow); }}
  .status-banner.starting {{ background:#0c1a2e; border-color:#1e3a5f; color:var(--blue); }}
  .status-banner.restarting {{ background:#2a0a0a; border-color:#7f1d1d; color:var(--red); }}
  .status-dot {{ width:8px; height:8px; border-radius:50%; background:currentColor; flex-shrink:0; animation:pulse 2s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.4}} }}
  .tunnel-addr {{ margin-left:auto; font-family:var(--mono); font-size:12px; opacity:0.85; }}
  .connect-box {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:20px; }}
  .connect-label {{ color:var(--muted); font-size:11px; margin-bottom:12px; text-transform:uppercase; letter-spacing:0.08em; }}
  .connect-row {{ display:flex; gap:12px; flex-wrap:wrap; }}
  .connect-field {{ display:flex; flex-direction:column; gap:4px; background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:10px 14px; flex:1; min-width:160px; }}
  .field-label {{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:0.06em; }}
  .field-val   {{ font-family:var(--mono); font-size:15px; font-weight:600; color:var(--text); }}
  .claim-btn {{ display:inline-block; background:var(--blue); color:#fff; padding:10px 22px; border-radius:6px; text-decoration:none; font-weight:600; font-size:14px; }}
  .restart-btn {{ display:inline-block; background:var(--red); color:#fff; padding:10px 22px; border-radius:6px; border:none; font-weight:600; font-size:14px; cursor:pointer; margin-top:12px; }}
  .restart-btn:hover {{ opacity:0.9; }}
  .restart-btn:disabled {{ background:#555; cursor:not-allowed; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:12px; margin-bottom:20px; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px; }}
  .card-title {{ font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); margin-bottom:12px; }}
  .metric-row {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px; }}
  .metric-val {{ font-family:var(--mono); font-size:22px; font-weight:600; }}
  .metric-sub {{ font-size:11px; color:var(--muted); font-family:var(--mono); }}
  .gauge-track {{ height:4px; background:var(--border); border-radius:2px; overflow:hidden; margin-top:4px; }}
  .gauge-fill {{ height:100%; border-radius:2px; transition:width 0.6s ease; }}
  .pill {{ display:inline-block; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; font-family:var(--mono); }}
  .pill.running {{ background:#052e16; color:var(--green); }}
  .pill.stopped {{ background:#1c0a0a; color:var(--red); }}
  .info-row {{ display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border); font-size:13px; }}
  .info-row:last-child {{ border-bottom:none; }}
  .info-key {{ color:var(--muted); }}
  .info-val {{ font-family:var(--mono); }}
  .player-list {{ list-style:none; }}
  .player-item {{ padding:7px 0; border-bottom:1px solid var(--border); font-family:var(--mono); font-size:13px; color:var(--green); }}
  .player-item:last-child {{ border-bottom:none; }}
  .player-item.empty {{ color:var(--muted); font-style:italic; }}
  .logs-section {{ margin-top:8px; }}
  .log-tabs {{ display:flex; gap:4px; margin-bottom:12px; flex-wrap:wrap; }}
  .log-tab {{ padding:5px 14px; border-radius:6px; font-size:12px; font-family:var(--mono); cursor:pointer; border:1px solid var(--border); background:var(--bg); color:var(--muted); transition:all 0.15s; }}
  .log-tab.active {{ background:var(--surface); color:var(--text); border-color:#3d4455; }}
  .log-section {{ display:none; }}
  .log-section.visible {{ display:block; }}
  .log-label {{ font-size:10px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); margin-bottom:6px; }}
  .log-pre {{ background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:14px; font-family:var(--mono); font-size:11px; line-height:1.6; color:#94a3b8; overflow-x:auto; white-space:pre-wrap; word-break:break-all; max-height:340px; overflow-y:auto; }}
  .footer {{ margin-top:24px; text-align:center; font-size:11px; color:var(--muted); font-family:var(--mono); }}
</style>
</head>
<body>

<div class="header">
  <div class="header-icon">⛏</div>
  <div>
    <h1>Bedrock Server</h1>
    <div class="header-sub">dashboard · auto-refresh 15s</div>
  </div>
  {logout_html}
</div>

{restart_banner}
{status_html}
{connect_html}

<div class="connect-box" style="margin-top:0;">
  <div class="connect-label">Server Control</div>
  <button class="restart-btn" id="restartBtn" onclick="restartServer()">🔄 Restart Server (Kill BDS)</button>
  <div id="restartMsg" style="margin-top:8px;font-size:12px;color:var(--muted);"></div>
</div>

<div class="grid">

  <div class="card">
    <div class="card-title">Memory</div>
    <div class="metric-row">
      <span class="metric-val" style="color:{ram_color}">{metrics['ram_used_mb']} MB</span>
      <span class="metric-sub">of {metrics['ram_total_mb']} MB</span>
    </div>
    {gauge(metrics['ram_pct'], ram_color)}
    <div class="metric-sub" style="margin-top:6px">{metrics['ram_pct']}% used</div>
  </div>

  <div class="card">
    <div class="card-title">CPU</div>
    <div class="metric-row">
      <span class="metric-val" style="color:{cpu_color}">{metrics['cpu_pct']}%</span>
      <span class="metric-sub">utilisation</span>
    </div>
    {gauge(metrics['cpu_pct'], cpu_color)}
    <div class="metric-sub" style="margin-top:6px">uptime {metrics['uptime']}</div>
  </div>

  <div class="card">
    <div class="card-title">Disk  /data</div>
    <div class="metric-row">
      <span class="metric-val" style="color:{disk_color}">{metrics['disk_used_gb']} GB</span>
      <span class="metric-sub">of {metrics['disk_total_gb']} GB</span>
    </div>
    {gauge(metrics['disk_pct'], disk_color)}
    <div class="metric-sub" style="margin-top:6px">world size {metrics['world_size']}</div>
  </div>

  <div class="card">
    <div class="card-title">Server</div>
    <div class="info-row">
      <span class="info-key">BDS process</span>
      <span class="pill {bds_class}">{bds_status}</span>
    </div>
    <div class="info-row">
      <span class="info-key">Players</span>
      <span class="info-val">{len(players)} online</span>
    </div>
    <div class="info-row">
      <span class="info-key">Port</span>
      <span class="info-val">19132 UDP</span>
    </div>
    <div class="info-row">
      <span class="info-key">Mode</span>
      <span class="info-val">online-mode=false</span>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Online Players ({len(players)})</div>
    <ul class="player-list">
      {player_items}
    </ul>
  </div>

</div>

<div class="card logs-section">
  <div class="card-title">Logs</div>
  <div class="log-tabs">
    <button class="log-tab active" onclick="showLog('server')">BDS Server</button>
    <button class="log-tab"       onclick="showLog('playit')">Playit</button>
  </div>
  {log_block(server_lines, 'BDS Server')}
  {log_block(playit_lines, 'Playit')}
</div>

<div class="footer">auto-refreshing · {time.strftime('%H:%M:%S UTC', time.gmtime())}</div>

<script>
  function showLog(name) {{
    document.querySelectorAll('.log-section').forEach(s => s.classList.remove('visible'));
    document.querySelectorAll('.log-tab').forEach(t => t.classList.remove('active'));
    const label = name === 'server' ? 'BDS Server' : 'Playit';
    document.querySelectorAll('.log-section').forEach(s => {{
      if (s.querySelector('.log-label') && s.querySelector('.log-label').textContent === label)
        s.classList.add('visible');
    }});
    event.target.classList.add('active');
  }}
  document.querySelector('.log-section').classList.add('visible');
  document.querySelectorAll('.log-pre').forEach(el => el.scrollTop = el.scrollHeight);

  function restartServer() {{
    const btn = document.getElementById('restartBtn');
    const msg = document.getElementById('restartMsg');
    if (!confirm('Kill bedrock_server? This will restart the entire container and disconnect all players.')) return;
    btn.disabled = true;
    msg.textContent = 'Sending restart signal...';
    fetch('/restart', {{ method: 'POST' }})
      .then(r => r.text())
      .then(t => {{
        msg.textContent = 'Restart triggered. Container will reboot in ~30 seconds...';
        msg.style.color = 'var(--red)';
      }})
      .catch(e => {{
        msg.textContent = 'Restart sent. Connection lost (expected).';
        msg.style.color = 'var(--red)';
      }});
  }}

  setTimeout(() => location.reload(), 15000);
</script>
</body>
</html>"""


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/login":
            if is_authenticated(self.headers):
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                body = build_login_html().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        if self.path == "/logout":
            self.send_response(302)
            self.send_header("Set-Cookie", "auth_token=; Path=/; Max-Age=0")
            self.send_header("Location", "/login")
            self.end_headers()
            return

        if not is_authenticated(self.headers):
            if self.path == "/metrics":
                self.send_response(401)
                self.end_headers()
            else:
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
            return

        if self.path == "/metrics":
            m = get_metrics()
            body = json.dumps(m).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        metrics = get_metrics()

        with lock:
            if not metrics.get("bds_running", False):
                online_players.clear()
            players = list(online_players)
            srv_lines = list(recent_server_lines)
            ply_lines = list(recent_playit_lines)
            tunnel = tunnel_address
            claim  = claim_link
            restarting = restart_status["restarting"] and (time.time() - restart_status["time"] < 60)

        html = build_html(metrics, players, srv_lines, ply_lines, tunnel, claim, restarting)
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/login":
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            params = urllib.parse.parse_qs(body)
            user = params.get('username', [''])[0]
            pwd = params.get('password', [''])[0]

            if DASHBOARD_USER and DASHBOARD_PASS and user == DASHBOARD_USER and pwd == DASHBOARD_PASS:
                token = get_auth_token()
                self.send_response(302)
                self.send_header("Set-Cookie", f"auth_token={token}; Path=/; HttpOnly; SameSite=Lax")
                self.send_header("Location", "/")
                self.end_headers()
            else:
                resp = build_login_html("Invalid username or password").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            return

        if not is_authenticated(self.headers):
            self.send_response(401)
            self.end_headers()
            return

        if self.path == "/restart":
            with lock:
                restart_status["restarting"] = True
                restart_status["time"] = time.time()

            # Kill bedrock_server -> start.sh exits -> Render restarts container
            killed = False
            try:
                pid = int(subprocess.check_output(["pgrep", "-x", "bedrock_server"], text=True).strip().split()[0])
                os.kill(pid, signal.SIGTERM)
                killed = True
                print(f"[server.py] Sent SIGTERM to bedrock_server (PID {pid})")
                time.sleep(3)  # Wait for BDS to flush world files to disk
            except Exception as e:
                print(f"[server.py] Failed to kill BDS: {e}")

            # Pre-restart backup using existing perform_backup() in backup.py
            try:
                print("[server.py] Running pre-restart Telegram backup...")
                from backup import BDSBackup
                bot = BDSBackup()
                bot.startup_check()
                bot.perform_backup()
                print("[server.py] Pre-restart Telegram backup complete!")
            except Exception as e:
                print(f"[server.py] Pre-restart backup error: {e}")

            body = b"Restart triggered with pre-restart backup" if killed else b"Failed to find BDS process"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


# ── Start log watchers ────────────────────────────────────────────────────────

threading.Thread(target=follow_file, args=(SERVER_LOG, "BDS", recent_server_lines), daemon=True).start()
threading.Thread(target=follow_file, args=(PLAYIT_LOG, "PLAYIT", recent_playit_lines), daemon=True).start()

server = HTTPServer(("0.0.0.0", PORT), Handler)
print(f"[server.py] Dashboard on port {PORT}")
server.serve_forever()