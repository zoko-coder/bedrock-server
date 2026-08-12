#!/bin/bash

mkdir -p /data/plugins /data/logs /data/playit-config

# Persist playit config across restarts
export HOME=/data
mkdir -p /data/.config
ln -sf /data/playit-config /data/.config/playit 2>/dev/null || true

if [ ! -f /data/server.properties ]; then
    cat > /data/server.properties << 'EOF'
motd=My Bedrock Server
server-port=19132
max-players=10
gamemode=survival
difficulty=normal
EOF
fi

PHP_BIN=$(find /server/bin -name "php" -type f | head -1)
echo "Using PHP binary: $PHP_BIN"

# Start web dashboard FIRST so it catches all playit output
python3 /server.py &

# Small delay to ensure server.py is watching before playit writes
sleep 2

# Run playit and capture ALL output
echo "[start.sh] Starting playit..." >> /data/logs/playit.log
/usr/local/bin/playit >> /data/logs/playit.log 2>&1 &
PLAYIT_PID=$!
echo "[start.sh] playit PID: $PLAYIT_PID"

# Also dump the first 50 lines of playit output for debugging
sleep 5
echo "[start.sh] playit log so far:" >> /data/logs/playit.log
tail -n 20 /data/logs/playit.log >> /data/logs/playit.log 2>/dev/null || true

exec "$PHP_BIN" /server/PocketMine-MP.phar \
    --no-wizard \
    --data=/data \
    --plugins=/data/plugins