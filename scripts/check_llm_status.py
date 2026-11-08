#!/usr/bin/env python3
"""Report configured LLM availability without generating model responses."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import dotenv_values

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import (
        BotoCoreError,
        ClientError,
        NoCredentialsError,
        PartialCredentialsError,
    )
except ImportError:
    boto3 = None


def is_configured(value: str | None) -> bool:
    """Return whether an environment value is nonempty and not a placeholder."""
    return bool(value) and "replace" not in value.lower()


def load_config() -> dict[str, Any]:
    """Load the non-secret LibreChat model configuration."""
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / "ai-agent-librechat-oss" / "librechat.yaml"
    return yaml.safe_load(path.read_text())


def bedrock_status(values: dict[str, str | None], config: dict[str, Any]) -> str:
    """Check that AWS can resolve the configured Bedrock inference profile."""
    label = "Claude Sonnet 4.6 (Bedrock)"
    if boto3 is None:
        return f"{label}: NOT CHECKED (boto3 is not installed)"

    region = values.get("BEDROCK_AWS_DEFAULT_REGION")
    profile = values.get("BEDROCK_INFERENCE_PROFILE_CLAUDE_SONNET")
    if not is_configured(region) or not is_configured(profile):
        return f"{label}: NOT CONFIGURED"

    bedrock_models = config.get("endpoints", {}).get("bedrock", {}).get("models", [])
    configured_models = [
        item.strip()
        for item in (values.get("BEDROCK_AWS_MODELS") or "").split(",")
        if item.strip()
    ]
    configured_model_ids = {
        model.rsplit("/", 1)[-1]
        for model in configured_models
    }
    if not bedrock_models or not all(
        model in configured_model_ids for model in bedrock_models
    ):
        return f"{label}: MISCONFIGURED (model list mismatch)"
    profile_id = str(profile).rsplit("/", 1)[-1]
    if profile_id not in bedrock_models:
        return f"{label}: MISCONFIGURED (profile and model mismatch)"
    if profile not in configured_models and profile_id not in configured_models:
        return f"{label}: MISCONFIGURED (profile not selected)"

    access_key = values.get("BEDROCK_AWS_ACCESS_KEY_ID")
    secret_key = values.get("BEDROCK_AWS_SECRET_ACCESS_KEY")
    session_token = values.get("BEDROCK_AWS_SESSION_TOKEN")
    if bool(access_key) != bool(secret_key):
        return f"{label}: MISCONFIGURED (incomplete credential pair)"
    if access_key and access_key.startswith("ASIA") and not session_token:
        return f"{label}: MISCONFIGURED (temporary credential token missing)"

    client_options: dict[str, Any] = {
        "region_name": region,
        "config": Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    }
    if access_key and secret_key:
        client_options.update(
            {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
            }
        )
        if session_token:
            client_options["aws_session_token"] = session_token

    try:
        client = boto3.client("bedrock", **client_options)
        response = client.get_inference_profile(
            inferenceProfileIdentifier=profile,
        )
    except (NoCredentialsError, PartialCredentialsError):
        return f"{label}: NOT CONFIGURED (AWS credentials unavailable)"
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "AWS error")
        if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedException"):
            return f"{label}: REACHABLE (profile lookup not authorized)"
        if code in ("ResourceNotFoundException", "NotFoundException"):
            return f"{label}: MISCONFIGURED (profile not found)"
        if code in ("ValidationException", "InvalidParameterException"):
            return f"{label}: MISCONFIGURED (invalid profile or region)"
        return f"{label}: REACHABLE ({code})"
    except BotoCoreError:
        return f"{label}: UNAVAILABLE (AWS transport failure)"

    status = str(response.get("status", "")).upper()
    if status and status != "ACTIVE":
        return f"{label}: UNAVAILABLE (profile status {status})"
    return f"{label}: PROFILE AVAILABLE"


def litellm_statuses(
    values: dict[str, str | None],
    config: dict[str, Any],
) -> list[str]:
    """Check LiteLLM authentication and advertised model aliases."""
    specs = [
        spec
        for spec in config.get("modelSpecs", {}).get("list", [])
        if spec.get("preset", {}).get("endpoint") == "LiteLLM"
    ]
    fallback = [
        f"{spec['label']}: NOT CONFIGURED"
        for spec in specs
    ]

    key = values.get("LITELLM_API_KEY")
    endpoints = [
        endpoint
        for endpoint in config.get("endpoints", {}).get("custom", [])
        if endpoint.get("name") == "LiteLLM"
    ]
    if not is_configured(key) or len(endpoints) != 1:
        return fallback

    base_url = str(endpoints[0].get("baseURL", "")).rstrip("/")
    if not base_url.startswith("https://"):
        return [
            f"{spec['label']}: MISCONFIGURED (invalid LiteLLM URL)"
            for spec in specs
        ]

    try:
        response = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0,
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        return [f"{spec['label']}: UNAVAILABLE (timeout)" for spec in specs]
    except httpx.ConnectError:
        return [
            f"{spec['label']}: UNAVAILABLE (connection or TLS failure)"
            for spec in specs
        ]
    except httpx.HTTPError:
        return [
            f"{spec['label']}: UNAVAILABLE (HTTP transport failure)"
            for spec in specs
        ]

    if response.status_code in (401, 403):
        return [
            f"{spec['label']}: REACHABLE "
            f"(authentication failed: HTTP {response.status_code})"
            for spec in specs
        ]
    if response.status_code != 200:
        return [
            f"{spec['label']}: REACHABLE "
            f"(unexpected HTTP {response.status_code})"
            for spec in specs
        ]

    try:
        payload = response.json()
        model_ids = {
            str(item["id"])
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        }
    except (ValueError, AttributeError):
        return [
            f"{spec['label']}: REACHABLE (invalid model-list response)"
            for spec in specs
        ]

    results = []
    for spec in specs:
        model_id = str(spec.get("preset", {}).get("model", ""))
        if model_id in model_ids:
            results.append(f"{spec['label']}: MODEL ADVERTISED")
        else:
            results.append(f"{spec['label']}: UNAVAILABLE (model not advertised)")
    return results


def main() -> None:
    env_path = Path(os.environ.get("LAB_ENV", Path.home() / "lab.env"))
    values = dict(dotenv_values(env_path)) if env_path.is_file() else {}
    config = load_config()

    print(bedrock_status(values, config))
    for result in litellm_statuses(values, config):
        print(result)


if __name__ == "__main__":
    main()
