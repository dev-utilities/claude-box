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

```zsh
docker compose build
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
| `--rebuild` | Rebuild the Docker image before starting |
| `--yolo` | Alias for `--dangerously-skip-permissions` — skips all permission prompts |
| `--live-log <file>` | Log every exchange to a markdown file during the session |

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