#!/usr/bin/env python3
"""claude-box host-side launcher — runs on the host, not inside the container."""

import argparse
import datetime
import os
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from box_common import (
    BOX_STATE_ROOT,
    box_lock,
    cleanup_dangling_images,
    compute_hash,
    compute_name,
    container_needs_recreate,
    container_state,
    ensure_image,
    image_id,
    main_git_mount,
    parse_ports,
    register_session,
    run_session,
    scan_mcp_configs,
    start_commit_watcher,
    to_docker_path,
)


def find_profile() -> str:
    profile = os.environ.get("CLAUDE_BOX_PROFILE", "")
    if profile:
        return profile
    bp = Path.cwd() / ".claude" / "box-profile"
    return bp.read_text().strip() if bp.is_file() else ""


def is_port_alive(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("localhost", port)) == 0


def _write_ports(box_dir: Path, ports: "list[int]") -> None:
    """Write ports file atomically; clear ports.applied so the wait loop resets."""
    (box_dir / "ports.applied").unlink(missing_ok=True)
    tmp = box_dir / "ports.tmp"
    tmp.write_text("\n".join(str(p) for p in ports))
    os.replace(str(tmp), str(box_dir / "ports"))


def _wait_for_ports(box_dir: Path, requested: "set[str]") -> None:
    """Block up to 2 s for the guard to acknowledge all requested port forwards."""
    if not requested:
        return
    applied_file = box_dir / "ports.applied"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            applied = set(applied_file.read_text().split())
            if requested.issubset(applied):
                return
        except FileNotFoundError:
            pass
        time.sleep(0.1)
    print("[claude] ⚠️  Guard did not acknowledge port forwards within 2s, proceeding anyway")


def _ensure_container(
    box_dir: Path,
    container_name: str,
    profile: str,
    base_id: str,
    host_cwd: str,
    container_cwd: str,
    container_claude_dir: str,
    claude_dir: Path,
    creation_env_args: "list[str]",
    extra_docker_args: "list[str]",
    extra_mounts: "list[str]",
    start_image: str,
) -> Path:
    """Make sure the named container exists and is running, recreating if stale.

    Registers this session's marker in the same locked section — the same lock
    `_maybe_remove_container` takes before deciding to tear the container down,
    so a session can't be newly attaching while another, exiting session is
    mid-decision about whether it's the last one out.
    """
    with box_lock(box_dir):
        state = container_state(container_name)

        if state != "missing" and container_needs_recreate(container_name, profile, base_id):
            print("[claude] Container is stale (profile or base changed), recreating...")
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            state = "missing"

        if state == "missing":
            print(f"[claude] Creating container {container_name}...")
            r = subprocess.run([
                "docker", "run", "-d", "--init", "--name", container_name,
                "--label", "claude-box=1",
                "--label", f"claude-box.workspace={host_cwd}",
                "--label", f"claude-box.profile={profile}",
                "--label", f"claude-box.base={base_id}",
                *extra_docker_args,
                *creation_env_args,
                "-v", f"{claude_dir}:{container_claude_dir}",
                "-v", f"{host_cwd}:{container_cwd}",
                "-v", f"{str(box_dir)}:/home/boxuser/.claude-box",
                *extra_mounts,
                start_image,
            ])
            if r.returncode != 0:
                print("[claude] Failed to create container.", file=sys.stderr)
                sys.exit(1)
        elif state == "stopped":
            print(f"[claude] Starting stopped container {container_name}...")
            subprocess.run(["docker", "start", container_name], check=True)

        return register_session(box_dir)


def _do_prune() -> None:
    print("[claude] Pruning stale claude-box images and containers...")
    pruned = 0

    r = subprocess.run(
        ["docker", "images", "--filter", "label=claude-box.workspace",
         "--format", r'{{.ID}} {{index .Labels "claude-box.workspace"}}'],
        capture_output=True, text=True,
    )
    for line in r.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            img_id, ws = parts
            if not Path(ws).exists():
                subprocess.run(["docker", "rmi", img_id], capture_output=True)
                print(f"  Removed image {img_id[:12]} (workspace: {ws})")
                pruned += 1

    r = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=claude-box",
         "--format", r'{{.Names}} {{.Label "claude-box.workspace"}}'],
        capture_output=True, text=True,
    )
    for line in r.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            cname, ws = parts
            if not Path(ws).exists():
                subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
                print(f"  Removed container {cname} (workspace: {ws})")
                pruned += 1

    print(f"[claude] Pruned {pruned} item(s).")


def main():
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    container_claude_dir = "/home/boxuser/.claude"

    # Profile detection — CWD only, no upward walk
    profile = find_profile()
    suffix = f"-{profile}" if profile else ""
    claude_dir = Path.home() / f".claude{suffix}"
    host_main_claude = Path.home() / ".claude"
    host_main_claude.mkdir(parents=True, exist_ok=True)
    claude_dir.mkdir(parents=True, exist_ok=True)

    extra_mounts = []
    default_claude = "/home/boxuser/default-claude"
    if profile:
        # Remove stale symlinks that docker can't mount over
        for entry in ("ide", "ide-backups", ".alive_ports"):
            d = claude_dir / entry
            if d.is_symlink():
                d.unlink()
        extra_mounts.extend(["-v", f"{host_main_claude}:{default_claude}"])
        print(f"[claude] Profile: {profile} ({claude_dir})")
    else:
        print(f"[claude] No profile detected, using default ({claude_dir})")

    ide_dir = host_main_claude / "ide"
    ide_dir.mkdir(parents=True, exist_ok=True)
    (host_main_claude / "ide-backups").mkdir(parents=True, exist_ok=True)

    # Collect alive IDE ports
    alive_ports: list[int] = []
    for lockfile in sorted(ide_dir.glob("*.lock")):
        try:
            port = int(lockfile.stem)
            if is_port_alive(port):
                alive_ports.append(port)
        except ValueError:
            pass

    # Write .alive_ports (still used by the guard for IDE lock restore)
    with tempfile.NamedTemporaryFile("w", dir=host_main_claude, delete=False, suffix=".tmp") as f:
        f.write("\n".join(str(p) for p in alive_ports))
        tmp_path = f.name
    os.replace(tmp_path, host_main_claude / ".alive_ports")
    print(f"[claude] Alive IDE ports: {' '.join(str(p) for p in alive_ports) or 'none'}")

    # Arg parsing
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--yolo", action="store_true")
    parser.add_argument("--live-log", dest="live_log", default=os.environ.get("CLAUDE_BOX_LIVE_LOG", ""))
    parser.add_argument("--forward-port", dest="forward_ports", action="append", default=[])
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--prune", action="store_true")
    parsed, passthrough_args = parser.parse_known_args()

    if parsed.yolo:
        passthrough_args.append("--dangerously-skip-permissions")

    cwd = Path.cwd()
    ws_hash = compute_hash(cwd, profile)
    container_name = compute_name(cwd, profile)
    committed_image = f"claudebox-img-{ws_hash}:latest"
    box_dir = BOX_STATE_ROOT / ws_hash
    box_dir.mkdir(parents=True, exist_ok=True)

    # Management commands — handled before image/container work
    if parsed.stop:
        print(f"[claude] Stopping {container_name}...")
        subprocess.run(["docker", "stop", container_name])
        return
    if parsed.clean:
        print(f"[claude] Cleaning {container_name} and {committed_image}...")
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        subprocess.run(["docker", "rmi", committed_image], capture_output=True)
        removed = cleanup_dangling_images(str(cwd))
        if removed:
            print(f"[claude] Removed {removed} dangling image(s).")
        print("[claude] Done.")
        return
    if parsed.prune:
        _do_prune()
        return

    # Best-effort, non-blocking, scoped to this workspace only: sweep any of its
    # own dangling images left over from a prior commit/retag (e.g. a watcher
    # that committed but crashed before its own cleanup ran). Fire-and-forget —
    # correctness doesn't depend on it finishing before the session starts, and
    # docker refuses to remove an image still in use, so it can't touch
    # anything live.
    threading.Thread(target=cleanup_dangling_images, args=(str(cwd),), daemon=True).start()

    docker_dir = repo_root / "docker"
    ensure_image("claude-secure:latest", docker_dir / "Dockerfile.claude", docker_dir, parsed.rebuild)
    base_id = image_id("claude-secure:latest")

    # Resolve start image: use committed image if it was built from the current base
    start_image = "claude-secure:latest"
    committed_base = ""
    r = subprocess.run(
        ["docker", "inspect", "-f", '{{index .Config.Labels "claude-box.base"}}', committed_image],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        committed_base = r.stdout.strip()
        if committed_base and committed_base == base_id:
            start_image = committed_image
        else:
            print("[claude] Committed image is stale (base rebuilt), starting from base")
    print(f"[claude] Start image: {start_image}")

    # Ports to forward host -> container: auto-detected MCP server ports, plus
    # whatever the user named explicitly via --forward-port / CLAUDE_BOX_FORWARD_PORTS
    # (any host service the container needs to reach, not just MCP).
    mcp_ports: set[int] = set(scan_mcp_configs(claude_dir, cwd, "claude"))
    forward_ports: set[int] = set(
        parse_ports(os.environ.get("CLAUDE_BOX_FORWARD_PORTS", ""), *parsed.forward_ports)
    )
    sse_port = os.environ.get("CLAUDE_CODE_SSE_PORT", "")
    if sse_port.isdigit():
        sp = int(sse_port)
        if sp in mcp_ports:
            print(f"[claude] ⚠️  MCP port {sse_port} collides with CLAUDE_CODE_SSE_PORT — skipping it")
            mcp_ports.discard(sp)
        if sp in forward_ports:
            print(f"[claude] ⚠️  Forwarded port {sse_port} collides with CLAUDE_CODE_SSE_PORT — skipping it")
            forward_ports.discard(sp)

    # Write ports file for the guard (IDE + MCP + manually forwarded, combined)
    all_ports = sorted(set(alive_ports) | mcp_ports | forward_ports)
    _write_ports(box_dir, all_ports)
    if all_ports:
        print(f"[claude] Port forwards: {', '.join(str(p) for p in all_ports)}")

    # Git worktree detection
    initial_prompt = []
    git_file = cwd / ".git"
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
            extra_mounts += main_git_mount(cwd, "claude")

    # Live log prompt
    live_log_file = parsed.live_log
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

    # Platform-specific docker args
    extra_docker_args = []
    if platform.system() == "Linux":
        extra_docker_args = ["--add-host=host.docker.internal:host-gateway"]

    host_cwd = str(cwd)
    container_cwd = to_docker_path(cwd)

    # Creation-time env (baked into the container — no secrets here)
    creation_env_args = ["-e", f"CLAUDE_CONFIG_DIR={container_claude_dir}"]
    if profile:
        creation_env_args += ["-e", f"DEFAULT_CLAUDE_PATH={default_claude}"]

    # Per-exec env (fresh each session — delivered via docker exec -e)
    exec_env_args = []
    for var in ("CLAUDE_CODE_SSE_PORT", "ENABLE_IDE_INTEGRATION"):
        if os.environ.get(var):
            exec_env_args += ["-e", var]

    tty_args = ["-t"] if sys.stdin.isatty() else []
    initial_prompt_args = ["\n".join(initial_prompt)] if initial_prompt else []

    exec_cmd = [
        "docker", "exec", "-i", *tty_args,
        *exec_env_args,
        "-w", container_cwd,
        container_name,
        "claude",
        *initial_prompt_args,
        *passthrough_args,
    ]

    # Between the state check and the exec, another session's watcher may have
    # removed this container (last-session teardown race). Retry a bounded
    # number of times — but only when the container is actually gone/stopped
    # afterward; otherwise rc is claude's own exit code and must be propagated
    # as-is.
    MAX_EXEC_ATTEMPTS = 3
    rc = 1
    for attempt in range(1, MAX_EXEC_ATTEMPTS + 1):
        session_marker = _ensure_container(
            box_dir, container_name, profile, base_id, host_cwd, container_cwd,
            container_claude_dir, claude_dir, creation_env_args, extra_docker_args,
            extra_mounts, start_image,
        )
        _wait_for_ports(box_dir, {str(p) for p in all_ports})

        finish = start_commit_watcher(
            box_dir, container_name, committed_image, base_id, host_cwd, profile, session_marker,
        )
        rc = run_session(exec_cmd)
        finish()

        if rc == 0 or container_state(container_name) == "running":
            break
        if attempt < MAX_EXEC_ATTEMPTS:
            print(f"[claude] Container disappeared mid-exec (attempt {attempt}/{MAX_EXEC_ATTEMPTS}), retrying...")
    else:
        print("[claude] Gave up after repeated container-exec races.", file=sys.stderr)

    sys.exit(rc)


if __name__ == "__main__":
    main()
