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

# DEBUG: Check playit binary
echo "=== PLAYIT BINARY INFO ===" >> /data/logs/playit.log
file /usr/local/bin/playit >> /data/logs/playit.log 2>&1
ls -la /usr/local/bin/playit >> /data/logs/playit.log 2>&1
ldd /usr/local/bin/playit >> /data/logs/playit.log 2>&1 || echo "ldd not available" >> /data/logs/playit.log
echo "==========================" >> /data/logs/playit.log

# Start web dashboard FIRST
python3 /server.py &

sleep 2

# DEBUG: Try running playit directly to see what it outputs
echo "=== TEST 1: Direct run (no TTY) ===" >> /data/logs/playit.log
timeout 10 /usr/local/bin/playit >> /data/logs/playit.log 2>&1 &
PID1=$!
sleep 5
kill $PID1 2>/dev/null
wait $PID1 2>/dev/null

echo "=== TEST 2: With pseudo-TTY (script) ===" >> /data/logs/playit.log
script -q -c "/usr/local/bin/playit" /dev/null >> /data/logs/playit.log 2>&1 &
PID2=$!
sleep 5
kill $PID2 2>/dev/null
wait $PID2 2>/dev/null

echo "=== TEST 3: playit setup ===" >> /data/logs/playit.log
timeout 10 /usr/local/bin/playit setup >> /data/logs/playit.log 2>&1 || true

echo "=== END DEBUG ===" >> /data/logs/playit.log

# Now run playit for real with pseudo-TTY
script -q -c "/usr/local/bin/playit" /dev/null >> /data/logs/playit.log 2>&1 &

exec "$PHP_BIN" /server/PocketMine-MP.phar \
    --no-wizard \
    --data=/data \
    --plugins=/data/plugins