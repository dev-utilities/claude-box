#!/usr/bin/env python3
"""codex-box host-side launcher — runs Codex CLI inside Docker."""

import argparse
import os
import platform
import sys
from pathlib import Path

from box_common import ensure_image, main_git_mount, run_or_exec, to_docker_path


def main():
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    container_codex_home = "/home/codexuser/.codex"
    codex_dir = Path(os.environ.get("CODEX_BOX_DIR", str(Path.home() / ".codex")))
    codex_dir.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--yolo", action="store_true")
    parsed, passthrough_args = parser.parse_known_args()

    if parsed.yolo:
        passthrough_args.append("--dangerously-bypass-approvals-and-sandbox")

    docker_dir = repo_root / "docker"
    ensure_image("codex-secure:latest", docker_dir / "Dockerfile.codex", docker_dir, parsed.rebuild)

    # Mount only the current directory (like claude.py) so Codex cannot touch
    # sibling worktrees or the rest of the repo when launched from a subdir.
    cwd = Path.cwd()
    host_cwd = str(cwd)
    container_cwd = to_docker_path(cwd)

    worktree_args = []
    initial_prompt_args = []
    if (cwd / ".git").is_file():
        if platform.system() == "Windows":
            print(
                "[codex] Git worktree detected on Windows. The .git file may contain a "
                "Windows path that Linux git inside the container cannot resolve."
            )
            # Pre-warn Codex itself, but only in interactive mode — a positional
            # prompt in front of a subcommand (exec, resume, login, ...) would break it.
            if not passthrough_args or passthrough_args[0].startswith("-"):
                initial_prompt_args = [
                    "Important: this session is running inside a git worktree on Windows. "
                    "The .git file contains a Windows-format path (e.g. C:\\Users\\...) that "
                    "Linux git inside this container cannot resolve. Git operations that "
                    "traverse the worktree link (git status, git log, git diff across the "
                    "worktree, etc.) are likely to fail. Non-worktree git repos work fine. "
                    "Be cautious before running any git command that depends on worktree "
                    "metadata, and warn the user if you anticipate a failure."
                ]
        else:
            worktree_args = main_git_mount(cwd, "codex")

    extra_docker_args = []
    if platform.system() == "Linux":
        extra_docker_args = ["--add-host=host.docker.internal:host-gateway"]

    env_args = []
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
        if os.environ.get(var):
            env_args += ["-e", var]

    print(f"[codex] CODEX_HOME: {codex_dir}")

    tty_args = ["-t"] if sys.stdin.isatty() else []
    cmd = [
        "docker", "run", "--rm", "-i", *tty_args,
        *extra_docker_args,
        *env_args,
        "-v", f"{codex_dir}:{container_codex_home}",
        "-v", f"{host_cwd}:{container_cwd}",
        "-w", container_cwd,
        *worktree_args,
        "codex-secure:latest",
        *initial_prompt_args,
        *passthrough_args,
    ]

    run_or_exec(cmd)


if __name__ == "__main__":
    main()
