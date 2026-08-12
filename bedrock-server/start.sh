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

# Start fake HTTP server for Render health check
python3 /server.py &

# Start playit tunnel in background
playit &

# Use PocketMine's bundled PHP binary
exec /server/bin/php8/bin/php /server/PocketMine-MP.phar \
    --no-wizard \
    --data=/data \
    --plugins=/data/plugins