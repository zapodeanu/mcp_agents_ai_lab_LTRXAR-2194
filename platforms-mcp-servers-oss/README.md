# Platforms MCP Servers (OSS)

> Note: This project was co-authored with Cursor/Codex 5.3.
> Version note: This OSS repository is the current MCP server version and replaces the older `network_platforms_mcp_servers` repo. Legacy `declarative-*` server entrypoints are deprecated.

This project is published for open-source use as is. It is not intended to be used in production.

## MCP AI Agent Lab Integration

This copy is bundled with the parent MCP AI Agent Lab. In the lab:

- Use the parent [lab guide](../docs/lab-guide.md) for the student workflow.
- Store runtime settings in `$HOME/lab.env`; do not create a credential file
  inside this directory.
- The parent repository's `Makefile` starts Catalyst Center from this directory
  and Meraki Magic from `../meraki-magic-mcp-community`.
- The Meraki implementation in this directory remains available through the
  `optional-meraki-*` Make targets for comparison and is not started by default.
- All active servers load `$HOME/lab.env` automatically.

## Server Architecture

Current OSS server suite (grouped by platform):

**Meraki**
- `meraki_core.py` - FastMCP core app and tool registration for Meraki
- `meraki_stdio.py` - stdio transport wrapper for Meraki
- `meraki_remote.py` - streamable HTTP transport wrapper for Meraki
- `Resources/meraki_tools.yaml` - Meraki declarative tool definitions
- `Resources/meraki_organizations.yaml` - Meraki organization mapping

**Catalyst Center**
- `catalyst_center_core.py` - FastMCP core app and tool registration for Catalyst Center
- `catalyst_center_stdio.py` - stdio transport wrapper for Catalyst Center
- `catalyst_center_remote.py` - streamable HTTP transport wrapper for Catalyst Center
- `Resources/catalyst_center_tools.yaml` - Catalyst Center declarative tool definitions
- `Resources/catalyst_center_clusters.yaml` - Catalyst Center cluster mapping
- `Resources/catalyst_config_ai_flows.yaml` - Catalyst Center AI flow definitions

**Shared**
- `download_embeddings_model.py` - local embedding model/bootstrap helper
- `../.env.example` - lab environment template copied to `$HOME/lab.env`
- `../Makefile` - parent lab commands for remote server startup/health checks

**Training**
- `training_mcp_servers/` - optional training/demo server variants for learning and experimentation

Architecture model (grouped by platform):

**Meraki architecture**
- `meraki_core.py` builds the Meraki FastMCP app and registers tools.
- `meraki_stdio.py` runs Meraki with `transport="stdio"`.
- `meraki_remote.py` runs Meraki with `transport="streamable-http"` on `/mcp` (default port `8001`).

**Catalyst Center architecture**
- `catalyst_center_core.py` builds the Catalyst Center FastMCP app and registers tools.
- `catalyst_center_stdio.py` runs Catalyst Center with `transport="stdio"`.
- `catalyst_center_remote.py` runs Catalyst Center with `transport="streamable-http"` on `/mcp` (default port `8000`).

**Shared transport behavior**
- Run transport wrappers (`*_stdio.py` or `*_remote.py`) rather than executing `*_core.py` directly.
- Remote wrappers bind to `MCP_HOST` (default `0.0.0.0`); use a real server IP/FQDN in clients (`0.0.0.0` is bind-only).
- Remote wrappers support optional TLS via `--ssl-certfile` and `--ssl-keyfile` (or `MCP_SSL_CERTFILE` / `MCP_SSL_KEYFILE`).
- Remote wrappers require API key auth on `/mcp` using `MCP_API_KEY` and client header `X-API-Key`.

## Streamable HTTP + SSE Client Checklist

Use this checklist when integrating remote MCP clients:

1. **Use streamable HTTP endpoint**
   - **Catalyst Center**: `https://<host>:8000/mcp` (or `http://<host>:8000/mcp` for local non-TLS testing).
   - **Meraki Magic**: `https://<host>:8002/mcp` (or `http://<host>:8002/mcp` for local non-TLS testing).
   - **Optional bundled Meraki**: port `8001`, started from this directory with
     `make -C .. optional-meraki-up`.

2. **Include API key header**
   - Remote wrappers require `MCP_API_KEY` on startup, and clients must include:
   - `X-API-Key: <key>`

3. **Initialize first**
   - Send `POST /mcp` with JSON-RPC `initialize` before any other MCP calls.

4. **Accept header must include both content types**
   - `Accept: application/json, text/event-stream`
   - Sending only `text/event-stream` can return `406 Not Acceptable`.

5. **Persist and reuse session ID**
   - Read `mcp-session-id` from initialize response headers.
   - Send `mcp-session-id` on all subsequent calls.
   - Missing this header can return `Bad Request: Missing session ID`.

6. **Keep transport assumptions correct**
   - Streamable HTTP may return JSON or SSE frames depending on request flow.
   - SSE is part of streamable HTTP behavior, not a separate transport mode.

7. **TLS/self-signed handling**
   - For self-signed certs in POC, either:
     - trust the cert/CA in the client, or
     - disable verification temporarily in the MCP client for testing only (for example Node-based clients may use `NODE_TLS_REJECT_UNAUTHORIZED=0`).
   - This repository does not implement a server-side `MCP_VERIFY_TLS` variable.

## API Explorer Scope (OSS)

- API Explorer execution is restricted to **GET-only** operations in this OSS repository.
- Non-GET explorer requests (POST/PUT/DELETE/PATCH) are intentionally blocked.
- Use the private/internal repository variant if you require full CRUD explorer behavior.

### API Explorer Tools and Intent

Use these explorer tools as a workflow: discover -> inspect -> execute -> review analytics.

**Meraki Explorer Tools**
- `explore_meraki_api_endpoints`: Natural-language search over Meraki OpenAPI endpoints to find candidate APIs by intent.
- `get_meraki_endpoint_info`: Inspect one Meraki endpoint's expected parameters/usage before execution.
- `execute_meraki_api_endpoint`: Execute a selected Meraki endpoint dynamically (GET-only in OSS), optionally scoped by organization.
- `get_meraki_explorer_analytics`: Review Meraki explorer usage patterns and success/failure rates.

**Catalyst Center Explorer Tools**
- `explore_catalyst_api_endpoints`: Natural-language search over Catalyst Center OpenAPI endpoints to find candidate APIs by intent.
- `get_catalyst_endpoint_info`: Inspect one Catalyst endpoint's expected parameters/usage before execution.
- `execute_catalyst_api_endpoint`: Execute a selected Catalyst endpoint dynamically (GET-only in OSS), optionally scoped by cluster.
- `get_catalyst_explorer_analytics`: Review Catalyst explorer usage patterns and success/failure rates.

Analytics intent:
- Use explorer analytics to identify frequently explored endpoints for promotion into curated YAML tools (`*_tools.yaml`).
- Use explorer analytics to identify tool usage patterns (high-frequency paths, repeated failures, parameter friction) and optimize tool definitions, defaults, and documentation.

### When MCP Server Certificates Are Required

- `*_stdio.py` servers do not expose HTTPS listeners, so local server certs are not required.
- `*_remote.py` servers running without TLS (`http://`) do not require local certs (development/testing only).
- `*_remote.py` servers running with TLS (`https://`) require local cert/key files on the MCP server host (`--ssl-certfile` and `--ssl-keyfile`, or `MCP_SSL_CERTFILE` and `MCP_SSL_KEYFILE`).
- If those certs are self-signed, clients must trust the cert/CA or use a temporary client-side verification bypass only for testing.

## Prerequisites

- macOS or Linux shell environment
- Python `3.13.x` for this lab (the upstream project supports `3.10+`)
- `uv` for Python installation and virtual-environment management
- `make`
- `openssl` (for self-signed cert generation in local TLS mode)
- Optional for client testing examples: Node.js + `npx`
- API credentials for Meraki and/or Catalyst Center

## Quick Start

1. **Environment Setup**
   ```bash
   cd ..
   uv venv --python 3.13 --seed .venv
   source .venv/bin/activate
   python -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'
   uv pip install --python .venv/bin/python -r requirements.lock
   cd platforms-mcp-servers-oss
   ```

2. **Configure Credentials**

   For this bundled lab, copy the parent template to `$HOME/lab.env`:

   ```bash
   cp ../.env.example "$HOME/lab.env"
   chmod 600 "$HOME/lab.env"
   ```

   Then update only the values provided by the instructor.

3. **Run Servers (choose one mode)**

   Use one of the following approaches:

   **A) Stdio mode (good for local MCP client testing)**
   ```bash
   # Meraki (run in its own terminal session)
   python meraki_stdio.py

   # Catalyst Center (run in its own terminal session)
   python catalyst_center_stdio.py
   ```

   **B) Remote mode (HTTP/HTTPS endpoints)**
   ```bash
   # Meraki (run in its own terminal session)
   python meraki_remote.py --host 0.0.0.0 --port 8001

   # Catalyst Center (run in its own terminal session)
   python catalyst_center_remote.py --host 0.0.0.0 --port 8000
   ```

   **Optional HTTPS (self-signed cert) for remote mode**
   ```bash
   mkdir -p certs
   openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
     -keyout certs/mcp-selfsigned.key \
     -out certs/mcp-selfsigned.crt \
     -subj "/CN=<host-or-fqdn>"

   # Meraki HTTPS remote
   python meraki_remote.py --host 0.0.0.0 --port 8001 \
     --ssl-certfile certs/mcp-selfsigned.crt --ssl-keyfile certs/mcp-selfsigned.key

   # Catalyst Center HTTPS remote
   python catalyst_center_remote.py --host 0.0.0.0 --port 8000 \
     --ssl-certfile certs/mcp-selfsigned.crt --ssl-keyfile certs/mcp-selfsigned.key
   ```

4. **Alternative: Start MCP Remotes with the Parent Makefile**

   From this component directory, `make -C .. up` starts the default lab pair:
   Catalyst Center on port `8000` and Meraki Magic on port `8002`. Both use the
   same certificate and `MCP_API_KEY` from `$HOME/lab.env`.

   Optional TLS path overrides:
   ```bash
   MCP_ENABLE_TLS=true \
   MCP_SSL_CERTFILE=certs/mcp-selfsigned.crt \
   MCP_SSL_KEYFILE=certs/mcp-selfsigned.key \
   make -C .. up
   ```
   To disable TLS for local HTTP-only testing:
   ```bash
   MCP_ENABLE_TLS=false make -C .. up
   ```
   Auto-generated certificate behavior:
   - The parent `make mcp-up` auto-generates with `CN=localhost` and Subject Alternative Names
     for `localhost` and `127.0.0.1` when certificate files are missing.
   - For access through another hostname or IP, pre-create a certificate with
     matching Subject Alternative Names and pass it through
     `MCP_SSL_CERTFILE` and `MCP_SSL_KEYFILE`.

## Sanity Check (MCP-Only Default)

After `make -C .. up`, verify MCP services (HTTPS default):

```bash
make -C .. status
# Catalyst Center
curl -k -i https://127.0.0.1:8000/health
# Meraki Magic
curl -k -i https://127.0.0.1:8002/health
# Example MCP call (Catalyst Center)
curl -k -i -H "X-API-Key: $MCP_API_KEY" -H "Accept: application/json, text/event-stream" https://127.0.0.1:8000/mcp
```

If you disabled TLS (`MCP_ENABLE_TLS=false`), use HTTP checks:
```bash
MCP_ENABLE_TLS=false make -C .. status
# Catalyst Center
curl -i http://127.0.0.1:8000/health
# Meraki Magic
curl -i http://127.0.0.1:8002/health
```

Expected:
- MCP remotes on `8000`/`8002` return `200` health JSON.

## Configuration

### API docs source

- API Explorer coverage relies on local OpenAPI/Swagger files in `Resources/`.
- Tested OpenAPI snapshots for both bundled platform MCP servers are committed
  so a fresh clone can build either API Explorer.
- The Meraki snapshot contains vendor-supplied PEM certificate strings as API
  payload examples. They are documentation data, not runtime trust material;
  some examples are expired and must never be copied into an operational
  certificate store.
- For updates, download the latest specs from Cisco DevNet and replace:
  - **Catalyst Center**: [https://developer.cisco.com/docs/catalyst-center/3-1-3/overview/](https://developer.cisco.com/docs/catalyst-center/3-1-3/overview/) -> `Resources/catalyst_center_openapi.json`
  - **Meraki**: [https://developer.cisco.com/meraki/api-v1/overview/](https://developer.cisco.com/meraki/api-v1/overview/) -> `Resources/meraki_openapi.json`

### Regenerate explorer embeddings from updated OpenAPI specs

After replacing OpenAPI files, regenerate embeddings with:

```bash
# Optional: refresh local sentence-transformer model cache
python download_embeddings_model.py

# Remove old embedding caches so they are rebuilt for new OpenAPI content
rm -f embeddings_assets/catalyst_embeddings_*.pkl
rm -f embeddings_assets/meraki_embeddings_*.pkl

# Start servers once; explorers auto-rebuild embeddings from Resources/*openapi*.json
make -C .. up
```

### Core Configuration Files

**Meraki**
- `Resources/meraki_tools.yaml` - Meraki API endpoints and parameters
- `Resources/meraki_openapi.json` - Tracked Meraki OpenAPI specification used
  to build the optional Meraki API Explorer

**Catalyst Center**
- `Resources/catalyst_center_tools.yaml` - Catalyst Center API endpoints and parameters
- `Resources/catalyst_center_openapi.json` - Tracked Catalyst Center OpenAPI
  specification used to build the API Explorer
- `Resources/catalyst_config_ai_flows.yaml` - Example AI flow definitions; AI flows can be developed as reusable skills

**Shared**
- `requirements.txt` - component dependency declarations including MCP, API
  clients, and ML libraries
- `../requirements.lock` - exact dependency set used by the parent lab

### Adding New Tools

- Add new API tools in the `_tools` files: `Resources/meraki_tools.yaml` and `Resources/catalyst_center_tools.yaml`.
- Start from the corresponding OpenAPI spec (`Resources/meraki_openapi.json` or `Resources/catalyst_center_openapi.json`) and map the operation into a tool entry.
- Parameter locations should follow OpenAPI definitions:
  - `in: path` -> required path parameters in the endpoint template.
  - `in: query` -> optional/required query string parameters.
  - `in: header` -> explicit headers when required by the endpoint.
  - `requestBody` -> JSON/body payload fields for non-GET operations (not executed by OSS API Explorer).
- Keep parameter names/types aligned with the OpenAPI `parameters` and `requestBody.content.*.schema` definitions so tool validation matches API expectations.

Example (`_tools` YAML entry):

```yaml
- name: list_network_devices
  description: "List devices for a specific network"
  endpoint: "networks/{network_id}/devices"
  method: GET
  parameters:
    organization:
      type: string
      description: "Organization scope for resolution"
      required: true
      location: special
    network_id:
      type: string
      description: "Network identifier from a discovery call"
      required: true
      location: path
    perPage:
      type: integer
      description: "Maximum results per page"
      required: false
      location: query
```

### Multi-Environment Setup

**`Resources/meraki_organizations.yaml`** - Configure multiple Meraki organizations:
```yaml
meraki_organizations:
  - name: "Production"
    api_key_env: "MERAKI_PROD_API_KEY"
    description: "Production environment networks"
    enabled: true
  - name: "Lab"
    api_key_env: "MERAKI_LAB_API_KEY"
    description: "Development and testing networks"
    enabled: true
```

Use `enabled: true` or `enabled: false` as a simple operational switch to include or exclude an organization from active service.

**`Resources/catalyst_center_clusters.yaml`** - Configure multiple Catalyst Center clusters:
```yaml
catalyst_centers:
  - name: "Portland"
    host: "Portland-center.domain.com"
    version: "2.3.7.10"
    location: "Portland"
    enabled: true
  - name: "San Jose"
    host: "SanJose-catalyst.domain.com"
    version: "2.3.7.9" 
    location: "San Jose"
    enabled: false
```

Use `enabled: true` or `enabled: false` as a simple operational switch to include or exclude a cluster from active service.

**Note on Catalyst credentials:** the current FastMCP Catalyst flow requires shared `CC_USER` and `CC_PASS` from environment variables.  
`catalyst_center_clusters.yaml` provides cluster host inventory/selection (including `cluster="all"`); `CC_URL` is no longer required for startup.

If you want fully YAML-driven cluster auth in the future, prefer per-cluster env references (for example `username_env` / `password_env`) and keep secrets in environment or a secret manager rather than hardcoding credentials in YAML.

### Environment Variables

The bundled lab uses the parent `.env.example` and `$HOME/lab.env`:
```bash
# Remote listener defaults (all interfaces for local/server hosting)
# 0.0.0.0 is for server bind/listen only; clients must connect using a real server IP or FQDN.
MCP_HOST=0.0.0.0
MCP_CATALYST_PORT=8000
MCP_MERAKI_PORT=8001  # optional bundled Meraki server

# Optional bundled Meraki server
MERAKI_PROD_API_KEY=your_production_api_key
MERAKI_LAB_API_KEY=your_lab_api_key
# Optional Meraki API base URL (default: https://api.meraki.com/api/v1)
MERAKI_BASE_URL=https://api.meraki.com/api/v1

# Catalyst Center
CC_USER=your_username
CC_PASS=your_password

# Shared transport/security
MCP_SSL_CERTFILE=certs/mcp-selfsigned.crt
MCP_SSL_KEYFILE=certs/mcp-selfsigned.key

# Optional MCP remote API key for /mcp endpoints
MCP_API_KEY=replace_with_a_long_random_key

# Shared logging
MCP_LOG_DIR=logs
MCP_LOG_LEVEL=INFO
MCP_LOG_MODE=a
MCP_LOG_FORMAT=%(asctime)s - PID:%(process)d - %(name)s - %(levelname)s - %(message)s
MERAKI_LOG_FILE=meraki_mcp.log
CATALYST_LOG_FILE=catalyst_center_mcp.log
```

## Dependencies

Key packages from `requirements.txt` (highlights):
- `mcp` - Model Context Protocol server framework
- `httpx` - Modern HTTP client for API calls  
- `sentence-transformers` - AI embeddings for API exploration
- `scikit-learn`, `numpy` - ML libraries for cosine similarity search

## Claude Desktop Configuration

Add to your Claude Desktop `claude_desktop_config.json`:

### Stdio Wrappers

**Meraki (stdio)**

```json
{
  "mcpServers": {
    "meraki_stdio": {
      "command": "/path/to/your/venv/bin/python3",
      "args": ["/path/to/your/meraki_stdio.py"]
    }
  }
}
```

**Catalyst Center (stdio)**

```json
{
  "mcpServers": {
    "catalyst_center_stdio": {
      "command": "/path/to/your/venv/bin/python3",
      "args": ["/path/to/your/catalyst_center_stdio.py"]
    }
  }
}
```

**Note**: Update paths to match your actual Python virtual environment and script locations.

### Remote Wrappers (HTTPS)

These examples use external Node bridge packages (`npx ...-remote`) to connect Claude Desktop to this repo's HTTPS MCP endpoints.
Use `https://` URLs when MCP server TLS is enabled.

**Catalyst Center (remote HTTPS)**

```json
{
  "mcpServers": {
    "catalyst_remote": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://<host-or-fqdn>:8000/mcp"
      ]
    }
  }
}
```

**Meraki (remote HTTPS)**

```json
{
  "mcpServers": {
    "meraki_remote": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://<host-or-fqdn>:8001/mcp"
      ]
    }
  }
}
```

### Temporary TLS Verification Bypass (Testing Only)

Use this only for local/lab testing with self-signed certificates.

**Catalyst Center (testing-only bypass)**

```json
{
  "mcpServers": {
    "catalyst_remote": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://<host-or-fqdn>:8000/mcp"
      ],
      "env": {
        "NODE_TLS_REJECT_UNAUTHORIZED": "0"
      }
    }
  }
}
```

**Meraki (testing-only bypass)**

```json
{
  "mcpServers": {
    "meraki_remote": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://<host-or-fqdn>:8001/mcp"
      ],
      "env": {
        "NODE_TLS_REJECT_UNAUTHORIZED": "0"
      }
    }
  }
}
```

**Warning**: `NODE_TLS_REJECT_UNAUTHORIZED=0` disables certificate verification and is insecure. Do not use it in production.
**Recommended**: use certificates signed by a trusted CA (or install your internal CA) and keep TLS verification enabled.

Each server provides YAML-defined tools plus OpenAPI-based API exploration for complete network automation capabilities.
