FROM debian:12.13-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    ca-certificates \
    socat \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code as root
RUN curl -fsSL https://claude.ai/install.sh | bash && \
    cp /root/.local/bin/claude /usr/local/bin/claude && \
    chmod +x /usr/local/bin/claude

ENV PATH="/root/.local/bin:/usr/local/bin/:${PATH}"

RUN useradd -m claudeuser

COPY entrypoint.sh /home/claudeuser/entrypoint.sh
RUN chmod +x /home/claudeuser/entrypoint.sh

WORKDIR /workspace

USER claudeuser
ENTRYPOINT ["/home/claudeuser/entrypoint.sh"]