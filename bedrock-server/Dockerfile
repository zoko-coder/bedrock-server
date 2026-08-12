FROM php:8.2-cli

RUN apt-get update && apt-get install -y \
    wget \
    curl \
    python3 \
    libzip-dev \
    libgmp-dev \
    libyaml-dev \
    && docker-php-ext-install zip gmp \
    && pecl install yaml \
    && docker-php-ext-enable yaml \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

# Download PocketMine-MP
RUN wget -q https://github.com/pmmp/PocketMine-MP/releases/latest/download/PocketMine-MP.phar \
    -O /server/PocketMine-MP.phar

COPY playit-linux-amd64 /usr/local/bin/playit
COPY start.sh /start.sh
COPY server.py /server.py

RUN chmod +x /start.sh /usr/local/bin/playit

EXPOSE 19132/udp

CMD ["/start.sh"]