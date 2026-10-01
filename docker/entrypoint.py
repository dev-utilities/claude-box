#!/usr/bin/env python3
"""claude-box container entrypoint — runs inside the container."""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

GUARD_LOG_MAX_BYTES = 524288  # 512 KB

# Fixed path where the launcher mounts the per-workspace state directory.
# Guard reads ports from here and writes ports.applied.
BOX_DIR = Path("/home/boxuser/.claude-box")


def main():
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    default_claude_str = os.environ.get("DEFAULT_CLAUDE_PATH", "")

    print(f"[entrypoint] ========== STARTUP ==========")
    print(f"[entrypoint] DEFAULT_CLAUDE_PATH={default_claude_str or '<not set>'}")
    print(f"[entrypoint] CLAUDE_CONFIG_DIR={config_dir}")

    # Determine shared dir (guard + IDE lock files)
    if default_claude_str:
        shared_dir = Path(default_claude_str)
        shared_ide = shared_dir / "ide"
        shared_ide.mkdir(parents=True, exist_ok=True)
        # Each container keeps its own copy of config_ide synced from shared_ide.
        # This avoids the symlink race when multiple containers share the same profile dir.
        config_ide = config_dir / "ide"
        if config_ide.is_symlink():
            config_ide.unlink()
        config_ide.mkdir(parents=True, exist_ok=True)
        _sync_ide_locks(shared_ide, config_ide)
        print(f"[entrypoint] IDE locks synced {shared_ide} -> {config_ide}")
    else:
        shared_dir = config_dir
        config_ide = None

    (shared_dir / "ide").mkdir(parents=True, exist_ok=True)
    (shared_dir / "ide-backups").mkdir(parents=True, exist_ok=True)

    print("[entrypoint] IDE dir contents at startup:")
    for p in sorted((shared_dir / "ide").iterdir()):
        print(f"  {p}")

    # Start guard as detached subprocess — outlives this process (which blocks below)
    guard_log_path = shared_dir / "guard.log"
    guard_args = [sys.executable, __file__, "--guard", str(shared_dir)]
    if config_ide is not None:
        guard_args.append(str(config_ide))
    guard_log = open(guard_log_path, "a")
    subprocess.Popen(guard_args, stdout=guard_log, stderr=guard_log)
    guard_log.close()
    print(f"[entrypoint] Guard started — log: {guard_log_path}")
    print(f"[entrypoint] Supervisor ready — awaiting sessions via docker exec")
    print(f"[entrypoint] =============================")

    # Block forever. Socat is managed by the guard via the ports file.
    # Sessions arrive via `docker exec`, not by re-running the entrypoint.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.pause()


def _sync_ide_locks(src: Path, dst: Path) -> None:
    src_names = set()
    for lockfile in src.glob("*.lock"):
        src_names.add(lockfile.name)
        target = dst / lockfile.name
        if not target.exists() or target.stat().st_mtime < lockfile.stat().st_mtime:
            shutil.copy2(lockfile, target)
    for stale in dst.glob("*.lock"):
        if stale.name not in src_names:
            stale.unlink(missing_ok=True)


# Per-guard socat process table: port -> Popen
_socat_procs: "dict[int, subprocess.Popen]" = {}


def _update_socat(glog) -> None:
    """Diff desired ports (ports file) against running socat children; start/stop as needed."""
    if not BOX_DIR.is_dir():
        return

    ports_file = BOX_DIR / "ports"
    desired: set = set()
    if ports_file.exists():
        try:
            for line in ports_file.read_text().splitlines():
                tok = line.strip()
                if tok.isdigit():
                    desired.add(int(tok))
        except Exception:
            pass

    running = set(_socat_procs.keys())

    # Start forwards for new ports
    for port in desired - running:
        try:
            log_path = BOX_DIR / f"socat-{port}.log"
            f = open(log_path, "a")
            proc = subprocess.Popen(
                ["socat",
                 f"TCP-LISTEN:{port},fork,reuseaddr",
                 f"TCP:host.docker.internal:{port}"],
                stdout=f, stderr=f,
            )
            f.close()
            _socat_procs[port] = proc
            glog(f"socat started port {port} (PID={proc.pid})")
        except Exception as e:
            glog(f"socat start failed port {port}: {e}")

    # Stop forwards for removed ports
    for port in running - desired:
        proc = _socat_procs.pop(port)
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        glog(f"socat stopped port {port}")

    # Reschedule crashed socat processes (they'll restart on the next cycle)
    for port in list(_socat_procs):
        if _socat_procs[port].poll() is not None:
            glog(f"socat port {port} died unexpectedly, will restart next cycle")
            del _socat_procs[port]

    # Write the applied set for the host launcher's startup wait
    try:
        (BOX_DIR / "ports.applied").write_text(
            "\n".join(str(p) for p in sorted(_socat_procs.keys()))
        )
    except Exception:
        pass


def run_guard(shared_dir: Path, config_ide: "Path | None" = None):
    guard_uuid = _read_uuid()
    ide_dir = shared_dir / "ide"
    backup_dir = shared_dir / "ide-backups"
    heartbeat_file = shared_dir / ".guard-heartbeat"
    alive_ports_file = shared_dir / ".alive_ports"
    guard_log = shared_dir / "guard.log"

    def glog(msg):
        ts = time.strftime("%H:%M:%S")
        with open(guard_log, "a") as f:
            f.write(f"[guard {ts}] {msg}\n")

    def truncate_log():
        if guard_log.exists() and guard_log.stat().st_size > GUARD_LOG_MAX_BYTES:
            lines = guard_log.read_text().splitlines()
            guard_log.write_text("\n".join(lines[-500:]) + "\n")

    glog(f"Guard UUID: {guard_uuid}")

    loop_count = 0
    was_leader = False

    while True:
        now_ms = int(time.time() * 1000)
        loop_count += 1
        if loop_count % 300 == 0:
            truncate_log()

        # Socat management — not leader-gated; each container owns its own forwards
        _update_socat(glog)

        # Per-container IDE lock sync — not leader-gated either
        if config_ide is not None:
            _sync_ide_locks(ide_dir, config_ide)

        # Leader election: only one guard handles shared backup/restore
        if heartbeat_file.exists():
            try:
                hb_uuid, hb_time_str = heartbeat_file.read_text().strip().split(":", 1)
                if hb_uuid != guard_uuid and (now_ms - int(hb_time_str)) < 500:
                    was_leader = False
                    time.sleep(0.3)
                    continue
            except Exception:
                pass

        # Claim leadership with a brief race window
        heartbeat_file.write_text(f"{guard_uuid}:{now_ms}")
        time.sleep(0.05)
        try:
            current_leader = heartbeat_file.read_text().strip().split(":", 1)[0]
            if current_leader != guard_uuid:
                was_leader = False
                time.sleep(0.3)
                continue
        except Exception:
            pass

        if not was_leader:
            glog(f"Became leader (UUID={guard_uuid})")
            was_leader = True

        # Back up new lock files
        for lockfile in ide_dir.glob("*.lock"):
            backup = backup_dir / lockfile.name
            if not backup.exists():
                shutil.copy2(lockfile, backup)
                glog(f"Backed up lock file: {lockfile.name}")

        # Restore deleted lock files if port is still alive
        alive_ports: set[str] = set()
        alive_ports_known = alive_ports_file.exists()
        if alive_ports_known:
            alive_ports = set(alive_ports_file.read_text().split())

        for backup in backup_dir.glob("*.lock"):
            port = backup.stem
            if alive_ports_known and port not in alive_ports:
                backup.unlink()
                glog(f"IDE port {port} no longer alive, removing backup: {backup.name}")
                continue
            original = ide_dir / backup.name
            if not original.exists():
                try:
                    shutil.copy2(backup, original)
                    glog(f"Restored lock file: {backup.name}")
                except Exception:
                    pass

        time.sleep(0.3)


def _read_uuid() -> str:
    try:
        return Path("/proc/sys/kernel/random/uuid").read_text().strip()
    except Exception:
        import socket
        return f"{socket.gethostname()}-{os.getpid()}-{int(time.time() * 1e9)}"


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--guard":
        run_guard(Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) >= 4 else None)
    else:
        main()
