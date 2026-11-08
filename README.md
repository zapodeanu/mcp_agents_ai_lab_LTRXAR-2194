# MCP AI Agent Lab

Developed by Gabi Zapodeanu, PTME + Cursor/GPT-5.6 Sol

This hands-on lab introduces AI agents to Cisco network platforms through the
Model Context Protocol (MCP). The default lab pair is Cisco Catalyst Center
MCP and Meraki Magic MCP. The first module installs and validates these
services; the second module connects them to a LibreChat AI agent using AWS
Bedrock and a cloud LiteLLM endpoint.

> Lab use only: the referenced MCP server project is a proof of concept and is
> not intended for production deployment.

## Students: Start Here

Before cloning the repository, open the
[Student Start page](docs/student-start.md). It covers the instructor-provided
access information, SSH connection, Ubuntu validation, protected
configuration check, public clone, and first progress check.

## What You Will Learn

- Prepare an Ubuntu host for Python-based MCP services.
- Run Catalyst Center and Meraki Magic MCP servers over streamable HTTP.
- Keep lab credentials outside source repositories.
- Validate service health, authentication, and TLS configuration.
- Install and run LibreChat with AWS Bedrock and OpenAI-compatible LiteLLM
  models.
- Connect a LibreChat agent to Catalyst Center, Meraki Magic, Splunk,
  ThousandEyes, and draw.io MCP servers and inspect their tools.

## Architecture

```text
Lab Computer browser
      | HTTPS :3080
      v
LibreChat AI agent :3080
      |
      | MCP streamable HTTPS
      v
+-------------------------------------+
| Catalyst Center MCP :8000           |----> Cisco Catalyst Center
| Meraki Magic MCP    :8002           |----> Cisco Meraki Dashboard
| Remote Splunk MCP (Bearer token)    |----> Splunk
| Remote ThousandEyes MCP (Bearer)    |----> ThousandEyes
| Public draw.io MCP                  |----> draw.io
+-------------------------------------+
```

## Quick Start

The lab uses `$HOME/lab.env` as its environment source of truth on both macOS
and Ubuntu. At startup, the launcher creates a mode-`600`, Git-ignored runtime
copy containing only LibreChat-required values at
`ai-agent-librechat-oss/librechat-src/.env`. Catalyst and Meraki credentials
are excluded. Do not place real credentials in tracked repository files.

```bash
sudo apt update
sudo apt install -y git

cd "$HOME"
git clone https://github.com/zapodeanu/mcp_agents_ai_lab_LTRXAR-2194.git mcp-ai-agent-lab
cd mcp-ai-agent-lab

test -s "$HOME/lab.env" && echo "lab.env: present" || {
  echo "STOP: ask the instructor to restore lab.env"
  exit 1
}
./docs/setup-full-lab.sh
make up
make status
```

Continue with the [complete lab guide](docs/lab-guide.md).

The student workflow is validated for Ubuntu 24.04. With a complete
preconfigured `$HOME/lab.env`, the bootstrap installs both modules from the
tested dependency lock. If required values are missing or still placeholders,
it installs the shared prerequisites and then pauses before LibreChat
installation. The instructor preconfigures this file; students must not open,
print, copy, source, or modify it.

## Runtime Versions

- Bundled MCP servers: Python `3.13.x` for a consistent student environment
- LibreChat npm installation: Node.js `24.22.1` and npm `11.13.0`

LibreChat core uses Node.js rather than the lab's Python runtime. The shared
Python environment still provides setup helpers, local MCP servers, and status
checks.

## Bundled MCP Servers

Module 1 includes `platforms-mcp-servers-oss/`, based on:

- [platforms-mcp-servers-oss](https://github.com/zapodeanu/platforms-mcp-servers-oss) —
  FastMCP servers for Catalyst Center and Meraki

The bundled copy is configured to load `$HOME/lab.env` automatically. Its
original Meraki MCP remains available on port `8001` as an optional comparison
and is not started by the default workflow.

Module 1 also includes `meraki-magic-mcp-community/`, based on:

- [meraki-magic-mcp-community](https://github.com/CiscoDevNet/meraki-magic-mcp-community) —
  dynamic discovery and execution across the Meraki Python SDK

The `make mcp-up` command starts Catalyst Center on port `8000` and Meraki
Magic on port `8002`. Both use the same HTTPS certificate and require the same
`X-API-Key` value from `MCP_API_KEY`.

## Bundled LibreChat Agent

Module 2 includes `ai-agent-librechat-oss/`, a local LibreChat launcher
configured for AWS Bedrock, cloud LiteLLM models, the two local MCP servers,
the remote Splunk and ThousandEyes MCP servers, and the public draw.io MCP
server. It uses the same `$HOME/lab.env` file and shared lab certificate.
LibreChat source and Node dependencies are downloaded during the module setup
rather than committed to this repository.

After both modules are installed, use the root Makefile for the complete lab:

```bash
make up       # Start Catalyst Center, Meraki Magic, and LibreChat
make status   # Check local health, remote MCPs, and LLM configuration
make down     # Stop LibreChat and both default MCP servers
```

MongoDB is a host-managed dependency and is not stopped by `make down`.

## Lab Build Progress Check

Students and proctors can determine how far a Sandbox has progressed without
displaying credentials or platform data:

```bash
cd "$HOME/mcp-ai-agent-lab"
python3 scripts/check_lab_progress.py
```

The checker reports eight sequential milestones covering the repository,
Ubuntu prerequisites, locked Python environment, protected configuration,
host services, LibreChat installation, local runtime, and MCP initialization.
It identifies the first incomplete checkpoint and the next action, and waits
up to 45 seconds for normal MCP initialization after the runtime becomes
healthy.

After all local checkpoints pass, include remote MCP and model-provider status:

```bash
python3 scripts/check_lab_progress.py --live
```

When the stack is intentionally stopped with `make down`, checkpoints 1–6
should pass while local runtime and current MCP initialization report
`NOT READY`. See [the proctor guide](docs/proctor-guide.md) for detailed
preflight, troubleshooting, dependency-lock, certificate, and MongoDB-reset
procedures.

## Validation Status

The complete workflow has been validated on an Ubuntu 24.04 Sandbox:

- `make up`, `make status`, and `make down`
- Three selectable LLMs: Bedrock Claude Sonnet, SharonAI Gemma, and Claude
  Haiku
- Five MCP integrations: Catalyst Center, Meraki Magic, Splunk, ThousandEyes,
  and draw.io
- Read-oriented queries spanning those four network and observability platforms

All five MCP connections, all three model choices, bounded single-platform
exercises, and the multi-platform workflow passed acceptance testing. Tool
counts can vary when upstream catalogs change.

Splunk uses its HTTPS port `443` reverse-proxy route at
`/en-US/splunkd/__raw/services/mcp`. The two LiteLLM models depend on the
external LiteLLM service being available. Follow the
[infrastructure test chapter](docs/lab-guide.md#chapter-5-test-the-infrastructure)
before distributing the student VM.

## Files

- `README.md` — overview and quick start
- `Makefile` — unified start, stop, status, and optional-server commands
- `requirements.txt` — human-maintained Python dependency sources
- `requirements.lock` — exact direct and transitive Python package versions
  tested for student installation
- `docs/student-start.md` — pre-clone student access and bootstrap instructions
- `docs/lab-guide.md` — student instructions and validation
- `docs/proctor-guide.md` — fleet preparation, lock maintenance, preflight,
  and troubleshooting
- `docs/setup-full-lab.sh` — Ubuntu full bootstrap
- `scripts/check_lab_progress.py` — credential-safe local build progress and
  optional live-status checker for students and proctors
- `scripts/check_remote_mcp.py` — credential-safe remote MCP status probes
- `scripts/check_llm_status.py` — non-generative Bedrock and LiteLLM checks
- `.env.example` — safe environment-variable template
- `.gitignore` — prevents local credentials, keys, and certificates from being committed
- `SECURITY.md` — private vulnerability-reporting and credential-handling policy
- `platforms-mcp-servers-oss/` — bundled Catalyst Center and Meraki MCP source
- `meraki-magic-mcp-community/` — bundled Meraki Magic MCP source
- `ai-agent-librechat-oss/` — bundled LibreChat agent launcher and configuration

## Security

- Use only instructor-provided lab accounts and API keys.
- Never commit `$HOME/lab.env`, certificates, or private keys.
- Use a unique `MCP_API_KEY`; do not reuse a platform password or API key.
- Self-signed certificates are acceptable only for this isolated lab.
- LibreChat and the MCP frontends listen on all Sandbox interfaces; restrict
  inbound TCP `3080`, `8000`, and `8002` to the lab network. The LibreChat
  backend on `3081` remains loopback-only.
- Meraki Magic defaults to `READ_ONLY_MODE=true`.

## Current Scope

Module 1 covers MCP server setup and validation. Module 2 covers LibreChat,
AWS Bedrock, LiteLLM, and connecting the agent to the configured MCP servers.
