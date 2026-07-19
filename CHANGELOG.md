# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.6.0] - 2026-07-19

### Added

- **MCP support** — MCP servers now work inside the box (see the readme's MCP section for the full support matrix):
  - **stdio servers run in-container** — Node.js 24 LTS (via nvm) and `uv`/`uvx` are baked into the images, so `npx -y ...` / `uvx ...` MCP servers spawn inside the sandbox.
  - **Host-local HTTP/SSE servers auto-forward** — the launcher scans MCP configs (`.claude.json` user/local scope and project `.mcp.json`) for `http://localhost:<port>` URLs and forwards those ports to the host via socat, so configs work verbatim in-container. Extra ports via the repeatable `--mcp-port` flag or `CLAUDE_BOX_MCP_PORTS` env var.
  - **Host-path warnings** — the launcher warns at startup when an MCP stdio command references a path that only exists on the host (e.g. `/Users/...`, `C:\...`).
- **Shared base image** — new `docker/Dockerfile.base` (`box-base:latest`, Ubuntu 24.04) underlies both the claude and codex images; `ensure_image()` builds it automatically before either child image.
- **Box-aware Claude** — a managed-policy memory file (`docker/box-claude.md` → `/etc/claude-code/CLAUDE.md` in the image) tells Claude it's in claude-box and how to handle MCP servers, sudo, and runtime installs. Invisible to host-side Claude sessions sharing the same config dir.
- **Passwordless sudo in the container** — the container user can `apt-get install` system deps at runtime; nvm and `uv python install` cover alternate Node/Python versions user-space.

### Changed

- **Claude image rebased** from `python:3.12-slim-bookworm` to the shared Ubuntu 24.04 `box-base` — full apt ecosystem and build tooling for general-purpose work. The first `--rebuild` after updating is a full multi-minute build.
- **Single container user `boxuser`** (UID 1000) replaces `claudeuser`/`codexuser` in both images; container-side paths are now `/home/boxuser/.claude` and `/home/boxuser/.codex`. Host-side state carries over unchanged.

### Removed

- **`global_python_requirements.txt`** — baked Python tooling was unused; tools install at runtime instead of bloating every image build.
- **docker-based MCP servers inside the box (rejected by design)** — mounting the Docker socket would be root-equivalent on the host and defeat the sandbox. Run docker-packaged MCP servers on the host behind an HTTP port instead (readme, MCP section).

### Fixed

- **`codex` launcher crash** — `bin/codex.py` used `sys.stdin.isatty()` without importing `sys`, raising `NameError` on every run.

### Known limitations

- **In-container MCP OAuth** — the auth callback port isn't published, so browser-based MCP authentication can't complete inside the box. Run the one-time auth from a host-side session with the same `CLAUDE_CONFIG_DIR`; tokens persist via the mount.

## [0.5.0] - 2026-07-05

### Added

- **Codex CLI runner** — new `codex` command (`bin/codex`, `bin/codex.bat`, `bin/codex.ps1` wrapping `bin/codex.py`) runs OpenAI's Codex CLI inside its own container, mirroring the claude wrapper: only the current directory is mounted, Codex state persists via host `~/.codex` (override with `CODEX_BOX_DIR`), and `OPENAI_*` credentials are forwarded only when set.
- **Codex image** — `docker/Dockerfile.codex`, based on Ubuntu 24.04 with Node.js 24 LTS, Python 3, Git, and common build tooling. `codexuser` takes UID 1000 (the stock `ubuntu` user is removed) so files written to mounted volumes match the typical host user on Linux.
- **Codex flags** — `--yolo` maps to Codex's `--dangerously-bypass-approvals-and-sandbox`; `--rebuild` forces an image rebuild (the image is otherwise auto-built on first run).
- **Codex worktree caution on Windows** — the launcher prints the same worktree warning as claude, and in interactive sessions injects a cautionary note into Codex's context (skipped for subcommand invocations like `codex exec`, where a positional prompt would break the command).

### Changed

- **Launchers invoke `docker` directly** — `docker-compose.yml` removed; both `bin/claude.py` and `bin/codex.py` run their containers with plain `docker run` and pass the env vars and volume mounts themselves. Each launcher is fully standalone, so unset variables belonging to one tool can no longer fail another.
- **Images auto-build on first run** — if the required image doesn't exist locally, the launcher builds it before starting, so a fresh clone works without a manual build step. `--rebuild` still forces a rebuild.
- **Docker assets moved to `docker/`** — `Dockerfile` renamed to `docker/Dockerfile.claude`; `entrypoint.py` and `global_python_requirements.txt` moved alongside it. The build context is now the `docker/` directory, keeping the repo root clean.
- **Shared launcher helpers extracted to `bin/box_common.py`** — path conversion, image build/auto-build, worktree `.git` mounting, and the exec/run tail now live in one module imported by the launchers instead of being duplicated. Worktree resolution is also more robust: it now handles relative `gitdir:` paths in the `.git` file.

### Fixed

- **socat output leaking into the terminal** — `socat`'s `stdout` is now redirected to `socat.log`, and the entrypoint no longer prints socat startup messages when `CLAUDE_CODE_SSE_PORT` is not set.
- **`bin/claude` line endings on Windows** — `.gitattributes` now forces LF for `bin/claude` (replacing the stale `entrypoint.sh` entry), so the launcher is not broken by CRLF checkouts.

## [0.4.0] - 2026-05-20

### Added

- **`--yolo` flag** — alias for `--dangerously-skip-permissions`, passed through to Claude.
- **PowerShell launcher** — `bin/claude.ps1` added for Windows PowerShell support, mirroring the existing `.bat` wrapper.
- **`.gitattributes` configuration** — added `.gitattributes` to force LF line endings for shell files, preventing execution failures when cloned or checked out on Windows.
- **Session-aware live log filenames** — `--live-log` paths may include a `SESSION_ID` placeholder, replaced with the actual Claude session ID at startup (detected from the most recent `.jsonl` in `~/.claude/projects/<project-key>/`). If the placeholder is missing it is inserted before the file extension automatically (e.g. `chat.md` → `chat-SESSION_ID.md`), with a timestamp fallback when the session ID cannot be detected.

### Changed

- **Host-side launcher migrated to Python** — Moved primary launcher logic from shell/batch scripts to a cross-platform Python implementation (`bin/claude.py`), using thin platform-specific wrappers (`bin/claude`, `bin/claude.bat`, `bin/claude.ps1`).
- **In-container entrypoint migrated to Python** — Completely rewrote the container startup logic and lock file guardian from Bash (`entrypoint.sh`) to Python (`entrypoint.py`), eliminating shell/CRLF compatibility issues on Windows and simplifying user process spawning.
- **Arg parsing migrated to `argparse`** — replaced the manual `while` loop with `argparse.parse_known_args` in the launcher; unknown args are passed through to Claude unchanged.
- **Live log skips setup exchange** — the initial logging-setup message and Claude's response to it are no longer written to the log file; logging starts from the first real user message.
- **Live log is silent** — Claude no longer mentions or acknowledges the logging behavior in its responses.

### Removed

- **`claude-yolo` wrappers** — `bin/claude-yolo`, `bin/claude-yolo.bat`, and `bin/claude-yolo.ps1` removed. Use `claude --yolo` instead.
- **`entrypoint.sh`** — Deleted in favor of the new Python-based `entrypoint.py`.
- **Dockerfile `sed` strip** — Removed the `sed -i` line-ending strip in the Dockerfile as it is no longer required for the Python entrypoint.

### Known limitations

- **Git worktrees on Windows are unsupported** — the `.git` file in a worktree stores a Windows-format path that Linux git inside the container cannot resolve. The launcher prints a warning at startup and injects a note into Claude's context so it stays cautious about git operations. Non-worktree repos work fine on Windows.

---

## [0.3.1] - 2026-05-03

### Added

- **`--live-log <file>` flag** — instructs Claude to append each exchange to a markdown file during the session. Useful for reviewing long outputs in an editor without copying from the terminal. Also configurable via the `CLAUDE_BOX_LIVE_LOG` env var; the flag takes precedence if both are set.
- **Shared `ide/` and `ide-backups/` across all profiles** — `~/.claude/ide` and `~/.claude/ide-backups` are now the single canonical locations for IDE lock files and their backups. Both are bind-mounted directly into the container regardless of which profile is active, so the lock file guardian works correctly across profile switches.

### Changed

- **`CLAUDE_PROFILE` renamed to `CLAUDE_BOX_PROFILE`** — all claude-box specific env vars now share the `CLAUDE_BOX_` prefix for consistency. Update any shell profiles or scripts that export `CLAUDE_PROFILE`.
- **`box-profile` lookup walks up the directory tree** — `bin/claude` now searches for `.claude/box-profile` by traversing from `$PWD` toward the filesystem root, the same way `git` finds `.git`. Previously it only checked `$PWD` exactly, so running from a subdirectory would silently fall back to the default profile.
- **IDE port scan reads from `~/.claude/ide` directly** — the alive-ports check now always reads lock files from the shared `~/.claude/ide` instead of `${CLAUDE_DIR}/ide`, keeping it consistent with the new bind-mount approach.

---

## [0.3.0] - 2026-04-25

### Added

- **Multi-profile support** — Claude Box now supports multiple isolated Claude profiles.
  - Each project can declare its profile by placing a `box-profile` file inside its `.claude/` directory.
  - The `claude` binary auto-reads `{pwd}/.claude/box-profile` at startup and sets `CLAUDE_PROFILE` accordingly (only when not already exported in the environment).
  - Each profile maps to its own config directory (`~/.claude-<profile>`), keeping credentials, settings, and history fully isolated between projects or clients.
  - A profile status line is always printed at startup:
    - `[claude] Profile: <name> (~/.claude-<name>)` when a profile is active.
    - `[claude] No profile detected, using default (~/.claude)` when no profile file is found.
- **Global Python requirements** — `global_python_requirements.txt` is now copied into the image and installed via pip at build time, making Python packages (e.g. `graphifyy`) available inside every container without manual setup.
- **`--rebuild` flag** — pass `--rebuild` to `bin/claude` to trigger `docker compose run --build`, rebuilding the image before starting the container. Useful after updating `global_python_requirements.txt` or the `Dockerfile`.
- **`graphify install` on build** — if `graphify` is available after pip install, its post-install hook runs automatically so tools like the commit hook are wired up out of the box.

### Changed

- **Base image** switched from `debian:12.13-slim` to `python:3.12.13-slim-bookworm` — Python 3.12 is now baked into the container, removing the need for a separate Python install step.
- **`docker-compose.yml` volume mount** simplified — volumes now use the `CLAUDE_DIR` env var (resolved by `bin/claude` at startup) instead of a hardcoded `~/.claude` path, and the separate `~/.claude.json` mount is dropped. This makes profile-aware mounts work correctly.

---

## [0.2.0] - 2026-04-10

### Added

- Claude installed under `claudeuser` for better home-directory management inside the container.

### Changed

- Switched to `claudeuser`-owned home directory to avoid permission issues with mounted volumes.

---

## [0.1.0] - 2026-04-03

### Added

- Initial working Claude Box setup — Claude Code running inside Docker with IDE integration.
- Lock file guardian with leader election to handle Docker startup delay transparently.
- Git worktree detection — main repo `.git` is auto-mounted when a worktree is detected.
- Alive IDE port detection — only live ports are written to `.alive_ports` before container start.
- Credentials persist across restarts via `~/.claude` volume mount.
