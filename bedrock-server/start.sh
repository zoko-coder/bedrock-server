#!/bin/bash

mkdir -p /data/logs /data/worlds

# ── Graceful shutdown handler ────────────────────────────────────────────────
shutdown() {
    echo "[start.sh] Shutdown signal received..."
    # Try to save BDS world gracefully
    if [ -n "$BDS_PID" ] && kill -0 "$BDS_PID" 2>/dev/null; then
        echo "[start.sh] Stopping BDS (PID $BDS_PID)..."
        kill -TERM "$BDS_PID" 2>/dev/null
        wait "$BDS_PID" 2>/dev/null
    fi
    # Kill all background jobs
    kill $(jobs -p) 2>/dev/null
    wait 2>/dev/null
    echo "[start.sh] Clean shutdown complete."
    exit 0
}
trap shutdown SIGTERM SIGINT

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
view-distance=4
tick-distance=2
player-idle-timeout=30
default-player-permission-level=member
texturepack-required=false
content-log-file-enabled=false
compression-threshold=256
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

# ── ALWAYS enforce low memory settings on every boot ─────────────────────────
sed -i 's/^view-distance=.*/view-distance=4/' /data/server.properties
sed -i 's/^tick-distance=.*/tick-distance=2/' /data/server.properties
sed -i 's/^compression-threshold=.*/compression-threshold=256/' /data/server.properties
echo "[start.sh] Memory-safe settings enforced (view-distance=4, tick-distance=2)"

# ── Delete allowlist files ────────────────────────────────────────────────────
rm -f /data/allowlist.json /data/whitelist.json
echo "[start.sh] Allowlist files removed"

# ── Restore world from Telegram if missing ────────────────────────────────────
LEVEL_NAME=$(grep '^level-name=' /data/server.properties | cut -d'=' -f2)
WORLD_PATH="/data/worlds/$LEVEL_NAME"
if [ ! -d "$WORLD_PATH" ] || [ -z "$(ls -A "$WORLD_PATH" 2>/dev/null)" ]; then
    echo "[start.sh] World missing — attempting Telegram restore..."
    python3 /backup.py restore >> /data/logs/backup.log 2>&1 \
        && echo "[start.sh] ✅ World restored from Telegram" \
        || echo "[start.sh] ❌ No backup found — BDS will generate a fresh world"
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
/usr/local/bin/playit >> /data/logs/playit.log 2>&1 &
echo "[start.sh] playit started (PID $!)"

# ── Start Bedrock Server (foreground — keeps container alive) ─────────────────
cd /data
echo "[start.sh] Starting Bedrock Server..."
export LD_LIBRARY_PATH=.
./bedrock_server >> /data/logs/server.log 2>&1 &
BDS_PID=$!
echo "[start.sh] BDS started (PID $BDS_PID)"

# Wait for BDS to exit (or shutdown signal)
wait "$BDS_PID"
echo "[start.sh] BDS exited."