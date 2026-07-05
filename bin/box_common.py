"""Shared helpers for the claude-box host-side launchers."""

import os
import platform
import re
import subprocess
import sys
from pathlib import Path


def to_docker_path(p: Path) -> str:
    """Convert a host path to the equivalent Linux path inside the container."""
    if platform.system() == "Windows":
        s = str(p)
        drive, rest = os.path.splitdrive(s)
        return f"/{drive[0].lower()}{rest.replace(chr(92), '/')}"
    return str(p)


def ensure_image(image: str, dockerfile: Path, context: Path, rebuild: bool) -> None:
    """Build the image if a rebuild was requested or it doesn't exist locally."""
    if not rebuild:
        inspect = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if inspect.returncode == 0:
            return
    build = subprocess.run(["docker", "build", "-f", str(dockerfile), "-t", image, str(context)])
    if build.returncode != 0:
        sys.exit(build.returncode)


def main_git_mount(workspace: Path, tag: str) -> "list[str]":
    """Return -v args mounting the main repo's .git when workspace is a linked worktree."""
    git_file = workspace / ".git"
    if not git_file.is_file():
        return []
    match = re.search(r"gitdir:\s*(.+)", git_file.read_text())
    if not match:
        return []
    gitdir = Path(match.group(1).strip())
    if not gitdir.is_absolute():
        gitdir = (workspace / gitdir).resolve()
    parts = gitdir.parts
    if ".git" not in parts:
        return []
    main_git = Path(*parts[: parts.index(".git") + 1])
    if main_git.is_dir():
        print(f"[{tag}] Worktree detected. Mounting main repo .git: {main_git}")
        return ["-v", f"{main_git}:{to_docker_path(main_git)}"]
    return []


def run_or_exec(cmd: "list[str]") -> None:
    """Hand the terminal over to docker: exec on POSIX, wait-and-exit on Windows."""
    sys.stdout.flush()
    if platform.system() == "Windows":
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    os.execvp(cmd[0], cmd)
