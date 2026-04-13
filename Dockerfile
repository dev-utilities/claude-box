FROM debian:12.13-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    ca-certificates \
    socat \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m claudeuser

# Install Claude Code as claudeuser so it installs to the correct user directory
USER claudeuser
ENV HOME=/home/claudeuser
ENV PATH="/home/claudeuser/.local/bin:/usr/local/bin/:${PATH}"
RUN curl -fsSL https://claude.ai/install.sh | bash

USER root
COPY entrypoint.sh /home/claudeuser/entrypoint.sh
RUN chmod +x /home/claudeuser/entrypoint.sh

WORKDIR /workspace

USER claudeuser
ENTRYPOINT ["/home/claudeuser/entrypoint.sh"]
