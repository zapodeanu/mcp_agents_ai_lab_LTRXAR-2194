#!/usr/bin/env python3
"""Secured streamable HTTP entry point for the Meraki Magic dynamic MCP."""

import argparse
from contextlib import asynccontextmanager
import hmac
import importlib.util
import os
from pathlib import Path
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn


SCRIPT_DIR = Path(__file__).resolve().parent
_API_KEY_ENV_NAME = "MCP_API_KEY"
_API_KEY_HEADER_NAME = "x-api-key"


def load_dynamic_mcp():
    """Load the hyphenated dynamic server module and return its FastMCP object."""
    module_path = SCRIPT_DIR / "meraki-mcp-dynamic.py"
    spec = importlib.util.spec_from_file_location("meraki_magic_dynamic_server", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Meraki Magic server from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.mcp


def api_key_error(path: str, candidate: str, expected: str) -> tuple[int, str] | None:
    """Return an HTTP error for an unauthorized MCP request."""
    if not path.startswith("/mcp"):
        return None
    if not candidate:
        return 401, "missing api key"
    if not hmac.compare_digest(candidate, expected):
        return 403, "invalid api key"
    return None


def build_http_app(mcp_server, api_key: str) -> FastAPI:
    """Wrap the FastMCP ASGI app with health and API-key middleware."""
    if not api_key:
        raise RuntimeError(
            f"{_API_KEY_ENV_NAME} must be set for remote MCP server startup."
        )

    mcp_app = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    wrapper = FastAPI(lifespan=lifespan)

    @wrapper.middleware("http")
    async def require_api_key_for_mcp(request: Request, call_next):
        error = api_key_error(
            request.url.path,
            request.headers.get(_API_KEY_HEADER_NAME, "").strip(),
            api_key,
        )
        if error:
            status_code, message = error
            return JSONResponse(status_code=status_code, content={"error": message})
        return await call_next(request)

    @wrapper.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "meraki-magic-mcp"}

    wrapper.mount("/", mcp_app)
    return wrapper


def optional_path(value: str | None) -> str | None:
    return str(Path(value).expanduser()) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Meraki Magic FastMCP HTTPS remote server"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MERAKI_MCP_HOST", "127.0.0.1"),
        help="Host to bind to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MERAKI_MCP_PORT", "8002")),
        help="Port to listen on",
    )
    parser.add_argument(
        "--ssl-certfile",
        default=os.getenv("MCP_SSL_CERTFILE"),
        help="TLS certificate path",
    )
    parser.add_argument(
        "--ssl-keyfile",
        default=os.getenv("MCP_SSL_KEYFILE"),
        help="TLS private-key path",
    )
    args = parser.parse_args()

    certfile = optional_path(args.ssl_certfile)
    keyfile = optional_path(args.ssl_keyfile)
    if bool(certfile) != bool(keyfile):
        raise RuntimeError(
            "Both --ssl-certfile and --ssl-keyfile are required to enable TLS."
        )
    for path in (certfile, keyfile):
        if path and not Path(path).is_file():
            raise RuntimeError(f"TLS file not found: {path}")

    mcp_server = load_dynamic_mcp()
    app = build_http_app(mcp_server, os.getenv(_API_KEY_ENV_NAME, "").strip())
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )


if __name__ == "__main__":
    main()
