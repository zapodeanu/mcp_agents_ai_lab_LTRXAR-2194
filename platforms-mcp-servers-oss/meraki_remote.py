#!/usr/bin/env python3
"""
Meraki FastMCP streamable HTTP entrypoint.
Do not add tool logic here; keep logic in meraki_core.py.
"""

import argparse
from contextlib import asynccontextmanager
import hmac
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from meraki_core import build_meraki_fastmcp
from logging_config import build_uvicorn_log_config, configure_server_logging
import uvicorn

WRAPPER_LOGGER = logging.getLogger("meraki_remote_wrapper")
_BANNER_LINE = "=" * 80
_API_KEY_ENV_NAME = "MCP_API_KEY"
_API_KEY_HEADER_NAME = "x-api-key"
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meraki FastMCP Remote Server")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"), help="Host to bind to (default: MCP_HOST or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8001, help="Port to listen on (default: 8001)")
    parser.add_argument(
        "--ssl-certfile",
        default=None,
        help="Optional TLS certificate path for HTTPS listener",
    )
    parser.add_argument(
        "--ssl-keyfile",
        default=None,
        help="Optional TLS private key path for HTTPS listener",
    )
    args = parser.parse_args()
    configure_server_logging("meraki", "meraki_core")
    certfile = args.ssl_certfile or os.getenv("MCP_SSL_CERTFILE")
    keyfile = args.ssl_keyfile or os.getenv("MCP_SSL_KEYFILE")
    tls_enabled = bool(certfile and keyfile)

    if certfile:
        certfile = str(Path(certfile).expanduser())
    if keyfile:
        keyfile = str(Path(keyfile).expanduser())
    if (certfile and not keyfile) or (keyfile and not certfile):
        raise RuntimeError("Both --ssl-certfile and --ssl-keyfile are required to enable TLS.")

    meraki_base_url = os.getenv("MERAKI_BASE_URL", "https://api.meraki.com/api/v1")
    WRAPPER_LOGGER.info(_BANNER_LINE)
    WRAPPER_LOGGER.info("Meraki FastMCP Server Started (streamable-http)")
    WRAPPER_LOGGER.info("Process ID: %s", os.getpid())
    WRAPPER_LOGGER.info("Meraki Base URL: %s", meraki_base_url)
    WRAPPER_LOGGER.info(
        "Listen: %s://%s:%s/mcp",
        "https" if tls_enabled else "http",
        args.host,
        args.port,
    )
    WRAPPER_LOGGER.info(_BANNER_LINE)
    WRAPPER_LOGGER.info("Initializing Meraki FastMCP remote wrapper...")
    app = build_meraki_fastmcp(host=args.host, port=args.port)
    mcp_app = app.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    health_wrapper = FastAPI(lifespan=lifespan)
    api_key = os.getenv(_API_KEY_ENV_NAME, "").strip()
    if not api_key:
        raise RuntimeError(
            f"{_API_KEY_ENV_NAME} must be set for remote MCP server startup."
        )
    auth_enabled = True
    WRAPPER_LOGGER.info("Remote MCP API key auth enabled for /mcp")

    @health_wrapper.middleware("http")
    async def require_api_key_for_mcp(request: Request, call_next):
        if auth_enabled and request.url.path.startswith("/mcp"):
            candidate = request.headers.get(_API_KEY_HEADER_NAME, "").strip()
            if not candidate:
                return JSONResponse(
                    status_code=401,
                    content={"error": "missing api key"},
                )
            if not hmac.compare_digest(candidate, api_key):
                return JSONResponse(
                    status_code=403,
                    content={"error": "invalid api key"},
                )
        return await call_next(request)

    @health_wrapper.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "meraki-mcp"}

    health_wrapper.mount("/", mcp_app)

    uvicorn_log_config = build_uvicorn_log_config("meraki")
    uvicorn_config = uvicorn.Config(
        health_wrapper,
        host=args.host,
        port=args.port,
        log_level="info",
        log_config=uvicorn_log_config,
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )
    server = uvicorn.Server(uvicorn_config)
    server.run()
