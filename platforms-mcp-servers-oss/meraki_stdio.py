#!/usr/bin/env python3
"""
Meraki FastMCP stdio entrypoint.
Do not add tool logic here; keep logic in meraki_core.py.
"""

import logging
import os

from meraki_core import build_meraki_fastmcp
from logging_config import configure_server_logging

WRAPPER_LOGGER = logging.getLogger("meraki_stdio_wrapper")
_BANNER_LINE = "=" * 80


if __name__ == "__main__":
    configure_server_logging("meraki", "meraki_core")
    meraki_base_url = os.getenv("MERAKI_BASE_URL", "https://api.meraki.com/api/v1")
    WRAPPER_LOGGER.info(_BANNER_LINE)
    WRAPPER_LOGGER.info("Meraki FastMCP Server Started (stdio)")
    WRAPPER_LOGGER.info("Process ID: %s", os.getpid())
    WRAPPER_LOGGER.info("Meraki Base URL: %s", meraki_base_url)
    WRAPPER_LOGGER.info(_BANNER_LINE)
    WRAPPER_LOGGER.info("Initializing Meraki FastMCP stdio wrapper...")
    app = build_meraki_fastmcp()
    app.run(transport="stdio")
