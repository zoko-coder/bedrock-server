FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    wget curl unzip \
    python3 ca-certificates \
    libcurl4 libssl3 \
    libstdc++6 libgcc-s1 \
    tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

# Copy pre-downloaded Bedrock Server zip
COPY bedrock-server.zip /tmp/bedrock.zip
RUN unzip -q /tmp/bedrock.zip -d /server/bedrock && \
    rm /tmp/bedrock.zip && \
    chmod +x /server/bedrock/bedrock_server

# Download playit v0.17.1
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