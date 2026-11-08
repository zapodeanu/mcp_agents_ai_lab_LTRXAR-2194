#!/usr/bin/env python3
"""
Catalyst Center FastMCP stdio entrypoint.
Do not add tool logic here; keep logic in catalyst_center_core.py.
"""

import logging
import os

from catalyst_center_core import build_catalyst_center_fastmcp
from logging_config import configure_server_logging

WRAPPER_LOGGER = logging.getLogger("catalyst_center_stdio_wrapper")
_BANNER_LINE = "=" * 80


if __name__ == "__main__":
    configure_server_logging("catalyst", "catalyst_center_core")
    WRAPPER_LOGGER.info(_BANNER_LINE)
    WRAPPER_LOGGER.info("Catalyst Center FastMCP Server Started (stdio)")
    WRAPPER_LOGGER.info("Process ID: %s", os.getpid())
    WRAPPER_LOGGER.info(_BANNER_LINE)
    WRAPPER_LOGGER.info("Initializing Catalyst Center FastMCP stdio wrapper...")
    app = build_catalyst_center_fastmcp()
    app.run(transport="stdio")
