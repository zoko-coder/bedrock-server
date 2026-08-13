import os
import re
import threading
import time
import subprocess
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 10000))
SERVER_LOG = "/data/logs/server.log"
PLAYIT_LOG = "/data/logs/playit.log"

claim_link = None
tunnel_address = None
recent_server_lines = []
recent_playit_lines = []
online_players = []
lock = threading.Lock()

# ── Log followers ─────────────────────────────────────────────────────────────

def follow_file(path, label, target_list, max_lines=80):
    global claim_link, tunnel_address, online_players

    while not os.path.exists(path):
        time.sleep(2)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
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

                    # Playit claim link
                    m = re.search(r'https?://[^\s]*playit\.gg/claim/[^\s"\')]+', line, re.IGNORECASE)
                    if m:
                        claim_link = m.group(0)

                    # Tunnel address
                    a = re.search(r'([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*\.(?:ply\.gg|joinmc\.link)(?::\d+)?)', line)
                    if a:
                        tunnel_address = a.group(1)
                        if ':' not in tunnel_address:
                            tunnel_address += ":19132"

                    # Player join/leave (BDS format)
                    joined = re.search(r'Player connected:\s*([^,]+)', line)
                    left   = re.search(r'Player disconnected:\s*([^,]+)', line)
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


# ── System metrics ────────────────────────────────────────────────────────────

def get_metrics():
    metrics = {}

    # RAM
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])
            total = mem.get("MemTotal", 0)
            avail = mem.get("MemAvailable", 0)
            used  = total - avail
            metrics["ram_used_mb"]  = round(used  / 1024)
            metrics["ram_total_mb"] = round(total / 1024)
            metrics["ram_pct"]      = round(used / total * 100) if total else 0
    except Exception:
        metrics.update({"ram_used_mb": 0, "ram_total_mb": 0, "ram_pct": 0})

    # CPU (instant via /proc/stat diff)
    try:
        def read_cpu():
            with open("/proc/stat") as f:
                parts = f.readline().split()
            vals = list(map(int, parts[1:]))
            idle = vals[3]
            total = sum(vals)
            return idle, total

        i1, t1 = read_cpu()
        time.sleep(0.3)
        i2, t2 = read_cpu()
        dt = t2 - t1
        di = i2 - i1
        metrics["cpu_pct"] = round((1 - di / dt) * 100) if dt else 0
    except Exception:
        metrics["cpu_pct"] = 0

    # Disk
    try:
        st = os.statvfs("/data")
        total = st.f_blocks * st.f_frsize
        free  = st.f_bavail * st.f_frsize
        used  = total - free
        metrics["disk_used_gb"]  = round(used  / 1024**3, 1)
        metrics["disk_total_gb"] = round(total / 1024**3, 1)
        metrics["disk_pct"]      = round(used / total * 100) if total else 0
    except Exception:
        metrics.update({"disk_used_gb": 0, "disk_total_gb": 0, "disk_pct": 0})

    # Uptime
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        metrics["uptime"] = f"{h}h {m}m"
    except Exception:
        metrics["uptime"] = "—"

    # BDS process alive?
    try:
        out = subprocess.check_output(["pgrep", "-x", "bedrock_server"], text=True)
        metrics["bds_running"] = bool(out.strip())
    except Exception:
        metrics["bds_running"] = False

    # World size
    try:
        result = subprocess.check_output(
            ["du", "-sh", "/data/worlds"], text=True, stderr=subprocess.DEVNULL
        )
        metrics["world_size"] = result.split()[0]
    except Exception:
        metrics["world_size"] = "—"

    return metrics


# ── HTML builder ──────────────────────────────────────────────────────────────

def build_html(metrics, players, server_lines, playit_lines, tunnel, claim):

    # Status banner
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

    # Players
    bds_status = "● Running" if metrics["bds_running"] else "○ Stopped"
    bds_class  = "running" if metrics["bds_running"] else "stopped"
    player_items = "".join(f'<li class="player-item">⛏ {p}</li>' for p in players) \
                   or '<li class="player-item empty">No players online</li>'

    # Gauge bar helper (inline so no extra calls)
    def gauge(pct, color):
        return f"""
        <div class="gauge-track">
            <div class="gauge-fill" style="width:{pct}%;background:{color}"></div>
        </div>"""

    ram_color  = "#ef4444" if metrics["ram_pct"]  > 85 else "#22c55e"
    cpu_color  = "#ef4444" if metrics["cpu_pct"]  > 85 else "#3b82f6"
    disk_color = "#ef4444" if metrics["disk_pct"] > 85 else "#a855f7"

    # Logs
    def log_block(lines, label):
        content = "\n".join(lines[-40:]) if lines else "No output yet…"
        return f"""
        <div class="log-section">
            <div class="log-label">{label}</div>
            <pre class="log-pre" id="log-{label.lower().replace(' ','_')}">{content}</pre>
        </div>"""

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
    --bg:        #0d0f14;
    --surface:   #161920;
    --border:    #252830;
    --text:      #e2e8f0;
    --muted:     #64748b;
    --green:     #22c55e;
    --blue:      #3b82f6;
    --purple:    #a855f7;
    --yellow:    #eab308;
    --red:       #ef4444;
    --mono:      'IBM Plex Mono', monospace;
    --sans:      'Inter', sans-serif;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    min-height: 100vh;
    padding: 24px 16px 48px;
  }}

  /* ── Header ── */
  .header {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 20px;
  }}
  .header-icon {{ font-size: 28px; }}
  .header h1 {{
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 0.02em;
  }}
  .header-sub {{
    font-size: 12px;
    color: var(--muted);
    font-family: var(--mono);
  }}

  /* ── Status banner ── */
  .status-banner {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    border-radius: 8px;
    font-weight: 500;
    font-size: 13px;
    margin-bottom: 20px;
    border: 1px solid var(--border);
  }}
  .status-banner.online   {{ background: #052e16; border-color: #166534; color: var(--green); }}
  .status-banner.claiming {{ background: #1c1a06; border-color: #854d0e; color: var(--yellow); }}
  .status-banner.starting {{ background: #0c1a2e; border-color: #1e3a5f; color: var(--blue); }}

  .status-dot {{
    width: 8px; height: 8px;
    border-radius: 50%;
    background: currentColor;
    flex-shrink: 0;
    animation: pulse 2s infinite;
  }}
  @keyframes pulse {{
    0%,100% {{ opacity: 1; }}
    50%      {{ opacity: 0.4; }}
  }}

  .tunnel-addr {{
    margin-left: auto;
    font-family: var(--mono);
    font-size: 12px;
    opacity: 0.85;
  }}

  /* ── Connect box ── */
  .connect-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 20px;
  }}
  .connect-label {{ color: var(--muted); font-size: 11px; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.08em; }}
  .connect-row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .connect-field {{
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 14px;
    flex: 1;
    min-width: 160px;
  }}
  .field-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
  .field-val   {{ font-family: var(--mono); font-size: 15px; font-weight: 600; color: var(--text); }}

  .claim-btn {{
    display: inline-block;
    background: var(--blue);
    color: #fff;
    padding: 10px 22px;
    border-radius: 6px;
    text-decoration: none;
    font-weight: 600;
    font-size: 14px;
  }}

  /* ── Grid ── */
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }}

  /* ── Card ── */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }}
  .card-title {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 12px;
  }}

  /* ── Metric rows ── */
  .metric-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
  }}
  .metric-val {{
    font-family: var(--mono);
    font-size: 22px;
    font-weight: 600;
  }}
  .metric-sub {{
    font-size: 11px;
    color: var(--muted);
    font-family: var(--mono);
  }}

  /* ── Gauge ── */
  .gauge-track {{
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    margin-top: 4px;
  }}
  .gauge-fill {{
    height: 100%;
    border-radius: 2px;
    transition: width 0.6s ease;
  }}

  /* ── Status pill ── */
  .pill {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    font-family: var(--mono);
  }}
  .pill.running {{ background: #052e16; color: var(--green); }}
  .pill.stopped {{ background: #1c0a0a; color: var(--red); }}

  /* ── Info rows ── */
  .info-row {{
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }}
  .info-row:last-child {{ border-bottom: none; }}
  .info-key {{ color: var(--muted); }}
  .info-val {{ font-family: var(--mono); }}

  /* ── Players ── */
  .player-list {{ list-style: none; }}
  .player-item {{
    padding: 7px 0;
    border-bottom: 1px solid var(--border);
    font-family: var(--mono);
    font-size: 13px;
    color: var(--green);
  }}
  .player-item:last-child {{ border-bottom: none; }}
  .player-item.empty {{ color: var(--muted); font-style: italic; }}

  /* ── Logs ── */
  .logs-section {{ margin-top: 8px; }}
  .log-tabs {{
    display: flex;
    gap: 4px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }}
  .log-tab {{
    padding: 5px 14px;
    border-radius: 6px;
    font-size: 12px;
    font-family: var(--mono);
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--muted);
    transition: all 0.15s;
  }}
  .log-tab.active {{
    background: var(--surface);
    color: var(--text);
    border-color: #3d4455;
  }}
  .log-section {{ display: none; }}
  .log-section.visible {{ display: block; }}
  .log-label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 6px;
  }}
  .log-pre {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
    font-family: var(--mono);
    font-size: 11px;
    line-height: 1.6;
    color: #94a3b8;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 340px;
    overflow-y: auto;
  }}

  /* ── Footer ── */
  .footer {{
    margin-top: 24px;
    text-align: center;
    font-size: 11px;
    color: var(--muted);
    font-family: var(--mono);
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-icon">⛏</div>
  <div>
    <h1>Bedrock Server</h1>
    <div class="header-sub">dashboard · auto-refresh 15s</div>
  </div>
</div>

{status_html}
{connect_html}

<div class="grid">

  <!-- RAM -->
  <div class="card">
    <div class="card-title">Memory</div>
    <div class="metric-row">
      <span class="metric-val" style="color:{ram_color}">{metrics['ram_used_mb']} MB</span>
      <span class="metric-sub">of {metrics['ram_total_mb']} MB</span>
    </div>
    {gauge(metrics['ram_pct'], ram_color)}
    <div class="metric-sub" style="margin-top:6px">{metrics['ram_pct']}% used</div>
  </div>

  <!-- CPU -->
  <div class="card">
    <div class="card-title">CPU</div>
    <div class="metric-row">
      <span class="metric-val" style="color:{cpu_color}">{metrics['cpu_pct']}%</span>
      <span class="metric-sub">utilisation</span>
    </div>
    {gauge(metrics['cpu_pct'], cpu_color)}
    <div class="metric-sub" style="margin-top:6px">uptime {metrics['uptime']}</div>
  </div>

  <!-- Disk -->
  <div class="card">
    <div class="card-title">Disk  /data</div>
    <div class="metric-row">
      <span class="metric-val" style="color:{disk_color}">{metrics['disk_used_gb']} GB</span>
      <span class="metric-sub">of {metrics['disk_total_gb']} GB</span>
    </div>
    {gauge(metrics['disk_pct'], disk_color)}
    <div class="metric-sub" style="margin-top:6px">world size {metrics['world_size']}</div>
  </div>

  <!-- Server info -->
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

  <!-- Players -->
  <div class="card">
    <div class="card-title">Online Players ({len(players)})</div>
    <ul class="player-list">
      {player_items}
    </ul>
  </div>

</div>

<!-- Logs -->
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
  // Tab switching
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

  // Show first log tab on load
  document.querySelector('.log-section').classList.add('visible');

  // Scroll logs to bottom
  document.querySelectorAll('.log-pre').forEach(el => el.scrollTop = el.scrollHeight);

  // Auto-refresh
  setTimeout(() => location.reload(), 15000);
</script>
</body>
</html>"""


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            # JSON endpoint for quick checks
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
            players = list(online_players)
            srv_lines = list(recent_server_lines)
            ply_lines = list(recent_playit_lines)
            tunnel = tunnel_address
            claim  = claim_link

        html = build_html(metrics, players, srv_lines, ply_lines, tunnel, claim)
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# ── Start log watchers ────────────────────────────────────────────────────────

threading.Thread(
    target=follow_file,
    args=(SERVER_LOG, "BDS", recent_server_lines),
    daemon=True
).start()

threading.Thread(
    target=follow_file,
    args=(PLAYIT_LOG, "PLAYIT", recent_playit_lines),
    daemon=True
).start()

# ── Serve ─────────────────────────────────────────────────────────────────────

server = HTTPServer(("0.0.0.0", PORT), Handler)
print(f"[server.py] Dashboard on port {PORT}")
server.serve_forever()