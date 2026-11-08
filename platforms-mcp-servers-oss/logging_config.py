#!/usr/bin/env python3
"""Shared logging setup for MCP server entrypoints."""

from __future__ import annotations

import copy
import logging
import os

import uvicorn

DEFAULT_LOG_FORMAT = "%(asctime)s - PID:%(process)d - %(name)s - %(levelname)s - %(message)s"

_SERVER_FILE_DEFAULTS = {
    "catalyst": ("CATALYST_LOG_FILE", "catalyst_center_mcp.log"),
    "meraki": ("MERAKI_LOG_FILE", "meraki_mcp.log"),
}


class _RootNameFilter(logging.Filter):
    def __init__(self, root_name: str):
        super().__init__()
        self.root_name = root_name

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "root":
            record.name = self.root_name
        return True


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _log_dir() -> str:
    log_dir = os.getenv("MCP_LOG_DIR", "logs").strip() or "logs"
    if os.path.isabs(log_dir):
        resolved = log_dir
    else:
        resolved = os.path.join(_repo_root(), log_dir)
    os.makedirs(resolved, exist_ok=True)
    return resolved


def get_server_log_path(server_family: str) -> str:
    file_env, default_file = _SERVER_FILE_DEFAULTS[server_family]
    filename = os.getenv(file_env, default_file).strip() or default_file
    return os.path.join(_log_dir(), filename)


def _log_mode() -> str:
    mode = os.getenv("MCP_LOG_MODE", "a").strip().lower()
    return "w" if mode == "w" else "a"


def _log_level() -> int:
    level_name = (os.getenv("MCP_LOG_LEVEL", "INFO") or "INFO").strip().upper()
    return getattr(logging, level_name, logging.INFO)


def _log_format() -> str:
    return os.getenv("MCP_LOG_FORMAT", DEFAULT_LOG_FORMAT).strip() or DEFAULT_LOG_FORMAT


def configure_server_logging(server_family: str, root_name: str) -> str:
    """Configure root logging to a stable per-server file."""
    log_path = get_server_log_path(server_family)
    handler = logging.FileHandler(log_path, mode=_log_mode())
    handler.addFilter(_RootNameFilter(root_name))
    logging.basicConfig(
        level=_log_level(),
        format=_log_format(),
        handlers=[handler],
        force=True,
    )
    return log_path


def build_uvicorn_log_config(server_family: str) -> dict:
    """Build uvicorn log config that writes to the same server log file."""
    log_path = get_server_log_path(server_family)
    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["formatters"]["default"]["fmt"] = _log_format()
    log_config["formatters"]["access"]["fmt"] = _log_format()
    log_config["handlers"]["default"] = {
        "class": "logging.FileHandler",
        "filename": log_path,
        "mode": _log_mode(),
        "formatter": "default",
    }
    log_config["handlers"]["access"] = {
        "class": "logging.FileHandler",
        "filename": log_path,
        "mode": _log_mode(),
        "formatter": "access",
    }
    return log_config
