FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    wget \
    curl \
    python3 \
    ca-certificates \
    libstdc++6 \
    libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

RUN wget -q https://github.com/pmmp/PHP-Binaries/releases/download/pm5-php-8.2-latest/PHP-8.2-Linux-x86_64-PM5.tar.gz \
    -O /tmp/php.tar.gz && \
    tar -xzf /tmp/php.tar.gz -C /server && \
    rm /tmp/php.tar.gz && \
    find /server/bin -name "php" && \
    echo "=== PHP BINARY FOUND ==="

RUN wget -q https://github.com/pmmp/PocketMine-MP/releases/latest/download/PocketMine-MP.phar \
    -O /server/PocketMine-MP.phar

COPY playit-linux-amd64 /usr/local/bin/playit
COPY start.sh /start.sh
COPY server.py /server.py

RUN chmod +x /start.sh /usr/local/bin/playit

EXPOSE 19132/udp

CMD ["/start.sh"]