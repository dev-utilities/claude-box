"""Shared helpers for the claude-box host-side launchers."""

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

BASE_IMAGE = "box-base:latest"

# Path prefixes that exist on the host but never inside the container.
_HOST_ONLY_PREFIXES = ("/Users/", "/opt/homebrew", "/Volumes/")
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def to_docker_path(p: Path) -> str:
    """Convert a host path to the equivalent Linux path inside the container."""
    if platform.system() == "Windows":
        s = str(p)
        drive, rest = os.path.splitdrive(s)
        return f"/{drive[0].lower()}{rest.replace(chr(92), '/')}"
    return str(p)


def _image_exists(image: str) -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_image(image: str, dockerfile: Path, context: Path, rebuild: bool) -> None:
    """Build the shared base and the requested image if needed."""
    if not rebuild and _image_exists(image):
        return
    base_dockerfile = Path(dockerfile).parent / "Dockerfile.base"
    if base_dockerfile.is_file() and (rebuild or not _image_exists(BASE_IMAGE)):
        build = subprocess.run(
            ["docker", "build", "-f", str(base_dockerfile), "-t", BASE_IMAGE, str(context)]
        )
        if build.returncode != 0:
            sys.exit(build.returncode)
    build = subprocess.run(["docker", "build", "-f", str(dockerfile), "-t", image, str(context)])
    if build.returncode != 0:
        sys.exit(build.returncode)


def _is_host_only_path(s: str, home: str) -> bool:
    """True if s looks like a path that exists on the host but not in the container."""
    if _WIN_DRIVE_RE.match(s):
        return True
    if s.startswith(_HOST_ONLY_PREFIXES):
        return True
    # The host user's home dir (e.g. /home/faizan) is not the container home.
    return bool(home) and s.startswith(home + os.sep)


def scan_mcp_configs(claude_dir: Path, cwd: Path, tag: str) -> "list[int]":
    """Return localhost HTTP/SSE ports from MCP configs; warn on host-path commands.

    Best-effort: a malformed config must never block launch.
    """
    servers = {}
    try:
        data = json.loads((claude_dir / ".claude.json").read_text())
        servers.update(data.get("mcpServers") or {})
        project = (data.get("projects") or {}).get(to_docker_path(cwd)) or {}
        servers.update(project.get("mcpServers") or {})
    except Exception:
        pass
    try:
        data = json.loads((cwd / ".mcp.json").read_text())
        servers.update(data.get("mcpServers") or {})
    except Exception:
        pass

    home = str(Path.home())
    ports = set()
    for name, srv in servers.items():
        if not isinstance(srv, dict):
            continue
        url = srv.get("url") or ""
        if url:
            m = re.match(r"https?://(?:localhost|127\.0\.0\.1):(\d+)", url)
            if m:
                ports.add(int(m.group(1)))
            continue
        command = srv.get("command") or ""
        args = srv.get("args") or []
        host_paths = [
            s for s in [command, *args]
            if isinstance(s, str) and _is_host_only_path(s, home)
        ]
        if host_paths:
            print(
                f"[{tag}] ⚠️  MCP server '{name}' references a host path "
                f"({host_paths[0]}) that won't exist in the container. "
                f"Run it in-container instead, or expose it over HTTP on the host "
                f"(see readme, MCP section)."
            )
    return sorted(ports)


def parse_ports(*specs: str) -> "list[int]":
    """Parse comma/space-separated port lists, ignoring junk."""
    ports = set()
    for spec in specs:
        for tok in re.split(r"[,\s]+", spec or ""):
            if tok.isdigit():
                ports.add(int(tok))
    return sorted(ports)


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
