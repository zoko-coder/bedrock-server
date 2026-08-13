#!/bin/bash

mkdir -p /data/logs

# Copy Bedrock Server files to /data on first run
# (worlds, server.properties, and libraries live here)
if [ ! -f /data/bedrock_server ]; then
    echo "[start.sh] Copying Bedrock Server to /data..."
    cp -r /server/bedrock/* /data/
fi

# Create server.properties if missing
if [ ! -f /data/server.properties ]; then
    cat > /data/server.properties << 'EOF'
server-name=My Bedrock Server
gamemode=survival
difficulty=normal
allow-cheats=false
max-players=10
server-port=19132
server-portv6=19133
level-name=Bedrock level
online-mode=true
white-list=false
view-distance=32
tick-distance=4
player-idle-timeout=30
EOF
fi

# Start web dashboard
python3 /server.py &

sleep 2

# Start playit (your working tmux setup)
tmux new-session -d -s playit \
    'export TERM=xterm; /usr/local/bin/playit >> /data/logs/playit.log 2>&1'
tmux pipe-pane -t playit -o 'cat >> /data/logs/playit.log'

echo "[start.sh] playit started"

# Start Bedrock Dedicated Server
cd /data
echo "[start.sh] Starting Bedrock Server..."
LD_LIBRARY_PATH=. ./bedrock_server >> /data/logs/server.log 2>&1