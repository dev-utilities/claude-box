# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
