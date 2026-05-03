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

    # Profile detection
    profile = find_profile()
    suffix = f"-{profile}" if profile else ""
    claude_dir = Path.home() / f".claude{suffix}"

    claude_dir.mkdir(parents=True, exist_ok=True)
    (Path.home() / ".claude" / "ide").mkdir(parents=True, exist_ok=True)
    (Path.home() / ".claude" / "ide-backups").mkdir(parents=True, exist_ok=True)

    if profile:
        print(f"[claude] Profile: {profile} ({claude_dir})")
    else:
        print(f"[claude] No profile detected, using default ({claude_dir})")

    # Write alive IDE ports atomically
    ide_dir = Path.home() / ".claude" / "ide"
    alive_ports = []
    for lockfile in sorted(ide_dir.glob("*.lock")):
        try:
            port = int(lockfile.stem)
            if is_port_alive(port):
                alive_ports.append(str(port))
        except ValueError:
            pass

    with tempfile.NamedTemporaryFile("w", dir=claude_dir, delete=False, suffix=".tmp") as f:
        f.write("\n".join(alive_ports))
        tmp_path = f.name
    os.replace(tmp_path, claude_dir / ".alive_ports")
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
    extra_mounts = []
    git_file = Path.cwd() / ".git"
    if git_file.is_file():
        m = re.search(r"gitdir:\s*(.+)", git_file.read_text())
        if m:
            gitdir = m.group(1).strip()
            main_repo = Path(re.sub(r"/.git/worktrees/.*", "", gitdir))
            if (main_repo / ".git").is_dir():
                print(f"[claude] Worktree detected. Mounting main repo .git: {main_repo / '.git'}")
                extra_mounts += ["-v", f"{main_repo / '.git'}:{to_docker_path(main_repo / '.git')}"]

    # Live log prompt
    live_log_prompt = []
    if live_log_file:
        if "SESSION_ID" not in live_log_file:
            p = Path(live_log_file)
            live_log_file = str(p.with_name(p.stem + "-SESSION_ID" + p.suffix))
        ts_fallback = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"[claude] Live log: {live_log_file}")
        live_log_prompt = [
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
        ]

    # Platform-specific Docker args
    extra_docker_args = []
    if platform.system() == "Linux":
        extra_docker_args = ["--add-host=host.docker.internal:host-gateway"]

    cwd = Path.cwd()
    host_cwd = str(cwd)
    container_cwd = to_docker_path(cwd)
    host_ide = str(Path.home() / ".claude" / "ide")
    host_ide_backups = str(Path.home() / ".claude" / "ide-backups")

    env = os.environ.copy()
    env["CLAUDE_DIR"] = str(claude_dir)

    cmd = [
        "docker", "compose",
        "-f", str(compose_file),
        "run", "--rm",
        *compose_opts,
        *extra_docker_args,
        "-v", f"{host_cwd}:{container_cwd}",
        "-w", container_cwd,
        "-v", f"{host_ide}:/home/claudeuser/.claude/ide",
        "-v", f"{host_ide_backups}:/home/claudeuser/.claude/ide-backups",
        *extra_mounts,
        "claude",
        *live_log_prompt,
        *passthrough_args,
    ]

    if platform.system() == "Windows":
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    else:
        os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
