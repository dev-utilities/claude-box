# Claude Code in Docker — IDE Integration

Run Claude Code inside Docker with full IDE integration on macOS.

> **Tested with:** PyCharm. Should work with VS Code as well — not yet verified.
>
> **Note:** This project is in its early stages and currently focused on macOS. Windows and Linux support may come in the future — contributions are welcome!

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

---

## Multi-Profile Support

Claude Box supports multiple isolated Claude profiles, useful when working across different clients or projects that need separate credentials and settings.

### How it works

Each profile gets its own config directory on the host: `~/.claude-<profile>`.

The `claude` binary picks the profile in this order:
1. `CLAUDE_PROFILE` environment variable (if already exported)
2. `{pwd}/.claude/box-profile` file in the current project directory

A status line is always printed at startup so you know which profile is active.

### Setting up a project profile

Create a `.claude/box-profile` file in your project root:

```zsh
mkdir -p .claude
echo "client-a" > .claude/box-profile
```

Now running `claude` from that directory will automatically use `~/.claude-client-a`.

### Switching profiles manually

Export `CLAUDE_PROFILE` before running `claude`:

```zsh
CLAUDE_PROFILE=client-b claude
```

---

## Notes

- Git worktrees are detected automatically — the main repo's `.git` is mounted for you
- The lock file guardian handles the Docker startup delay transparently
- Credentials persist across container restarts via the `~/.claude` volume mount
- No dev containers needed — this approach is lighter and faster, especially in PyCharm where dev containers feel sluggish