#!/bin/bash

mkdir -p /data/logs /data/worlds

# ── Copy BDS binaries on first run ──────────────────────────────────────────
if [ ! -f /data/bedrock_server ]; then
    echo "[start.sh] Copying Bedrock Server to /data..."
    cp -r /server/bedrock/* /data/
fi

# ── Accept EULA ──────────────────────────────────────────────────────────────
echo "eula=true" > /data/eula.txt

# ── Create server.properties ONLY if missing ─────────────────────────────────
if [ ! -f /data/server.properties ]; then
    cat > /data/server.properties << 'EOF'
server-name=My Bedrock Server
gamemode=survival
difficulty=normal
allow-cheats=false
max-players=5
server-port=19132
server-portv6=19133
level-name=Bedrock level
online-mode=false
allow-list=false
white-list=false
view-distance=6
tick-distance=4
player-idle-timeout=30
default-player-permission-level=member
texturepack-required=false
content-log-file-enabled=false
compression-threshold=1
server-authoritative-movement=server-auth
player-movement-score-threshold=20
player-movement-distance-threshold=0.3
player-movement-duration-threshold-in-ms=500
correct-player-movement=false
server-authoritative-block-breaking=false
emit-server-telemetry=false
EOF
    echo "[start.sh] Created server.properties"
fi

# ── ALWAYS force open-access settings on every boot ──────────────────────────
# Prevents stale server.properties from blocking connections ("not invited" error)
sed -i 's/^online-mode=.*/online-mode=false/' /data/server.properties
sed -i 's/^allow-list=.*/allow-list=false/' /data/server.properties
sed -i 's/^white-list=.*/white-list=false/' /data/server.properties
echo "[start.sh] Access settings enforced (online-mode=false, allow-list=false)"

# ── Delete allowlist files ────────────────────────────────────────────────────
rm -f /data/allowlist.json /data/whitelist.json
echo "[start.sh] Allowlist files removed"

# ── Restore world from Telegram if missing ────────────────────────────────────
LEVEL_NAME=$(grep '^level-name=' /data/server.properties | cut -d'=' -f2)
WORLD_PATH="/data/worlds/$LEVEL_NAME"
if [ ! -d "$WORLD_PATH" ] || [ -z "$(ls -A "$WORLD_PATH" 2>/dev/null)" ]; then
    echo "[start.sh] World missing — attempting Telegram restore..."
    python3 /backup.py restore >> /data/logs/backup.log 2>&1 \
        && echo "[start.sh] World restored from Telegram" \
        || echo "[start.sh] No backup found — BDS will generate a fresh world"
else
    echo "[start.sh] World found at $WORLD_PATH — skipping restore"
fi

# ── Start web dashboard ───────────────────────────────────────────────────────
python3 /server.py >> /data/logs/dashboard.log 2>&1 &
echo "[start.sh] Web dashboard started"

sleep 2

# ── Start backup daemon ───────────────────────────────────────────────────────
python3 /backup.py >> /data/logs/backup.log 2>&1 &
echo "[start.sh] Backup daemon started"

# ── Start playit tunnel ───────────────────────────────────────────────────────
tmux new-session -d -s playit \
    'export TERM=xterm; /usr/local/bin/playit >> /data/logs/playit.log 2>&1'
tmux pipe-pane -t playit -o 'cat >> /data/logs/playit.log'
echo "[start.sh] playit started"

# ── Start Bedrock Server (foreground — keeps container alive) ─────────────────
cd /data
echo "[start.sh] Starting Bedrock Server..."
export LD_LIBRARY_PATH=.
./bedrock_server >> /data/logs/server.log 2>&1