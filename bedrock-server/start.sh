#!/bin/sh

mkdir -p /data/plugins

# Accept EULA
if [ ! -f /data/eula.txt ]; then
    echo "eula=true" > /data/eula.txt
fi

# Generate basic server.properties if not exists
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

# Start PocketMine
exec php /server/PocketMine-MP.phar \
    --no-wizard \
    --data=/data \
    --plugins=/data/plugins