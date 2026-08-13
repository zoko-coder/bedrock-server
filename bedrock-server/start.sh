#!/bin/bash

mkdir -p /data/logs

# Copy BDS files on first run
if [ ! -f /data/bedrock_server ]; then
    echo "[start.sh] Copying Bedrock Server to /data..."
    cp -r /server/bedrock/* /data/
fi

# Accept EULA (required!)
echo "eula=true" > /data/eula.txt

# Overwrite server.properties with public-friendly settings
cat > /data/server.properties << 'EOF'
server-name=My Bedrock Server
gamemode=survival
difficulty=normal
allow-cheats=false
max-players=20
server-port=19132
server-portv6=19133
level-name=Bedrock level
online-mode=false
white-list=false
allow-list=false
view-distance=32
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
EOF

echo "[start.sh] server.properties updated"

# Start web dashboard
python3 /server.py &

sleep 2

# Start playit
tmux new-session -d -s playit \
    'export TERM=xterm; /usr/local/bin/playit >> /data/logs/playit.log 2>&1'
tmux pipe-pane -t playit -o 'cat >> /data/logs/playit.log'

echo "[start.sh] playit started"

# Start Bedrock Dedicated Server
cd /data
echo "[start.sh] Starting Bedrock Server..."
LD_LIBRARY_PATH=. ./bedrock_server >> /data/logs/server.log 2>&1