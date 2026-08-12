#!/bin/bash

mkdir -p /data/plugins /data/logs /data/.config/playit_gg

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

# Start web dashboard FIRST
python3 /server.py &

sleep 2

# Run playit inside a pseudo-TTY so the frontend starts and prints the claim link
# 'script' is already available in debian:bookworm-slim
script -q -c "/usr/local/bin/playit" /dev/null >> /data/logs/playit.log 2>&1 &
echo "[start.sh] playit started with pseudo-TTY"

exec "$PHP_BIN" /server/PocketMine-MP.phar \
    --no-wizard \
    --data=/data \
    --plugins=/data/plugins