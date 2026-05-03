# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added

- **`--yolo` flag** — alias for `--dangerously-skip-permissions`, passed through to Claude.
- **Session ID in live log filename** — `--live-log` paths can now include `SESSION_ID` as a placeholder; Claude detects its session ID at startup by finding the most recently modified `.jsonl` in `~/.claude/projects/<project-key>/` and substitutes it into the filename.
- **Automatic `SESSION_ID` injection** — if the `--live-log` path does not contain `SESSION_ID`, Python inserts it before the file extension automatically (e.g. `chat.md` → `chat-SESSION_ID.md`).
- **Timestamp fallback for session ID** — if the project-key lookup fails, a Python-generated timestamp (`YYYYMMDD_HHMMSS`) is embedded in the prompt as a fallback session ID.

### Changed

- **Arg parsing migrated to `argparse`** — replaced the manual `while` loop with `argparse.parse_known_args`; unknown args are still passed through to Claude unchanged.
- **Live log skips setup exchange** — the initial logging-setup message and Claude's response to it are no longer written to the log file; logging starts from the first real user message.
- **Live log is silent** — Claude no longer mentions or acknowledges the logging behavior in its responses.

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
