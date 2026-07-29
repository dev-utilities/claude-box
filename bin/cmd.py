#!/usr/bin/env python3
"""cmd-box host-side launcher — runs Command Code CLI inside Docker."""

import argparse
import os
import platform
import sys
from pathlib import Path

from box_common import ensure_image, main_git_mount, run_or_exec, to_docker_path


def main():
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    container_cc_home = "/home/boxuser/.commandcode"
    cc_dir = Path(os.environ.get("COMMAND_CODE_BOX_DIR", str(Path.home() / ".commandcode")))
    cc_dir.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--rebuild", action="store_true")
    parsed, passthrough_args = parser.parse_known_args()

    docker_dir = repo_root / "docker"
    ensure_image("command-code-secure:latest", docker_dir / "Dockerfile.command-code", docker_dir, parsed.rebuild)

    # Mount only the current directory (like claude.py / codex.py) so Command Code
    # cannot touch sibling worktrees or the rest of the repo when launched from a subdir.
    cwd = Path.cwd()
    host_cwd = str(cwd)
    container_cwd = to_docker_path(cwd)

    worktree_args = []
    if (cwd / ".git").is_file():
        if platform.system() == "Windows":
            print(
                "[cmd] Git worktree detected on Windows. The .git file may contain a "
                "Windows path that Linux git inside the container cannot resolve."
            )
        else:
            worktree_args = main_git_mount(cwd, "cmd")

    extra_docker_args = []
    if platform.system() == "Linux":
        extra_docker_args = ["--add-host=host.docker.internal:host-gateway"]

    env_args = []
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "MOONSHOT_API_KEY",
        "DEEPSEEK_API_KEY",
        "ZHIPU_API_KEY",
        "QWEN_API_KEY",
        "MINIMAX_API_KEY",
    ):
        if os.environ.get(var):
            env_args += ["-e", var]

    print(f"[cmd] Config dir: {cc_dir}")

    tty_args = ["-t"] if sys.stdin.isatty() else []
    cmd = [
        "docker", "run", "--rm", "-i", *tty_args,
        *extra_docker_args,
        *env_args,
        "-v", f"{cc_dir}:{container_cc_home}",
        "-v", f"{host_cwd}:{container_cwd}",
        "-w", container_cwd,
        *worktree_args,
        "command-code-secure:latest",
        *passthrough_args,
    ]

    run_or_exec(cmd)


if __name__ == "__main__":
    main()
