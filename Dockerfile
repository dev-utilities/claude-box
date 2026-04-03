FROM debian:12.13-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    ca-certificates \
    socat \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /root/entrypoint.sh

# Run as root inside the container
WORKDIR /workspace

# Install Claude Code as root
RUN curl -fsSL https://claude.ai/install.sh | bash

ENV PATH="/root/.local/bin:${PATH}"

ENTRYPOINT ["bash", "/root/entrypoint.sh"]