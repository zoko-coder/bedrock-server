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

python3 /server.py &

sleep 2

# Playit finds the pre-baked secret and connects immediately
/usr/local/bin/playit >> /data/logs/playit.log 2>&1 &

exec "$PHP_BIN" /server/PocketMine-MP.phar \
    --no-wizard --data=/data --plugins=/data/plugins