#!/usr/bin/env python3
"""Launch one command in a detached session and record its process ID."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    log_path = Path(args.log_file).expanduser().resolve()
    pid_path = Path(args.pid_file).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("ab", buffering=0) as log_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
