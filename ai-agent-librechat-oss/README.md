# Network AI Hub - LibreChat Suite

> Note: This project was co-authored with Cursor/Codex 5.3.

LibreChat-based web app suite for browser chat with:

- AWS Bedrock model routing
- Multiple MCP servers (streamable HTTP)
- Local non-Docker startup
- Environment-driven configuration

## MCP AI Agent Lab Integration

This source is bundled into the parent teaching lab. It uses:

- The shared `$HOME/lab.env` file; do not create `environment.env` here.
- Catalyst Center MCP at `https://localhost:8000/mcp`.
- Meraki Magic MCP at `https://localhost:8002/mcp`.
- The shared MCP certificate and `MCP_API_KEY`.

## Architecture

- Browser -> LibreChat Web UI (`api` service)
- LibreChat -> AWS Bedrock
- LibreChat -> MCP servers (remote streamable HTTP)

## Prerequisites

- Node.js `24.22.1`
- npm `11.13.0`
- Git
- Local MongoDB (or Atlas connection via `MONGO_URI`)
- AWS credentials available through `$HOME/lab.env`, `~/.aws/credentials`, or
  an assigned IAM role
- nginx and OpenSSL
- MCP server endpoints reachable from this host

## Quick Start

1. From the parent lab root, start the MCP servers:

```bash
make mcp-up
cd ai-agent-librechat-oss
```

2. Lab preparation, already completed on student VMs: generate LibreChat
   secrets in `$HOME/lab.env`:

```bash
bash scripts/gen_secrets.sh
```

3. Lab preparation, already completed on student VMs: configure these values
   in `$HOME/lab.env`:

- `BEDROCK_AWS_DEFAULT_REGION`
- Bedrock credentials or rely on host credential chain
- `BEDROCK_AWS_MODELS` (the selected profile ARN or profile ID)
- `BEDROCK_INFERENCE_PROFILE_CLAUDE_SONNET` (the global system profile ARN)
- `LITELLM_API_KEY` (keep this only in `$HOME/lab.env`)
- `MCP_API_KEY` (used for `X-API-Key` header on remote MCP servers)
- `SPLUNK_MCP_BEARER` (used for the remote Splunk MCP server)
- `SPLUNK_MCP_EP` (the remote Splunk MCP endpoint)
- `THOUSANDEYES_API_KEY` (used as a bearer credential for ThousandEyes MCP)

The bundled `librechat.yaml` already targets the two local lab MCP servers,
the remote Splunk and ThousandEyes MCP servers, and the public draw.io MCP
server. To change the welcome message, edit `interface.customWelcome` in that
file.

ThousandEyes advertises write-capable tools as well as read tools. Use a
least-privilege lab credential and review proposed tool calls before approval.
The public draw.io MCP server does not use a lab credential; send only
non-sensitive diagram content to it.

It also exposes three model choices: Claude Sonnet 4.6 through the configured
AWS Bedrock global inference profile, SharonAI Gemma (LiteLLM)
(`sharon-gemma`), and Claude Haiku (`bedrock-claude`) through LiteLLM.

The current Splunk endpoint is reached through pinned `mcp-remote@0.15.2` over
its HTTPS port `443` reverse-proxy route. The endpoint presents a
publicly trusted certificate, so normal TLS certificate verification remains
enabled.

4. Setup local LibreChat source + dependencies:

```bash
bash scripts/setup_local.sh
```

The setup pins the tested LibreChat revision and applies the lab's compact MCP
selector. Selected MCP servers appear behind one dropdown instead of separate
composer chips.

5. Keep `ALLOW_REGISTRATION=true`, start LibreChat, and select **Sign up**.
Students and proctors create accounts only through the UI. A proctor can
register an account after resetting the lab environment when needed.

6. From the parent lab root, start the complete lab stack:

```bash
cd ..
make up
make status
```

7. Open `https://localhost:3080` on the Sandbox, or
   `https://<sandbox-host>:3080` from the Lab Computer.

## Make Workflow (Recommended)

From the parent lab repository:

```bash
make up          # Start both default MCP servers and LibreChat
make down        # Stop both default MCP servers and LibreChat
make status      # Check the stack, remote MCPs, and LLM configuration
make app-up      # Start only LibreChat
make app-down    # Stop only LibreChat
make app-status  # Check only LibreChat
```

MongoDB remains managed by the host service and is not stopped by `make down`.
The Makefile starts LibreChat in the background and waits for its HTTPS
endpoint before returning.

### HTTPS local mode (self-signed cert)

No org cert is required. This starts LibreChat on an internal port and exposes TLS via nginx.

```bash
bash scripts/start_suite_ssl.sh
```

Defaults:
- HTTPS frontend: all interfaces on port `3080`
- backend internal: `127.0.0.1:3081`

Override ports if needed:

```bash
BACKEND_PORT=3181 HTTPS_PROXY_PORT=3443 bash scripts/start_suite_ssl.sh
```

## App-Only Direct Commands

These scripts manage LibreChat only. Prefer the root Makefile when running the
complete lab.

### Stop

```bash
bash scripts/stop_suite.sh
```

### Restart

```bash
bash scripts/restart_all.sh
```

## Key Files

- `environment.env.example` - reference for values stored in `$HOME/lab.env`
- `librechat.yaml` - endpoint + MCP config
- `scripts/setup_local.sh` - clone/install/build LibreChat locally
- `scripts/sync_config.sh` - sync env/yaml into local LibreChat source
- `scripts/start_all.sh` - checks/starts local MongoDB and starts the app stack
- `scripts/restart_all.sh` - stop then start all services
- `scripts/stop_suite.sh` - one-command shutdown
- `scripts/gen_secrets.sh` - generate JWT/credential keys
- `overrides/` and `patches/` - reproducible compact MCP selector customization

## Logging

- Default consolidated log file: `logs/ai_agent_librechat.log`
- Launcher + backend + nginx entries are written to one app-specific file.
- Startup log filtering keeps config JSON blocks compact:
  - `Mongo Connection options [omitted JSON]`
  - `Custom config file loaded [omitted JSON]`

## Sanity Check

```bash
cd ..
make up
make status
curl --cacert certs/mcp-selfsigned.crt -i https://localhost:3080/
```

Expected:
- HTTPS frontend responds on `3080`
- Five MCP servers are initialized in LibreChat startup logs when the
  configured remotes are reachable

## Notes on Reused Concepts

This suite keeps the same concepts from your previous app:

- Browser-first chat UI
- Bedrock-based assistant
- MCP tool execution
- Multiple MCP server support
- Env-first deployment

The UI and orchestration are now handled by LibreChat itself.
