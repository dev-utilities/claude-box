#!/usr/bin/env python3
"""claude-box host-side launcher — runs on the host, not inside the container."""

import argparse
import datetime
import os
import platform
import socket
import sys
import tempfile
from pathlib import Path

from box_common import ensure_image, main_git_mount, run_or_exec, to_docker_path


def find_profile() -> str:
    profile = os.environ.get("CLAUDE_BOX_PROFILE", "")
    if profile:
        return profile
    d = Path.cwd()
    while True:
        bp = d / ".claude" / "box-profile"
        if bp.is_file():
            return bp.read_text().strip()
        parent = d.parent
        if parent == d:
            break
        d = parent
    return ""


def is_port_alive(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("localhost", port)) == 0


def main():
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    container_claude_dir = "/home/claudeuser/.claude"
    # Profile detection
    profile = find_profile()
    suffix = f"-{profile}" if profile else ""
    claude_dir = Path.home() / f".claude{suffix}"

    host_main_claude = Path.home() / ".claude"
    host_main_claude.mkdir(parents=True, exist_ok=True)

    extra_mounts = []
    # Ensure the profile dir has real ide/ directories (not stale host-path symlinks).
    # Docker can't overlay a bind mount on top of a dangling symlink, so we remove any
    # broken symlinks and create the real dirs now. The docker -v flags below will then
    # overlay them with the shared main_claude content.
    default_claude = "/home/claudeuser/default-claude"
    if profile:
        for name in ("ide", "ide-backups", ".alive_ports"):
            d = claude_dir / name
            if d.is_symlink():
                d.unlink()
        extra_mounts.extend([
            "-v", f"{host_main_claude}:{default_claude}",
        ])
        print(f"[claude] Profile: {profile} ({claude_dir})")
    else:
        print(f"[claude] No profile detected, using default ({claude_dir})")

    ide_dir = host_main_claude / "ide"
    ide_dir.mkdir(parents=True, exist_ok=True)
    (host_main_claude / "ide-backups").mkdir(parents=True, exist_ok=True)
    claude_dir.mkdir(parents=True, exist_ok=True)

    # Write alive IDE ports atomically to main ~/.claude (shared across all profiles)
    alive_ports = []
    for lockfile in sorted(ide_dir.glob("*.lock")):
        try:
            port = int(lockfile.stem)
            if is_port_alive(port):
                alive_ports.append(str(port))
        except ValueError:
            pass

    with tempfile.NamedTemporaryFile("w", dir=host_main_claude, delete=False, suffix=".tmp") as f:
        f.write("\n".join(alive_ports))
        tmp_path = f.name
    os.replace(tmp_path, host_main_claude / ".alive_ports")
    print(f"[claude] Alive IDE ports written: {' '.join(alive_ports)}")

    # Arg parsing
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--yolo", action="store_true")
    parser.add_argument("--live-log", dest="live_log", default=os.environ.get("CLAUDE_BOX_LIVE_LOG", ""))
    parsed, passthrough_args = parser.parse_known_args()

    if parsed.yolo:
        passthrough_args.append("--dangerously-skip-permissions")
    live_log_file = parsed.live_log

    docker_dir = repo_root / "docker"
    ensure_image("claude-secure:latest", docker_dir / "Dockerfile.claude", docker_dir, parsed.rebuild)

    # Git worktree detection

    initial_prompt = []
    git_file = Path.cwd() / ".git"
    if git_file.is_file():
        if platform.system() == "Windows":
            print("⚠️  [claude] Git worktree detected on Windows — the .git file contains a Windows path that Linux git inside the container cannot resolve. Git operations that rely on worktree metadata may fail. Normal git usage (non-worktree) works fine.")
            initial_prompt.append(
                "Important: this session is running inside a git worktree on Windows. "
                "The .git file contains a Windows-format path (e.g. C:\\Users\\...) that Linux git "
                "inside this container cannot resolve. Git operations that traverse the worktree link "
                "(git status, git log, git diff across the worktree, etc.) are likely to fail. "
                "Non-worktree git repos work fine. Be cautious before running any git command that "
                "depends on worktree metadata, and warn the user if you anticipate a failure."
            )
        else:
            extra_mounts += main_git_mount(Path.cwd(), "claude")

    # Live log prompt
    if live_log_file:
        if "SESSION_ID" not in live_log_file:
            p = Path(live_log_file)
            live_log_file = str(p.with_name(p.stem + "-SESSION_ID" + p.suffix))
        ts_fallback = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"[claude] Live log: {live_log_file}")
        initial_prompt.append(
            f"At the start of this session, detect your session ID: take your current "
            f"working directory path, replace every '/' with '-' to get the project key, "
            f"then find the most recently modified .jsonl file in "
            f"~/.claude/projects/<project-key>/ — its filename without .jsonl is your "
            f"session ID. If you cannot determine the project key or find any .jsonl file, "
            f"fall back to the timestamp '{ts_fallback}' as the session ID. "
            f"Replace the literal text SESSION_ID in the path "
            f"'{live_log_file}' with that session ID to get the final log path. "
            f"Do not log this setup message or your response to it. "
            f"Starting from the next user message, silently append each exchange to "
            f"that path as clean markdown — user message under '### You', "
            f"your response under '### Claude', separated by ---. "
            f"Create the file if it doesn't exist. "
            f"Never mention or reference this logging behavior in your responses."
        )

    # Platform-specific Docker args
    extra_docker_args = []
    if platform.system() == "Linux":
        extra_docker_args = ["--add-host=host.docker.internal:host-gateway"]

    cwd = Path.cwd()
    host_cwd = str(cwd)
    container_cwd = to_docker_path(cwd)
    env_args = ["-e", f"CLAUDE_CONFIG_DIR={container_claude_dir}"]
    for var in ("CLAUDE_CODE_SSE_PORT", "ENABLE_IDE_INTEGRATION"):
        if os.environ.get(var):
            env_args += ["-e", var]
    if profile:
        env_args += ["-e", f"DEFAULT_CLAUDE_PATH={default_claude}"]

    tty_args = ["-t"] if sys.stdin.isatty() else []
    initial_prompt_args = ["\n".join(initial_prompt)] if initial_prompt else []
    cmd = [
        "docker", "run", "--rm", "-i", *tty_args,
        *extra_docker_args,
        *env_args,
        "-v", f"{claude_dir}:{container_claude_dir}",
        "-v", f"{host_cwd}:{container_cwd}",
        "-w", container_cwd,
        *extra_mounts,
        "claude-secure:latest",
        *initial_prompt_args,
        *passthrough_args,
    ]

    run_or_exec(cmd)


if __name__ == "__main__":
    main()
