#!/bin/bash

mkdir -p /data/plugins /data/logs

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

# Start web dashboard
python3 /server.py &

sleep 2

# Start playit with a restart loop (if it ever crashes, it comes back)
while true; do
    echo "[start.sh] Starting playit..."
    /usr/local/bin/playit >> /data/logs/playit.log 2>&1
    echo "[start.sh] playit exited, restarting in 5s..."
    sleep 5
done &

# Start PocketMine-MP and redirect its logs so server.py can read them
exec "$PHP_BIN" /server/PocketMine-MP.phar \
    --no-wizard \
    --data=/data \
    --plugins=/data/plugins >> /data/logs/server.log 2>&1