# Python 3.12.13 (latest stable as of 2026-03-03) on Debian 12 Bookworm slim
FROM python:3.12.13-slim-bookworm

RUN apt-get update && apt-get install -y \
    curl \
    git \
    ca-certificates \
    socat \
    && rm -rf /var/lib/apt/lists/*

# Install global Python requirements
COPY global_python_requirements.txt /tmp/global_python_requirements.txt
RUN pip install --no-cache-dir -r /tmp/global_python_requirements.txt \
 && if command -v graphify > /dev/null 2>&1; then graphify install; fi

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
