# Claude Code in Docker — IDE Integration

Run Claude Code inside Docker with full IDE integration on macOS.

> **Tested with:** PyCharm. Should work with VS Code as well — not yet verified.
>
> **Note:** This project is in its early stages and currently focused on macOS and Windows. Linux support may come in the future — contributions are welcome!

---

## Prerequisites

- Docker Desktop running
- PyCharm with the Claude Code plugin installed (search "Claude Code" by [Anthropic](https://plugins.jetbrains.com/vendor/anthropic) in JetBrains Marketplace)

---

## Setup

### 1. Update your rc file e.g. `~/.zshrc`
- Set `CLAUDE_CONFIG_DIR` env var inside your rc file
- Add the `claude-box` directory to `$PATH`

```zsh
export CLAUDE_CONFIG_DIR=~/.claude
export PATH="path/to/claude-box/bin:$PATH"
```

> **Note:** Make sure to restart PyCharm if it was already running

### 2. Build the container

The Docker image is built automatically the first time you run `claude`. To force a rebuild later (e.g. after changing `docker/Dockerfile.claude`):

```zsh
claude --rebuild
```

### 3. Make `claude` shell file executable

```zsh
chmod +x bin/claude
```

---

## Usage

- **From terminal**: run `claude` in any project directory
- **From PyCharm**: click the Claude Code button — it launches the container automatically

To manually connect Claude to PyCharm, run `/ide`.

### Flags

| Flag | Description |
|---|---|
| `--rebuild` | Rebuild the Docker images (shared base + claude) before starting |
| `--yolo` | Alias for `--dangerously-skip-permissions` — skips all permission prompts |
| `--live-log <file>` | Log every exchange to a markdown file during the session |
| `--mcp-port <ports>` | Extra host ports to forward for MCP servers (repeatable, comma-separated) |

### Live Log

The `--live-log` flag instructs Claude to append each prompt and response to a markdown file as the session progresses — useful for reviewing long outputs in your editor.

```zsh
# log to chat.md in the current directory
claude --live-log chat.md

# log to a custom path
claude --live-log /tmp/session.md
```

You can also set `CLAUDE_BOX_LIVE_LOG` in your shell profile to enable it automatically for every session:

```zsh
export CLAUDE_BOX_LIVE_LOG=~/claude-logs/chat.md
```

The flag takes precedence over the env var if both are set.

---

## MCP Support

MCP config needs no special handling — user/local scope (`.claude.json` inside the
mounted config dir), project scope (`.mcp.json` in your repo), and Codex's
`config.toml` all reach the container through the existing mounts.

| Server type | Works? | How |
|---|---|---|
| Remote HTTP/SSE (internet URL) | ✅ | Plain outbound HTTPS, nothing to do |
| stdio via `npx` / `uvx` | ✅ | Node (nvm) and uv are preinstalled — servers run *inside* the sandbox |
| Host-local HTTP/SSE (`http://localhost:<port>`) | ✅ | Ports are detected in your MCP config at launch and auto-forwarded to the host; add extra ports with `--mcp-port` or `CLAUDE_BOX_MCP_PORTS` |
| stdio with host paths (`/Users/...`, `C:\...`) | ❌ | Won't exist in the container — the launcher warns at startup. Run it in-container or bridge it (below) |
| Docker-packaged servers | ❌ in-box | No docker inside the box (mounting the docker socket would defeat the sandbox). Run them on the **host** behind a port instead — see below |

**Bridging a host-only server to the box** — run it on a host port, the launcher
forwards it automatically on the next start:

```zsh
# Any stdio command (including docker run) exposed as streamable HTTP on :8931
npx -y supergateway --stdio "docker run -i --rm mcp/foo" --port 8931

# then, inside the box:
claude mcp add host-thing --transport http http://localhost:8931/mcp
```

Alternatives: Docker Desktop's **MCP Toolkit** gateway (one port for all catalog
servers), or the server's own HTTP mode (`docker run -p 8931:8931 some/mcp --transport http --port 8931`).

**OAuth-authenticated remote servers:** the in-container auth callback can't reach
your browser. Run the one-time authentication from a host-side `claude` session using
the same `CLAUDE_CONFIG_DIR` — tokens persist via the mount and the box uses them
silently.

**Runtime flexibility:** the container user has passwordless sudo for `apt-get`
system deps; nvm covers alternate Node versions and `uv python install` alternate
Pythons — no rebuild needed.

---

## Codex CLI — Containerized

This repo also includes a Codex CLI runner that uses the same Docker wrapper style, without IDE integration. Both the Claude and Codex images build on a shared `box-base` image (Ubuntu 24.04 with Node.js 24 LTS via nvm, uv, Python 3, Git, and common build tooling).

The image is built automatically the first time you run `codex`. To force a rebuild later (e.g. after changing `docker/Dockerfile.codex`), pass `--rebuild`. Run Codex from any project directory:

```zsh
codex
codex exec "summarize this repo"
```

The wrapper mounts your project and persists Codex state by mounting host `~/.codex` to `/home/boxuser/.codex` in the container. To isolate it from your normal Codex config, set `CODEX_BOX_DIR`:

```zsh
CODEX_BOX_DIR=~/.codex-box codex
```

The wrapper also supports `--yolo`, which maps to Codex's `--dangerously-bypass-approvals-and-sandbox` flag.

---

## Multi-Profile Support

Claude Box supports multiple isolated Claude profiles, useful when working across different clients or projects that need separate credentials and settings.

### How it works

Each profile gets its own config directory on the host: `~/.claude-<profile>`.

The `claude` binary picks the profile in this order:
1. `CLAUDE_BOX_PROFILE` environment variable (if already exported)
2. `.claude/box-profile` file — searched from the current directory upward to the filesystem root (same as how `git` finds `.git`), so it works from any subdirectory within a project

A status line is always printed at startup so you know which profile is active.

### Setting up a project profile

Create a `.claude/box-profile` file in your project root:

```zsh
mkdir -p .claude
echo "client-a" > .claude/box-profile
```

Now running `claude` from that directory will automatically use `~/.claude-client-a`.

### Switching profiles manually

Export `CLAUDE_BOX_PROFILE` before running `claude`:

```zsh
CLAUDE_BOX_PROFILE=client-b claude
```

---

## Notes

- Git worktrees are detected automatically — the main repo's `.git` is mounted for you
- The lock file guardian handles the Docker startup delay transparently
- Credentials persist across container restarts via the `~/.claude` volume mount
- No dev containers needed — this approach is lighter and faster, especially in PyCharm where dev containers feel sluggish

### Windows — git worktree limitation

Git worktrees are **not supported on Windows**. When git creates a worktree on Windows, the `.git` file stores a Windows-format path (e.g. `C:\Users\...`) that Linux git inside the container cannot resolve.

Claude will warn you at startup if a worktree is detected and will be cautious about git operations that depend on worktree metadata. Regular git usage (non-worktree repos) works fine on Windows.
