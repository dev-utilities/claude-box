#!/usr/bin/env python3
"""claude-box host-side launcher — runs on the host, not inside the container."""

import argparse
import datetime
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


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


def to_docker_path(p: Path) -> str:
    """Convert a host path to the equivalent Linux path inside the container."""
    if platform.system() == "Windows":
        s = str(p)
        drive, rest = os.path.splitdrive(s)
        return f"/{drive[0].lower()}{rest.replace(chr(92), '/')}"
    return str(p)


def main():
    script_dir = Path(__file__).parent
    compose_file = script_dir.parent / "docker-compose.yml"
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
    if profile:
        default_claude = "/home/claudeuser/default-claude"
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

    compose_opts = ["--build"] if parsed.rebuild else []
    if parsed.yolo:
        passthrough_args.append("--dangerously-skip-permissions")
    live_log_file = parsed.live_log

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
            m = re.search(r"gitdir:\s*(.+)", git_file.read_text())
            if m:
                gitdir = m.group(1).strip()
                main_repo = Path(re.sub(r"/.git/worktrees/.*", "", gitdir))
                if (main_repo / ".git").is_dir():
                    print(f"[claude] Worktree detected. Mounting main repo .git: {main_repo / '.git'}")
                    extra_mounts += ["-v", f"{main_repo / '.git'}:{to_docker_path(main_repo / '.git')}"]

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
    env = os.environ.copy()
    env["CLAUDE_DIR"] = str(claude_dir)
    env["CLAUDE_CONFIG_DIR"] = str(container_claude_dir)
    if profile:
        env["DEFAULT_CLAUDE_PATH"] = "/home/claudeuser/default-claude"
    else:
        env.pop("DEFAULT_CLAUDE_PATH", None)

    initial_prompt_args = ["\n".join(initial_prompt)] if initial_prompt else []
    cmd = [
        "docker", "compose",
        "-f", str(compose_file),
        "run", "--rm",
        *compose_opts,
        *extra_docker_args,
        "-v", f"{host_cwd}:{container_cwd}",
        "-w", container_cwd,
        *extra_mounts,
        "claude",
        *initial_prompt_args,
        *passthrough_args,
    ]

    if platform.system() == "Windows":
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    else:
        os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
