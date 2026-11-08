# Scripts

This folder contains local helper scripts for starting and managing the stack.

## `start_network_ai_stack.sh`

Starts MCP remote servers in sequence:

1. `catalyst_center_remote.py` (port `8000`)
2. `../meraki-magic-mcp-community/meraki_magic_remote.py` (port `8002`)

Both use the same HTTPS certificate and `MCP_API_KEY`. The bundled
`meraki_remote.py` server on port `8001` is optional and is not started by the
default workflow.

### Prerequisites

- Python virtual environment exists at:
  - `<lab-root>/.venv`
- By default, this script resolves:
  - `PLATFORMS_DIR`: parent of this script (`<lab-root>/platforms-mcp-servers-oss`)
  - `MERAKI_MAGIC_DIR`: `<lab-root>/meraki-magic-mcp-community`
- `MCP_API_KEY` is required for remote MCP startup and is enforced as `X-API-Key` on `/mcp`.

### Usage

From the `platforms-mcp-servers-oss` folder:

```bash
./scripts/start_network_ai_stack.sh
```

Or use the unified Makefile from the repository root:

```bash
cd ..
make mcp-up
```

From `platforms-mcp-servers-oss`, the equivalent command is:

```bash
make -C .. mcp-up
```

Optional Python override:

```bash
PYTHON_BIN=/opt/mcp-ai-agent-lab/.venv/bin/python ./scripts/start_network_ai_stack.sh
```

### Notes

- The script is intended for local development on this machine.
- It uses `nohup` and runs services in the background.
- It performs a best-effort pre-start cleanup for existing MCP remote processes.
- MCP remote service logs are written under the lab root `logs/` directory.
- See the lab root `../../Makefile` for `make mcp-up`, `make mcp-down`, and
  `make mcp-status`.

### Quick Verify

From the repository root, after `make mcp-up`:

```bash
make mcp-status
curl --cacert certs/mcp-selfsigned.crt -i https://localhost:8000/health
curl --cacert certs/mcp-selfsigned.crt -i https://localhost:8002/health
curl --cacert certs/mcp-selfsigned.crt -i -H "X-API-Key: $MCP_API_KEY" -H "Accept: application/json, text/event-stream" https://localhost:8000/mcp
```

For HTTP-only local testing:

```bash
MCP_ENABLE_TLS=false make mcp-up
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8002/health
```
