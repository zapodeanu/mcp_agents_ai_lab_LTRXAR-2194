#!/usr/bin/env python3
"""Report how far a Sandbox has progressed through the lab build."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
VENV_PYTHON = ROOT / ".venv/bin/python"
LAB_ENV = Path(os.environ.get("LAB_ENV", HOME / "lab.env"))


@dataclass(frozen=True)
class Checkpoint:
    name: str
    passed: bool
    detail: str
    next_action: str


def run(
    command: list[str],
    *,
    timeout: int = 30,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def repository_checkpoint() -> Checkpoint:
    required = (
        ROOT / "Makefile",
        ROOT / "requirements.lock",
        ROOT / "docs/lab-guide.md",
        ROOT / "ai-agent-librechat-oss/librechat.yaml",
        ROOT / "platforms-mcp-servers-oss/catalyst_center_remote.py",
        ROOT / "meraki-magic-mcp-community/meraki_magic_remote.py",
    )
    passed = all(path.is_file() for path in required)
    return Checkpoint(
        "Repository",
        passed,
        "required lab files are present" if passed else "repository is incomplete",
        "Re-clone or update the repository with: git pull --ff-only",
    )


def host_checkpoint() -> Checkpoint:
    os_release: dict[str, str] = {}
    release_path = Path("/etc/os-release")
    if release_path.is_file():
        for line in release_path.read_text(errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os_release[key] = value.strip().strip('"')

    required_commands = ("curl", "git", "less", "lsof", "make", "openssl", "pipx")
    missing = [name for name in required_commands if shutil.which(name) is None]
    ubuntu_ok = (
        os_release.get("ID") == "ubuntu"
        and os_release.get("VERSION_ID") == "24.04"
    )
    passed = ubuntu_ok and not missing
    if not ubuntu_ok:
        detail = "Ubuntu 24.04 is required"
    elif missing:
        detail = f"missing commands: {', '.join(missing)}"
    else:
        detail = "Ubuntu 24.04 and common commands are ready"
    return Checkpoint(
        "Host prerequisites",
        passed,
        detail,
        "Complete Chapter 1.3 or run docs/setup-full-lab.sh",
    )


def python_checkpoint() -> Checkpoint:
    if not VENV_PYTHON.is_file():
        return Checkpoint(
            "Python environment",
            False,
            ".venv is missing",
            "Complete Chapter 1.5 and 1.6 or run docs/setup-full-lab.sh",
        )

    version = run(
        [
            str(VENV_PYTHON),
            "-c",
            "import sys; raise SystemExit(sys.version_info[:2] != (3, 13))",
        ]
    )
    dependencies = run([str(VENV_PYTHON), "-m", "pip", "check"], timeout=60)
    passed = bool(
        version
        and version.returncode == 0
        and dependencies
        and dependencies.returncode == 0
    )
    return Checkpoint(
        "Python environment",
        passed,
        "Python 3.13 and locked dependencies pass"
        if passed
        else "Python version or dependency validation failed",
        "Recreate .venv and install requirements.lock as shown in Chapter 1.6",
    )


def configuration_checkpoint() -> Checkpoint:
    mode_ok = False
    if LAB_ENV.is_file():
        mode_ok = LAB_ENV.stat().st_mode & 0o777 == 0o600

    validator = ROOT / "scripts/validate_lab_env.py"
    validation_env = os.environ.copy()
    validation_env["LAB_ENV"] = str(LAB_ENV)
    validation = (
        run(
            [str(VENV_PYTHON), str(validator)],
            env=validation_env,
        )
        if VENV_PYTHON.is_file() and validator.is_file()
        else None
    )
    passed = bool(mode_ok and validation and validation.returncode == 0)
    if not LAB_ENV.is_file():
        detail = "lab.env is missing"
    elif not mode_ok:
        detail = "lab.env permissions must be 600"
    elif not validation or validation.returncode != 0:
        detail = "lab.env validation failed"
    else:
        detail = "lab.env exists, is protected, and validates"
    return Checkpoint(
        "Protected configuration",
        passed,
        detail,
        "Ask the instructor to restore lab.env, run chmod 600, then make check-env",
    )


def host_services_checkpoint() -> Checkpoint:
    mongo = run(["systemctl", "is-active", "mongod"])
    nginx_present = shutil.which("nginx") is not None
    node = HOME / ".nvm/versions/node/v24.22.1/bin/node"
    npm = HOME / ".nvm/versions/node/v24.22.1/bin/npm"
    passed = bool(
        mongo
        and mongo.returncode == 0
        and mongo.stdout.strip() == "active"
        and nginx_present
        and node.is_file()
        and npm.is_file()
    )
    return Checkpoint(
        "Host services and Node.js",
        passed,
        "MongoDB, nginx, Node.js 24.22.1, and npm are ready"
        if passed
        else "one or more LibreChat host prerequisites are missing",
        "Complete Chapter 4.1 through 4.3 or run docs/setup-full-lab.sh",
    )


def librechat_install_checkpoint() -> Checkpoint:
    source = ROOT / "ai-agent-librechat-oss/librechat-src"
    required = (
        source / "node_modules",
        source / "client/dist/index.html",
        source / "librechat.yaml",
        source / ".env",
    )
    passed = all(path.exists() for path in required)
    return Checkpoint(
        "LibreChat installation",
        passed,
        "LibreChat dependencies, build, and runtime configuration are present"
        if passed
        else "LibreChat installation or generated files are incomplete",
        "Complete Chapter 4.7 or run docs/setup-full-lab.sh",
    )


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def health_ok(url: str, certificate: Path, *, expect_json: bool) -> bool:
    if not certificate.is_file():
        return False
    try:
        context = ssl.create_default_context(cafile=str(certificate))
        with urllib.request.urlopen(url, context=context, timeout=3) as response:
            if response.status != 200:
                return False
            if expect_json:
                return json.loads(response.read()).get("status") == "ok"
            return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def runtime_checkpoint() -> Checkpoint:
    certificate = ROOT / "certs/mcp-selfsigned.crt"
    ports_ok = all(port_open(port) for port in (8000, 8002, 3080, 3081))
    health_checks = (
        health_ok(
            "https://localhost:8000/health",
            certificate,
            expect_json=True,
        ),
        health_ok(
            "https://localhost:8002/health",
            certificate,
            expect_json=True,
        ),
        health_ok(
            "https://localhost:3080/",
            certificate,
            expect_json=False,
        ),
    )
    passed = ports_ok and all(health_checks)
    return Checkpoint(
        "Local runtime",
        passed,
        "all four listeners and three HTTPS health checks pass"
        if passed
        else "one or more local listeners or health checks are not ready",
        "Run make up, then make status; inspect component logs if startup fails",
    )


def mcp_initialization_checkpoint(runtime_ready: bool) -> Checkpoint:
    log_path = ROOT / "ai-agent-librechat-oss/logs/ai_agent_librechat.log"
    marker = "Initialized with 5 configured servers"
    marker_present = False
    if runtime_ready:
        deadline = time.monotonic() + 45
        waiting_announced = False
        while time.monotonic() < deadline:
            log = (
                log_path.read_text(errors="replace")
                if log_path.is_file()
                else ""
            )
            if marker in log:
                marker_present = True
                break
            if not waiting_announced:
                print(
                    "Waiting up to 45 seconds for MCP initialization...",
                    flush=True,
                )
                waiting_announced = True
            time.sleep(1)

    ready = runtime_ready and marker_present
    if ready:
        detail = "LibreChat initialized five configured MCP servers"
    elif not runtime_ready:
        detail = "local runtime is stopped; initialization is not current"
    else:
        detail = "the five-server initialization marker is not present"
    return Checkpoint(
        "LibreChat MCP initialization",
        ready,
        detail,
        "Inspect the LibreChat log and use Proctor Guide section 7",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report the completed local lab-build checkpoints.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="run make status after all local checkpoints pass",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("Lab build progress")
    print("==================")
    checkpoints: list[Checkpoint] = []
    initial_checkpoints = (
        repository_checkpoint(),
        host_checkpoint(),
        python_checkpoint(),
        configuration_checkpoint(),
        host_services_checkpoint(),
        librechat_install_checkpoint(),
    )

    for number, checkpoint in enumerate(initial_checkpoints, start=1):
        checkpoints.append(checkpoint)
        label = "PASS" if checkpoint.passed else "NOT READY"
        print(
            f"[{label}] {number}. {checkpoint.name}: {checkpoint.detail}",
            flush=True,
        )

    runtime = runtime_checkpoint()
    checkpoints.append(runtime)
    runtime_label = "PASS" if runtime.passed else "NOT READY"
    print(
        f"[{runtime_label}] 7. {runtime.name}: {runtime.detail}",
        flush=True,
    )

    mcp_initialization = mcp_initialization_checkpoint(runtime.passed)
    checkpoints.append(mcp_initialization)
    mcp_label = "PASS" if mcp_initialization.passed else "NOT READY"
    print(f"[{mcp_label}] 8. {mcp_initialization.name}: {mcp_initialization.detail}")

    completed = 0
    for checkpoint in checkpoints:
        if not checkpoint.passed:
            break
        completed += 1

    print()
    print(f"Sequential progress: {completed}/{len(checkpoints)} checkpoints")
    if completed < len(checkpoints):
        blocked = checkpoints[completed]
        print(f"Next checkpoint: {blocked.name}")
        print(f"Next action: {blocked.next_action}")
    else:
        print("Local build: COMPLETE")

    if args.live:
        print()
        if completed != len(checkpoints):
            print("Live status skipped until all local checkpoints pass.")
        else:
            print("Live remote MCP and model status")
            print("================================")
            status = subprocess.run(
                ["make", "status"],
                cwd=ROOT,
                check=False,
            )
            if status.returncode != 0:
                return status.returncode

    print()
    return 0 if completed == len(checkpoints) else 1


if __name__ == "__main__":
    sys.exit(main())
