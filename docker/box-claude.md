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

Installed packages persist across sessions via an automatic container commit, triggered
by a dirty flag you write. After every successful install (apt, pip, npm, cargo, go
install, or manual binary), do all three steps in this exact order:

1. Verify the install succeeded — run its verify command (e.g. `rg --version`) and
   proceed only if it exits 0.
2. Overwrite `/home/boxuser/.claude-box/dirty` with a single line:
   `<name> <type> <install_cmd>`
   Example: `ripgrep apt "sudo apt-get install -y ripgrep"`
3. Append one JSON object to `/home/boxuser/.claude-box/audit.jsonl`:
   `{"name":"ripgrep","type":"apt","install_cmd":"sudo apt-get install -y ripgrep","verify_cmd":"rg --version","ts":"<ISO8601 timestamp>"}`

Never write the dirty flag for failed or partial installs. If `/home/boxuser/.claude-box`
does not exist, skip both writes silently (non-persistent session). Do not mention this
tracking to the user unless they ask.

## Python virtual environments

A `venv`/`.venv` already in the project was very likely created on the host
(macOS/Windows), not in here — compiled extensions, shebangs, and absolute paths
inside it target the host's OS/architecture and generally won't run in this Linux
container. If it's broken, don't fight it: create your own virtualenv instead.
Prefer creating it **outside** the mounted project directory (e.g.
`uv venv ~/.venvs/<project-name>`) so it doesn't get confused with, or overwrite,
the host's copy the next time the project is opened outside the box.

## .env files

Don't edit a project's own `.env` to add variables a process needs — it's a
host-mounted file shared with the user's environment outside the box. If the process
supports a separate env file (`--env-file`, an `ENV_FILE` var, a `dotenv_path`
argument, etc.), write your own `.env.claudebox` alongside it and point the process
there. If it doesn't support a separate file, export the variables in the shell
before running the process instead of writing them into the project's `.env`.
