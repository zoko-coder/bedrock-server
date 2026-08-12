import os
import re
import threading
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
    import time

    while not os.path.exists(path):
        time.sleep(2)
        print(f"[server.py] Waiting for {path}...")

    print(f"[server.py] Watching {path}")

    with open(path, "r") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                line = line.strip()
                print(f"[{label}] {line}")
                with link_lock:
                    recent_lines.append(f"[{label}] {line}")
                    if len(recent_lines) > 100:
                        recent_lines.pop(0)

                    # Claim link
                    match = re.search(r'(https://playit\.gg/claim/[^\s]+)', line)
                    if match:
                        claim_link = match.group(1)
                        print(f"[server.py] Claim link: {claim_link}")

                    # Tunnel address
                    addr = re.search(r'(\S+\.ply\.gg:\d+)', line)
                    if addr:
                        tunnel_address = addr.group(1)
                        print(f"[server.py] Tunnel: {tunnel_address}")
            else:
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
            log_text = "\n".join(lines[-40:])
            logs_html = f"""
            <h3>📄 Live Logs</h3>
            <pre style="background:#111;color:#0f0;padding:16px;
                        border-radius:6px;font-size:12px;
                        overflow-x:auto;white-space:pre-wrap">{log_text}</pre>
            """

        if tunnel:
            html = f"""
            <html><body style="font-family:sans-serif;padding:40px;max-width:800px">
            <h2>✅ Bedrock Server Running!</h2>
            <p>Add this in Minecraft mobile → Play → Servers → Add Server:</p>
            <table style="border-collapse:collapse;margin:16px 0;width:400px">
              <tr>
                <td style="padding:10px;background:#f0f0f0;font-weight:bold">Address</td>
                <td style="padding:10px;font-family:monospace">{tunnel.split(':')[0]}</td>
              </tr>
              <tr>
                <td style="padding:10px;background:#f0f0f0;font-weight:bold">Port</td>
                <td style="padding:10px;font-family:monospace">{tunnel.split(':')[1]}</td>
              </tr>
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
            <p>Auto-refreshing every 8 seconds...</p>
            <script>setTimeout(()=>location.reload(), 8000)</script>
            {logs_html}
            </body></html>
            """

        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


# Watch both log files in separate threads
threading.Thread(target=follow_file, args=(PMMP_LOG, "PMMP"), daemon=True).start()
threading.Thread(target=follow_file, args=(PLAYIT_LOG, "PLAYIT"), daemon=True).start()

server = HTTPServer(("0.0.0.0", PORT), Handler)
print(f"[server.py] Listening on port {PORT}")
server.serve_forever()