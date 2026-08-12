import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 10000))
LOG_PATH = "/data/logs/server.log"

claim_link = None
recent_lines = []
link_lock = threading.Lock()

def watch_log():
    global claim_link, recent_lines
    import time

    while not os.path.exists(LOG_PATH):
        time.sleep(2)
        print(f"[server.py] Waiting for log at {LOG_PATH}...")

    print("[server.py] Log found, watching...")

    with open(LOG_PATH, "r") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                line = line.strip()
                print(f"[LOG] {line}")
                with link_lock:
                    recent_lines.append(line)
                    if len(recent_lines) > 50:
                        recent_lines.pop(0)
                    match = re.search(r'(https://playit\.gg/[^\s]+)', line)
                    if match:
                        claim_link = match.group(1)
                        print(f"[server.py] Claim link: {claim_link}")
            else:
                time.sleep(1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with link_lock:
            link = claim_link
            lines = list(recent_lines)

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        logs_html = ""
        if lines:
            log_text = "\n".join(lines[-30:])
            logs_html = f"""
            <h3>📄 Recent Logs</h3>
            <pre style="background:#111;color:#0f0;padding:16px;
                        border-radius:6px;font-size:12px;
                        overflow-x:auto;white-space:pre-wrap">{log_text}</pre>
            """

        if link:
            html = f"""
            <html><body style="font-family:sans-serif;padding:40px;max-width:800px">
            <h2>✅ Bedrock Server Running!</h2>
            <p>Open Minecraft on your phone, go to <strong>Servers</strong> and add:</p>
            <table style="border-collapse:collapse;margin:16px 0">
              <tr>
                <td style="padding:8px;background:#f0f0f0"><strong>Address</strong></td>
                <td style="padding:8px">From playit.gg dashboard after claiming</td>
              </tr>
              <tr>
                <td style="padding:8px;background:#f0f0f0"><strong>Port</strong></td>
                <td style="padding:8px">19132</td>
              </tr>
            </table>
            <p><strong>👇 Claim your playit.gg tunnel first:</strong></p>
            <a href="{link}" target="_blank"
               style="font-size:1.1em;background:#5865f2;color:white;
                      padding:12px 24px;border-radius:6px;text-decoration:none">
               Claim Tunnel →
            </a>
            {logs_html}
            </body></html>
            """
        else:
            html = f"""
            <html><body style="font-family:sans-serif;padding:40px;max-width:800px">
            <h2>⏳ Server Starting...</h2>
            <p>Waiting for playit.gg claim link. Auto-refreshing every 10 seconds...</p>
            <script>setTimeout(()=>location.reload(), 10000)</script>
            {logs_html}
            </body></html>
            """

        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


watcher = threading.Thread(target=watch_log, daemon=True)
watcher.start()

server = HTTPServer(("0.0.0.0", PORT), Handler)
print(f"[server.py] Listening on port {PORT}")
server.serve_forever()