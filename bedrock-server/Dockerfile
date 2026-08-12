FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    wget curl python3 ca-certificates \
    libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

RUN wget -q https://github.com/pmmp/PHP-Binaries/releases/download/pm5-php-8.2-latest/PHP-8.2-Linux-x86_64-PM5.tar.gz \
    -O /tmp/php.tar.gz && \
    tar -xzf /tmp/php.tar.gz -C /server && \
    rm /tmp/php.tar.gz

RUN wget -q https://github.com/pmmp/PocketMine-MP/releases/latest/download/PocketMine-MP.phar \
    -O /server/PocketMine-MP.phar

# v0.15.3 — no TUI, no TTY needed, rock solid headless
RUN wget -q https://github.com/playit-cloud/playit-agent/releases/download/v0.15.3/playit-linux-amd64 \
    -O /usr/local/bin/playit && chmod +x /usr/local/bin/playit

RUN mkdir -p /root/.config/playit_gg
COPY playit.toml /root/.config/playit_gg/playit.toml

COPY start.sh /start.sh
COPY server.py /server.py
RUN chmod +x /start.sh

EXPOSE 19132/udp

CMD ["/start.sh"]