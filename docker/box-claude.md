# claude-box environment

You are running inside claude-box, a Docker container. The project directory and
`~/.claude` are host mounts; everything else is container-local. `host.docker.internal`
reaches the host.

## MCP servers

- Prefer in-container stdio servers (`npx -y ...`, `uvx ...`) — sandboxed, no host
  management needed. Node (via nvm) and uv are preinstalled.
- `http://localhost:<port>` MCP URLs are auto-forwarded to the host at launch, for
  servers that must run on the host (real browser, host apps, docker) or are shared
  across instances. Newly added localhost URLs take effect on the next launch.
- Docker-packaged MCP servers cannot run here (no docker in the box). Suggest running
  them on the host behind an HTTP port instead: Docker MCP Toolkit gateway, the
  image's own `--transport http` mode, or
  `npx -y supergateway --stdio "docker run -i --rm <image>" --port <port>`.
- Never reference host filesystem paths in MCP commands — they don't exist here.
- Remote OAuth MCP authentication cannot complete in-container (the callback port
  isn't published). Tell the user to run the one-time auth from a host-side session
  with the same config dir; tokens persist via the mount.

## Git

Never commit without asking the user first. The only exception is when the user has
explicitly said, in this session, to commit without asking — a one-off "commit this"
authorizes exactly that commit, not future ones.

## System packages

You have passwordless sudo: `sudo apt-get install ...` works for system deps. Use nvm
for other Node versions and `uv python install` for other Pythons — all user-space.
Installed packages may persist across sessions via the container commit; don't assume
they will until you've verified.
