#!/usr/bin/env python3
"""Report remote MCP availability without exposing endpoints or credentials."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from dotenv import dotenv_values

INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {
            "name": "mcp-ai-agent-lab-status",
            "version": "1.0.0",
        },
    },
}


def is_configured(value: str | None) -> bool:
    """Return whether an environment value is nonempty and not a placeholder."""
    return bool(value) and "replace" not in value.lower()


def valid_splunk_endpoint(
    endpoint: str | None,
    allowed_domains: set[str] | None = None,
) -> bool:
    """Validate the expected Splunk endpoint without displaying it."""
    if not endpoint or "replace" in endpoint.lower():
        return False
    try:
        parsed = urlparse(endpoint)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and (
                allowed_domains is None
                or parsed.hostname in allowed_domains
            )
            and parsed.port in (None, 443)
            and (
                parsed.path.rstrip("/")
                == "/en-US/splunkd/__raw/services/mcp"
            )
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


async def check_mcp(
    name: str,
    url: str,
    *,
    bearer: str | None = None,
    verify_tls: bool = True,
) -> str:
    """Send an MCP initialize request and return a credential-safe status."""
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            verify=verify_tls,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json=INITIALIZE_REQUEST,
            )
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                close_headers = {**headers, "mcp-session-id": session_id}
                try:
                    await client.delete(url, headers=close_headers)
                except httpx.HTTPError:
                    pass
    except httpx.TimeoutException:
        return f"{name}: UNAVAILABLE (timeout)"
    except httpx.ConnectError:
        return f"{name}: UNAVAILABLE (connection or TLS failure)"
    except httpx.HTTPError:
        return f"{name}: UNAVAILABLE (HTTP transport failure)"

    if response.status_code in (401, 403):
        return f"{name}: REACHABLE (authentication failed: HTTP {response.status_code})"
    if response.status_code != 200:
        return f"{name}: REACHABLE (unexpected HTTP {response.status_code})"

    body = response.text
    if '"result"' in body and (
        '"serverInfo"' in body or '"capabilities"' in body
    ):
        return f"{name}: AVAILABLE"
    return f"{name}: REACHABLE (unexpected MCP initialize response)"


async def run_checks() -> list[str]:
    """Build and run all configured remote MCP checks concurrently."""
    env_path = Path(os.environ.get("LAB_ENV", Path.home() / "lab.env"))
    values = dotenv_values(env_path) if env_path.is_file() else {}
    repo_root = Path(__file__).resolve().parent.parent
    librechat_config = yaml.safe_load(
        (repo_root / "ai-agent-librechat-oss" / "librechat.yaml").read_text()
    )
    allowed_domains = set(
        librechat_config.get("mcpSettings", {}).get("allowedDomains", [])
    )
    checks: list[Awaitable[str]] = []
    positions: list[tuple[int, str]] = []
    results: list[str | None] = [None, None, None]

    splunk_endpoint = values.get("SPLUNK_MCP_EP")
    splunk_bearer = values.get("SPLUNK_MCP_BEARER")
    if (
        valid_splunk_endpoint(splunk_endpoint, allowed_domains)
        and is_configured(splunk_bearer)
    ):
        positions.append((0, "Splunk MCP"))
        checks.append(
            check_mcp(
                "Splunk MCP",
                str(splunk_endpoint),
                bearer=str(splunk_bearer),
            )
        )
    else:
        results[0] = "Splunk MCP: NOT CONFIGURED"

    thousandeyes_key = values.get("THOUSANDEYES_API_KEY")
    if is_configured(thousandeyes_key):
        positions.append((1, "ThousandEyes MCP"))
        checks.append(
            check_mcp(
                "ThousandEyes MCP",
                "https://api.thousandeyes.com/mcp",
                bearer=str(thousandeyes_key),
            )
        )
    else:
        results[1] = "ThousandEyes MCP: NOT CONFIGURED"

    positions.append((2, "draw.io MCP"))
    checks.append(check_mcp("draw.io MCP", "https://mcp.draw.io/mcp"))

    completed = await asyncio.gather(*checks)
    for (position, _name), result in zip(positions, completed, strict=True):
        results[position] = result

    return [result for result in results if result is not None]


def main() -> None:
    for result in asyncio.run(run_checks()):
        print(result)


if __name__ == "__main__":
    main()
