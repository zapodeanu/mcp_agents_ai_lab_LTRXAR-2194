#!/usr/bin/env python3
"""Validate lab configuration without printing secret values."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[1]
LAB_ENV = Path(os.environ.get("LAB_ENV", Path.home() / "lab.env"))

values = dotenv_values(LAB_ENV)
required = (
    "MCP_API_KEY",
    "CC_USER",
    "CC_PASS",
    "MERAKI_API_KEY",
    "MERAKI_ORG_ID",
    "READ_ONLY_MODE",
    "CREDS_KEY",
    "CREDS_IV",
    "JWT_SECRET",
    "JWT_REFRESH_SECRET",
    "MEILI_MASTER_KEY",
    "BEDROCK_AWS_DEFAULT_REGION",
    "BEDROCK_AWS_MODELS",
    "BEDROCK_INFERENCE_PROFILE_CLAUDE_SONNET",
    "LITELLM_API_KEY",
    "SPLUNK_MCP_BEARER",
    "SPLUNK_MCP_EP",
    "THOUSANDEYES_API_KEY",
)
missing = [
    name
    for name in required
    if not values.get(name) or str(values[name]).lower().startswith("replace")
]
if missing:
    print("Lab configuration is incomplete:")
    for name in missing:
        print(f"  - {name}")
    print("Ask the instructor to correct the preconfigured lab.env.")
    raise SystemExit(2)

if str(values["READ_ONLY_MODE"]).lower() != "true":
    print("READ_ONLY_MODE must be true for the student lab.")
    raise SystemExit(2)

access_key = str(values.get("BEDROCK_AWS_ACCESS_KEY_ID") or "")
secret_key = str(values.get("BEDROCK_AWS_SECRET_ACCESS_KEY") or "")
session_token = str(values.get("BEDROCK_AWS_SESSION_TOKEN") or "")
if bool(access_key) != bool(secret_key):
    print("Bedrock static credentials must provide both the access key and secret.")
    raise SystemExit(2)
if access_key.startswith("ASIA") and not session_token:
    print("Temporary Bedrock credentials require BEDROCK_AWS_SESSION_TOKEN.")
    raise SystemExit(2)

try:
    splunk_endpoint = urlparse(str(values["SPLUNK_MCP_EP"]))
    librechat_config = yaml.safe_load(
        (REPO_ROOT / "ai-agent-librechat-oss/librechat.yaml").read_text()
    )
    allowed_domains = set(
        librechat_config.get("mcpSettings", {}).get("allowedDomains", [])
    )
    splunk_endpoint_valid = (
        splunk_endpoint.scheme == "https"
        and bool(splunk_endpoint.hostname)
        and not splunk_endpoint.hostname.lower().startswith("replace")
        and splunk_endpoint.hostname in allowed_domains
        and splunk_endpoint.port in (None, 443)
        and (
            splunk_endpoint.path.rstrip("/")
            == "/en-US/splunkd/__raw/services/mcp"
        )
        and not splunk_endpoint.username
        and not splunk_endpoint.password
        and not splunk_endpoint.query
        and not splunk_endpoint.fragment
    )
except (AttributeError, OSError, ValueError, yaml.YAMLError):
    splunk_endpoint_valid = False

if not splunk_endpoint_valid:
    print(
        "SPLUNK_MCP_EP must use an allowed hostname, HTTPS port 443, "
        "and path /en-US/splunkd/__raw/services/mcp."
    )
    raise SystemExit(2)

bedrock_region = str(values["BEDROCK_AWS_DEFAULT_REGION"])
bedrock_models = {
    item.strip()
    for item in str(values["BEDROCK_AWS_MODELS"]).split(",")
    if item.strip()
}
bedrock_profile = str(values["BEDROCK_INFERENCE_PROFILE_CLAUDE_SONNET"])
profile_match = re.fullmatch(
    r"arn:(?:aws|aws-us-gov|aws-cn):bedrock:"
    r"([a-z0-9-]+):[0-9]{12}:inference-profile/(.+)",
    bedrock_profile,
)
if not (
    profile_match
    and profile_match.group(1) == bedrock_region
    and (
        bedrock_profile in bedrock_models
        or profile_match.group(2) in bedrock_models
    )
):
    print(
        "BEDROCK_INFERENCE_PROFILE_CLAUDE_SONNET must be a system "
        "inference-profile ARN whose region matches "
        "BEDROCK_AWS_DEFAULT_REGION. BEDROCK_AWS_MODELS must contain "
        "that ARN or its profile ID."
    )
    raise SystemExit(2)

print("Required lab.env values are configured.")
