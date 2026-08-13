FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    wget curl unzip \
    python3 python3-requests \
    ca-certificates libcurl4 libssl3 \
    libstdc++6 libgcc-s1 tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

# Unzip BDS to /server/bedrock (handles subfolder automatically)
COPY bedrock-server.zip /tmp/bedrock.zip
RUN unzip -q /tmp/bedrock.zip -d /tmp/bedrock-extract && \
    # Move files up if they're in a subfolder
    if [ -d /tmp/bedrock-extract/bedrock-server* ]; then \
        mv /tmp/bedrock-extract/bedrock-server* /server/bedrock; \
    else \
        mv /tmp/bedrock-extract/* /server/bedrock; \
    fi && \
    rm -rf /tmp/bedrock-extract /tmp/bedrock.zip && \
    chmod +x /server/bedrock/bedrock_server && \
    ls -la /server/bedrock/

# Download playit
RUN wget -q https://github.com/playit-cloud/playit-agent/releases/download/v0.17.1/playit-linux-amd64 \
    -O /usr/local/bin/playit && chmod +x /usr/local/bin/playit

RUN mkdir -p /root/.config/playit_gg
COPY playit.toml /root/.config/playit_gg/playit.toml

COPY start.sh /start.sh
COPY server.py /server.py
COPY backup.py /backup.py
RUN chmod +x /start.sh

EXPOSE 19132/udp
CMD ["/start.sh"]