FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    wget curl unzip \
    python3 ca-certificates \
    libcurl4 libssl3 \
    libstdc++6 libgcc-s1 \
    tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

# Download official Bedrock Dedicated Server 1.26.43.1
# If this URL fails during build, download the zip manually from:
# https://www.minecraft.net/en-us/download/server/bedrock
# and place it in your repo as bedrock-server.zip, then replace the RUN below with:
# COPY bedrock-server.zip /tmp/bedrock.zip
RUN wget -q --user-agent="Mozilla/5.0" \
    https://minecraft.azureedge.net/bin-linux/bedrock-server-1.26.43.1.zip \
    -O /tmp/bedrock.zip && \
    unzip -q /tmp/bedrock.zip -d /server/bedrock && \
    rm /tmp/bedrock.zip && \
    chmod +x /server/bedrock/bedrock_server

# Download playit v0.17.1 (your working setup)
RUN wget -q https://github.com/playit-cloud/playit-agent/releases/download/v0.17.1/playit-linux-amd64 \
    -O /usr/local/bin/playit && chmod +x /usr/local/bin/playit

# Pre-baked playit secret
RUN mkdir -p /root/.config/playit_gg
COPY playit.toml /root/.config/playit_gg/playit.toml

COPY start.sh /start.sh
COPY server.py /server.py
RUN chmod +x /start.sh

EXPOSE 19132/udp

CMD ["/start.sh"]