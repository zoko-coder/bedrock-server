import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 10000))
PMMP_LOG = "/data/logs/server.log"
PLAYIT_LOG = "/data/logs/playit.log"

claim_link = None
tunnel_address = None
recent_lines = []
link_lock = threading.Lock()

def follow_file(path, label):
    global claim_link, tunnel_address

    while not os.path.exists(path):
        time.sleep(1)
        print(f"[server.py] Waiting for {path}...")

    print(f"[server.py] Watching {path}")

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        # Read from BEGINNING first, then tail
        read_from_start = True

        while True:
            line = f.readline()
            if line:
                line = line.strip()
                if line:
                    print(f"[{label}] {line}")
                    with link_lock:
                        recent_lines.append(f"[{label}] {line}")
                        if len(recent_lines) > 200:
                            recent_lines.pop(0)

                        # Claim link — flexible regex
                        match = re.search(r'https?://[^\s]*playit\.gg/claim/[^\s"\')]+', line, re.IGNORECASE)
                        if match:
                            claim_link = match.group(0)
                            print(f"[server.py] Claim link found: {claim_link}")

                        # Tunnel address — catch ply.gg, joinmc.link, etc.
                        addr = re.search(r'([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*\.(?:ply\.gg|joinmc\.link)(?::\d+)?)', line)
                        if addr:
                            tunnel_address = addr.group(1)
                            if ':' not in tunnel_address:
                                tunnel_address += ":19132"
                            print(f"[server.py] Tunnel found: {tunnel_address}")

                # After consuming all existing lines, switch to tail mode
                if read_from_start:
                    pos = f.tell()
                    f.seek(0, 2)
                    if pos >= f.tell():
                        read_from_start = False
                    f.seek(pos)
            else:
                if read_from_start:
                    read_from_start = False
                time.sleep(0.5)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with link_lock:
            link = claim_link
            tunnel = tunnel_address
            lines = list(recent_lines)

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        logs_html = ""
        if lines:
            log_text = "\n".join(lines[-50:])
            logs_html = f"""
            <h3>📄 Live Logs</h3>
            <pre style="background:#111;color:#0f0;padding:16px;
                        border-radius:6px;font-size:12px;
                        overflow-x:auto;white-space:pre-wrap;max-height:400px">{log_text}</pre>
            """

        if tunnel:
            host, port = tunnel.rsplit(":", 1) if ":" in tunnel else (tunnel, "19132")
            html = f"""
            <html><body style="font-family:sans-serif;padding:40px;max-width:800px">
            <h2>✅ Bedrock Server Running!</h2>
            <p>Add this in Minecraft mobile → Play → Servers → Add Server:</p>
            <table style="border-collapse:collapse;margin:16px 0;width:400px">
              <tr><td style="padding:10px;background:#f0f0f0;font-weight:bold">Address</td>
                  <td style="padding:10px;font-family:monospace">{host}</td></tr>
              <tr><td style="padding:10px;background:#f0f0f0;font-weight:bold">Port</td>
                  <td style="padding:10px;font-family:monospace">{port}</td></tr>
            </table>
            <script>setTimeout(()=>location.reload(), 15000)</script>
            {logs_html}
            </body></html>
            """
        elif link:
            html = f"""
            <html><body style="font-family:sans-serif;padding:40px;max-width:800px">
            <h2>🔗 Almost ready — claim your tunnel</h2>
            <p>Click below to claim your playit.gg tunnel, then come back here:</p>
            <a href="{link}" target="_blank"
               style="display:inline-block;font-size:1.1em;background:#5865f2;
                      color:white;padding:12px 24px;border-radius:6px;
                      text-decoration:none;margin:16px 0">
               Claim Tunnel →
            </a>
            <p>Page auto-refreshes every 8 seconds after claiming.</p>
            <script>setTimeout(()=>location.reload(), 8000)</script>
            {logs_html}
            </body></html>
            """
        else:
            html = f"""
            <html><body style="font-family:sans-serif;padding:40px;max-width:800px">
            <h2>⏳ Server Starting...</h2>
            <p>Waiting for playit to generate claim link or tunnel...</p>
            <p>Auto-refreshing every 8 seconds...</p>
            <script>setTimeout(()=>location.reload(), 8000)</script>
            {logs_html}
            </body></html>
            """

        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


threading.Thread(target=follow_file, args=(PMMP_LOG, "PMMP"), daemon=True).start()
threading.Thread(target=follow_file, args=(PLAYIT_LOG, "PLAYIT"), daemon=True).start()

server = HTTPServer(("0.0.0.0", PORT), Handler)
print(f"[server.py] Listening on port {PORT}")
server.serve_forever()