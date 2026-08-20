FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    wget curl unzip \
    python3 python3-requests \
    ca-certificates libcurl4 libssl3 \
    libstdc++6 libgcc-s1 tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server
ENV MALLOC_ARENA_MAX=1

COPY bedrock-server.zip /tmp/bedrock.zip
RUN mkdir -p /server/bedrock && \
    unzip -q /tmp/bedrock.zip -d /tmp/bedrock-extract && \
    SUBDIR=$(ls /tmp/bedrock-extract | grep -m1 "^bedrock-server" || true) && \
    if [ -n "$SUBDIR" ] && [ -d "/tmp/bedrock-extract/$SUBDIR" ]; then \
        mv /tmp/bedrock-extract/"$SUBDIR"/* /server/bedrock/; \
    else \
        mv /tmp/bedrock-extract/* /server/bedrock/; \
    fi && \
    rm -rf /tmp/bedrock-extract /tmp/bedrock.zip && \
    chmod +x /server/bedrock/bedrock_server

RUN wget -q https://github.com/playit-cloud/playit-agent/releases/download/v0.17.1/playit-linux-amd64 \
    -O /usr/local/bin/playit && chmod +x /usr/local/bin/playit

RUN mkdir -p /root/.config/playit_gg
COPY playit.toml /root/.config/playit_gg/playit.toml

COPY start.sh /start.sh
COPY server.py /server.py
COPY backup.py /backup.py
RUN chmod +x /start.sh

VOLUME /data
EXPOSE 19132/udp
CMD ["/start.sh"]