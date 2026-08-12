FROM alpine:3.19

RUN apk add --no-cache \
    wget \
    curl \
    python3 \
    ca-certificates \
    libstdc++ \
    libgcc \
    bash

WORKDIR /server

RUN wget -q https://github.com/pmmp/PHP-Binaries/releases/download/pm5-php-8.2-latest/PHP-8.2-Linux-x86_64-PM5.tar.gz \
    -O /tmp/php.tar.gz && \
    tar -xzf /tmp/php.tar.gz -C /server && \
    rm /tmp/php.tar.gz && \
    find /server/bin -name "php" && \
    echo "=== PHP BINARY FOUND AT ABOVE PATH ==="

RUN wget -q https://github.com/pmmp/PocketMine-MP/releases/latest/download/PocketMine-MP.phar \
    -O /server/PocketMine-MP.phar

COPY playit-linux-amd64 /usr/local/bin/playit
COPY start.sh /start.sh
COPY server.py /server.py

RUN chmod +x /start.sh /usr/local/bin/playit

EXPOSE 19132/udp

CMD ["/start.sh"]