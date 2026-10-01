"""Shared helpers for the claude-box host-side launchers."""

import contextlib
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

BASE_IMAGE = "box-base:latest"
BOX_STATE_ROOT: Path = Path.home() / ".claude-box"

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


def run_session(cmd: "list[str]") -> int:
    """Run docker as a subprocess and return its exit code.

    The launcher process stays alive after docker exits so a watcher thread can
    run teardown before the launcher exits. SIGINT is ignored here — the tty
    delivers it directly to the docker foreground process.
    """
    sys.stdout.flush()
    if platform.system() != "Windows":
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# Persistent container helpers
# ---------------------------------------------------------------------------

def compute_hash(cwd: Path, profile: str) -> str:
    """Stable 12-char hex key for (workspace, profile). Handles case/symlink variance."""
    key = f"{os.path.normcase(str(cwd.resolve()))}\0{profile}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def compute_name(cwd: Path, profile: str) -> str:
    """Deterministic container name — never stored, always recomputed."""
    h = compute_hash(cwd, profile)
    folder = re.sub(r"[^a-zA-Z0-9_.-]", "_", cwd.name)[:32]
    return f"claudebox_{folder}_{profile}_{h}"


def image_id(image: str) -> str:
    """Return the full SHA256 ID of a local image, or '' if it doesn't exist."""
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.Id}}", image],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def container_state(name: str) -> str:
    """Return 'missing', 'stopped', or 'running'."""
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}", name],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return "missing"
    return "running" if r.stdout.strip() == "running" else "stopped"


def _get_container_labels(name: str) -> "dict[str, str]":
    r = subprocess.run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "claude-box.profile"}} {{index .Config.Labels "claude-box.base"}}',
         name],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {}
    parts = r.stdout.strip().split(None, 1)
    return {
        "profile": parts[0] if parts else "",
        "base": parts[1] if len(parts) > 1 else "",
    }


def container_needs_recreate(name: str, profile: str, base_id: str) -> bool:
    """True if the container was created with a different profile or stale base image."""
    labels = _get_container_labels(name)
    if labels.get("profile", "") != profile:
        return True
    container_base = labels.get("base", "")
    if container_base and container_base != base_id:
        return True
    return False


@contextlib.contextmanager
def box_lock(box_dir: Path):
    """Per-workspace cross-process lock — serializes container state mutations."""
    lock_path = box_dir / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        if platform.system() != "Windows":
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if platform.system() != "Windows":
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_UN)


def _has_claude_sessions(name: str) -> bool:
    """True if the container has at least one running claude process (via docker top)."""
    r = subprocess.run(["docker", "top", name], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    lines = r.stdout.splitlines()
    if not lines:
        return False
    header = lines[0].split()
    try:
        cmd_idx = header.index("CMD")
    except ValueError:
        cmd_idx = len(header) - 1
    for line in lines[1:]:
        # CMD is the full command line (executable + args) and may itself
        # contain spaces, so it must stay unsplit — take only its first
        # token (the executable) to compare, not the last token of the row.
        parts = line.split(None, cmd_idx)
        if len(parts) <= cmd_idx:
            continue
        full_cmd = parts[cmd_idx]
        exe = full_cmd.split(None, 1)[0] if full_cmd else ""
        if exe == "claude" or exe.endswith("/claude"):
            return True
    return False


def _try_commit(
    box_dir: Path,
    name: str,
    committed_image: str,
    base_id: str,
    workspace: str,
    profile: str,
) -> None:
    """Claim the dirty flag and commit the container image. No-op if another watcher claimed it first."""
    dirty = box_dir / "dirty"
    try:
        entry = dirty.read_text().strip()
    except FileNotFoundError:
        return
    try:
        dirty.unlink()  # atomic claim — raises FileNotFoundError if another watcher won
    except FileNotFoundError:
        return
    except Exception:
        return

    old_id = image_id(committed_image)
    with box_lock(box_dir):
        r = subprocess.run([
            "docker", "commit",
            "--pause=false",
            "-m", entry or "claude-box: automatic commit",
            "-c", f"LABEL claude-box.base={base_id}",
            "-c", f"LABEL claude-box.workspace={workspace}",
            "-c", f"LABEL claude-box.profile={profile}",
            name, committed_image,
        ], capture_output=True)

    if r.returncode == 0 and old_id:
        # Remove the previous image now orphaned by the retag
        subprocess.run(["docker", "rmi", old_id], capture_output=True)


def _maybe_remove_container(name: str, box_dir: Path) -> None:
    """Remove the container if no claude sessions remain — called by last watcher out."""
    with box_lock(box_dir):
        if not _has_claude_sessions(name):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _commit_watcher(
    box_dir: Path,
    name: str,
    committed_image: str,
    base_id: str,
    workspace: str,
    profile: str,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        _try_commit(box_dir, name, committed_image, base_id, workspace, profile)
        stop_event.wait(timeout=2)
    # Final sweep after session ends
    _try_commit(box_dir, name, committed_image, base_id, workspace, profile)
    _maybe_remove_container(name, box_dir)


def start_commit_watcher(
    box_dir: Path,
    name: str,
    committed_image: str,
    base_id: str,
    workspace: str,
    profile: str,
) -> "callable":
    """Start the background commit watcher. Returns a finish() callable to block until teardown completes."""
    stop_event = threading.Event()
    t = threading.Thread(
        target=_commit_watcher,
        args=(box_dir, name, committed_image, base_id, workspace, profile, stop_event),
        daemon=True,
    )
    t.start()

    def finish() -> None:
        stop_event.set()
        t.join()

    return finish
