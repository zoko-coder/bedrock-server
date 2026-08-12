#!/bin/bash

mkdir -p /data/plugins /data/logs

if [ ! -f /data/server.properties ]; then
    cat > /data/server.properties << EOF
motd=My Bedrock Server
server-port=19132
max-players=10
gamemode=survival
difficulty=normal
EOF
fi

# Auto-find PHP binary wherever it extracted
PHP_BIN=$(find /server/bin -name "php" -type f | head -1)
echo "Using PHP binary: $PHP_BIN"

if [ -z "$PHP_BIN" ]; then
    echo "ERROR: PHP binary not found!"
    find /server -name "php" 2>/dev/null
    exit 1
fi

# Start fake HTTP server for Render health check
python3 /server.py &

# Start playit tunnel in background
playit &

exec "$PHP_BIN" /server/PocketMine-MP.phar \
    --no-wizard \
    --data=/data \
    --plugins=/data/plugins