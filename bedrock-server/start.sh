#!/bin/bash

mkdir -p /data/logs /data/worlds

# Copy BDS binaries on first run only
if [ ! -f /data/bedrock_server ]; then
    echo "[start.sh] Copying Bedrock Server to /data..."
    cp -r /server/bedrock/* /data/
fi

# Accept EULA
echo "eula=true" > /data/eula.txt

# Create server.properties ONLY if missing (don't overwrite existing world settings!)
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
white-list=false
allow-list=false
view-distance=6
tick-distance=2
player-idle-timeout=5
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
EOF
    echo "[start.sh] Created server.properties"
fi

LEVEL_NAME=$(grep '^level-name=' /data/server.properties | cut -d'=' -f2)
WORLD_PATH="/data/worlds/$LEVEL_NAME"
echo "[start.sh] World path: $WORLD_PATH"

# Start web dashboard
python3 /server.py &

sleep 2

# Restore world from Telegram if missing
if [ ! -d "$WORLD_PATH" ] || [ -z "$(ls -A "$WORLD_PATH" 2>/dev/null)" ]; then
    echo "[start.sh] World missing, checking Telegram..."
    python3 /backup.py restore
    if [ $? -eq 0 ]; then
        echo "[start.sh] World restored"
    else
        echo "[start.sh] No backup — BDS will create new world"
    fi
fi

# Start playit
tmux new-session -d -s playit \
    'export TERM=xterm; /usr/local/bin/playit >> /data/logs/playit.log 2>&1'
tmux pipe-pane -t playit -o 'cat >> /data/logs/playit.log'
echo "[start.sh] playit started"

# Start backup daemon
python3 /backup.py &
echo "[start.sh] Backup daemon started"

# Start Bedrock Server
cd /data
echo "[start.sh] Starting Bedrock Server..."
LD_LIBRARY_PATH=. ./bedrock_server >> /data/logs/server.log 2>&1