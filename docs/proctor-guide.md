# MCP AI Agent Lab Proctor Guide

Developed by Gabi Zapodeanu, PTME + Cursor/GPT-5.6 Sol

This guide contains instructor and proctor preparation that students do not
perform. The student workflow remains in [lab-guide.md](lab-guide.md).

## 1. Prepare the Sandbox configuration

### What this does

Places the prepared runtime configuration on each Sandbox and restricts access
to the Sandbox user. Students receive a Sandbox where this step is already
complete.

### Why it is needed

The lab integrates multiple protected services. Their credentials and
application secrets must be provisioned separately from the public repository
and must never be committed to source control.

Copy the prepared file from the secure proctor workstation when the Sandbox
image does not already contain it:

```bash
scp ~/lab.env ubuntu@<sandbox-host>:/home/ubuntu/lab.env
```

On the Sandbox:

```bash
chmod 600 "$HOME/lab.env"
test -s "$HOME/lab.env"
stat -c 'Permissions: %a  File: %n' "$HOME/lab.env"
```

Expected:

```text
Permissions: 600  File: /home/ubuntu/lab.env
```

Do not print, source, or commit this file. Rotate any credential that is
displayed in a terminal transcript, chat, screenshot, or support record.

## 2. Validate the prepared configuration

After the repository and Python environment are installed:

```bash
cd "$HOME/mcp-ai-agent-lab"
source .venv/bin/activate
make check-env
```

Expected:

```text
Required lab.env values are configured.
```

This validates required values and cross-setting consistency without printing
credentials. Live service authentication is tested later during the complete
preflight.

## 3. Refresh and verify the dependency lock

Students install the exact tested package set from the repository-root
`requirements.lock`. The human-maintained dependency sources remain
`requirements.txt` and the component requirement files it includes.

Refresh the lock only after the complete lab passes on the golden Sandbox.
Capture that working environment as temporary resolver constraints:

```bash
cd "$HOME/mcp-ai-agent-lab"
source .venv/bin/activate

python3 -m pip check
python3 -m pip freeze --exclude-editable \
  > /tmp/lab-tested-constraints.txt

uv pip compile \
  --universal \
  --python-version 3.13 \
  --generate-hashes \
  --constraints /tmp/lab-tested-constraints.txt \
  --custom-compile-command \
    "uv pip compile --universal --python-version 3.13 --generate-hashes requirements.txt -o requirements.lock" \
  requirements.txt \
  -o requirements.lock

rm -f /tmp/lab-tested-constraints.txt
printf '\n'
```

Review the lock-file diff. Then install it into a clean environment and test
the dependencies used by the lab:

```bash
rm -rf .venv-lock-test
uv venv --python 3.13 --seed .venv-lock-test

uv pip install \
  --python .venv-lock-test/bin/python \
  -r requirements.lock

.venv-lock-test/bin/python -m pip check

.venv-lock-test/bin/python - <<'PY'
import boto3
import fastapi
import httpx
import meraki
import torch
import uvicorn
from mcp.server.fastmcp import FastMCP

print("Locked dependency imports: OK")
print(f"Torch: {torch.__version__}")
print()
PY
```

Do not commit an updated lock until this clean-environment test and the
complete lab acceptance workflow both pass.

## 4. Golden-Sandbox workflow

Prepare and fully test one golden Sandbox before creating the student fleet:

1. Complete every student lab chapter on a clean Ubuntu 24.04 Sandbox.
2. Run the complete infrastructure and model checks.
3. Execute at least one real data tool against Catalyst Center, Meraki,
   Splunk, and ThousandEyes.
4. Confirm all five MCP servers publish their expected tool catalogs in
   LibreChat.
5. Remove nonessential shell history and temporary diagnostic files.
6. Snapshot the validated Sandbox.
7. Create the student Sandboxes from that snapshot.
8. Run the final preflight on every clone before class.

Do not commit `lab.env` or embed credentials in repository files, image
metadata, screenshots, or validation output.

## 5. Run the fleet preflight

Run this baseline on every cloned Sandbox before class:

```bash
cd "$HOME/mcp-ai-agent-lab"
source .venv/bin/activate

test -s "$HOME/lab.env"
test "$(stat -c '%a' "$HOME/lab.env")" = "600"
python3 --version
python3 -m pip check
systemctl is-active mongod
make check-env
make up
make status
printf '\n'
```

Confirm:

- Python is `3.13.x`, `pip check` reports no broken requirements, and MongoDB
  is active.
- Local ports `8000`, `8002`, `3080`, and `3081` have listeners.
- Both local health checks return `status: ok`.
- Splunk, ThousandEyes, and draw.io report `AVAILABLE`.
- Bedrock is reachable. `REACHABLE (profile lookup not authorized)` is
  acceptable when only the optional `bedrock:GetInferenceProfile` permission
  is absent.
- Both LiteLLM aliases report `MODEL ADVERTISED`.

In LibreChat, complete one fresh-chat inference with each model and one
read-only tool call through each platform MCP server. For the multi-platform
test, use Claude Sonnet 4.6 (Bedrock), make all five MCP servers available, and
verify that the agent invokes only those relevant to the request. Test each
32K LiteLLM model with only the MCP server or servers required by its prompt.

## 6. Troubleshoot startup and listener failures

First capture the current state without changing it:

```bash
cd "$HOME/mcp-ai-agent-lab"
make status

for port in 8000 8002 3080 3081; do
  lsof -nP -iTCP:"$port" -sTCP:LISTEN || true
done
printf '\n'
```

If a port is owned by an old lab process, use the normal stop targets before
starting again:

```bash
make down
make up
make status
printf '\n'
```

Do not terminate an unfamiliar process. If startup still fails, inspect the
component logs:

```bash
less "$HOME/mcp-ai-agent-lab/logs/catalyst_center_mcp.log"
less "$HOME/mcp-ai-agent-lab/logs/meraki_magic_mcp.log"
less "$HOME/mcp-ai-agent-lab/ai-agent-librechat-oss/logs/librechat_launcher.log"
less "$HOME/mcp-ai-agent-lab/ai-agent-librechat-oss/logs/ai_agent_librechat.log"
```

Before sharing log excerpts, remove credentials, bearer values, account
identifiers, real hostnames, IP addresses, and returned platform data.

## 7. Troubleshoot MCP initialization

LibreChat can take several seconds to initialize all five MCP servers. Wait up
to 45 seconds for the current application log:

```bash
cd "$HOME/mcp-ai-agent-lab"
python3 - <<'PY'
from pathlib import Path
import time

marker = "Initialized with 5 configured servers"
log_path = Path("ai-agent-librechat-oss/logs/ai_agent_librechat.log")
deadline = time.monotonic() + 45
ready = False

while time.monotonic() < deadline:
    log = log_path.read_text(errors="replace") if log_path.is_file() else ""
    if marker in log:
        ready = True
        break
    time.sleep(1)

print("LibreChat MCP initialization: OK" if ready else "NOT READY")
print()
raise SystemExit(0 if ready else 1)
PY
```

Then run the credential-safe remote probes directly:

```bash
LAB_ENV="$HOME/lab.env" \
  .venv/bin/python scripts/check_remote_mcp.py
printf '\n'
```

Interpret common results as follows:

- `401 Unauthorized` with `missing api key` from an intentionally
  unauthenticated local `/mcp` request is a successful negative security test.
- `AVAILABLE` proves that a remote endpoint completed MCP initialization.
- A transient `Ping failed` line during startup is not by itself a failure if
  the final five-server initialization succeeds and the tools work in a fresh
  LibreChat chat.
- Repeated connection failures require checking endpoint policy, DNS, outbound
  HTTPS, credential validity, and service availability. Never print the bearer
  token while diagnosing them.

## 8. Troubleshoot model providers

Run the non-generative, credential-safe model checks:

```bash
cd "$HOME/mcp-ai-agent-lab"
LAB_ENV="$HOME/lab.env" \
  .venv/bin/python scripts/check_llm_status.py
printf '\n'
```

Common causes:

- `InvalidClientTokenId` or “security token is invalid” means the configured
  AWS access-key pair is invalid, mistyped, inactive, or belongs to a deleted
  identity. Long-lived IAM access keys do not use a session token.
- `AccessDenied` for `bedrock:InvokeModelWithResponseStream` means the
  authenticated IAM identity lacks that action for the selected inference
  profile.
- `REACHABLE (profile lookup not authorized)` only identifies the optional
  control-plane permission; confirm actual inference in a fresh LibreChat
  chat.
- LiteLLM HTTP `401` or `403` usually means the API key is missing, expired,
  or unauthorized for the selected model alias.
- “Tool definitions consume” more tokens than `maxContextTokens` means too
  many MCP servers are selected for that model. LibreChat sends every selected
  tool definition before the model can choose a tool. With all 120 tools
  selected, acceptance testing measured approximately 83,000 tool tokens for
  SharonAI Gemma and 195,000 for Claude Haiku; both exceed their configured
  32,768-token limits. Counts vary by tokenizer and tool-catalog version.
  Start a new chat and select only the required server or servers. Do not
  raise `maxContextTokens` unless the provider confirms that the model
  supports the larger context window.

After changing any protected value, keep `lab.env` mode `600`, restart the
application, and use a new LibreChat chat:

```bash
chmod 600 "$HOME/lab.env"
make app-down
make app-up
make app-status
printf '\n'
```

## 9. Recheck TLS certificates

The local certificate is intentionally self-signed for the isolated lab.
Verify it before trusting it or distributing a Sandbox:

```bash
cd "$HOME/mcp-ai-agent-lab"
openssl x509 -checkend 0 -noout -in certs/mcp-selfsigned.crt
openssl x509 -noout -dates -subject -issuer -ext subjectAltName \
  -in certs/mcp-selfsigned.crt
openssl x509 -text -noout -in certs/mcp-selfsigned.crt | \
  awk '/Public-Key:/ {print; exit}'
openssl x509 -text -noout -in certs/mcp-selfsigned.crt | \
  awk '/Signature Algorithm:/ {print; exit}'
printf '\n'
```

Require a currently valid certificate, RSA 2048 bits or stronger (or EC P-256
or stronger), a SHA-2 signature, and SAN entries for `localhost` and
`127.0.0.1`. An identical issuer and subject is expected only because this is
an isolated self-signed lab certificate; use a trusted CA for production.

## 10. Reset LibreChat MongoDB data

This optional, destructive procedure permanently removes every LibreChat user,
session, conversation, and application record from the Sandbox. It does not
remove `$HOME/lab.env`, provider credentials, MCP configuration, installed
software, or the MongoDB service.

Use it only when preparing a clean student image or intentionally resetting a
test Sandbox. First verify that `lab.env` points to the expected local
`LibreChat` database without displaying the URI:

```bash
cd "$HOME/mcp-ai-agent-lab"
source .venv/bin/activate

python3 - <<'PY'
from pathlib import Path
from dotenv import dotenv_values

expected = "mongodb://127.0.0.1:27017/LibreChat"
actual = dotenv_values(Path.home() / "lab.env").get("MONGO_URI")
valid = actual == expected

print("MongoDB reset target: VERIFIED" if valid else "UNEXPECTED; STOP")
print()
raise SystemExit(0 if valid else 1)
PY
```

Stop LibreChat and require explicit confirmation:

```bash
make app-down

read -r -p \
  "Type RESET-LIBRECHAT to permanently delete all LibreChat data: " \
  confirmation
test "$confirmation" = "RESET-LIBRECHAT" || {
  echo "Reset cancelled."
  exit 1
}
printf '\n'
```

Drop only the verified local database:

```bash
mongosh "mongodb://127.0.0.1:27017/LibreChat" \
  --quiet \
  --eval 'db.dropDatabase()'

mongosh "mongodb://127.0.0.1:27017/LibreChat" \
  --quiet \
  --eval 'print("Collections after reset: " + db.getCollectionNames().length)'
printf '\n'
```

Expected:

```text
{ ok: 1, dropped: 'LibreChat' }
Collections after reset: 0
```

Restart LibreChat:

```bash
make app-up
make app-status
printf '\n'
```

Opening LibreChat should now show no previous users or chat history. Create a
new test account only when continued validation is required.

## 11. Check a student's build progress

Use the read-only progress checker when a student is unsure which build step
is complete. It checks sequential local milestones without displaying
credentials or platform data:

1. repository files;
2. Ubuntu 24.04 and common commands;
3. Python 3.13 and locked dependencies;
4. protected `lab.env` permissions and validation;
5. MongoDB, nginx, Node.js, and npm;
6. the LibreChat installation and generated files;
7. local listeners and HTTPS health endpoints; and
8. LibreChat initialization of five MCP servers.

Run it from the cloned repository with the system Python. The checker does not
require the virtual environment to be active:

```bash
cd "$HOME/mcp-ai-agent-lab"
python3 scripts/check_lab_progress.py
```

Example result from a partially completed build:

```text
Lab build progress
==================
[PASS] 1. Repository: required lab files are present
[PASS] 2. Host prerequisites: Ubuntu 24.04 and common commands are ready
[PASS] 3. Python environment: Python 3.13 and locked dependencies pass
[NOT READY] 4. Protected configuration: lab.env validation failed
...

Sequential progress: 3/8 checkpoints
Next checkpoint: Protected configuration
Next action: Ask the instructor to restore lab.env, run chmod 600, then make check-env
```

`NOT READY` and exit status `1` are expected when the student has not reached
the next checkpoint. Resolve the reported next action and rerun the checker.
It intentionally reports later checks too, but sequential progress stops at
the first incomplete milestone. When the local runtime is healthy, checkpoint
8 automatically waits up to 45 seconds for normal LibreChat MCP
initialization before reporting `NOT READY`.

After all local checkpoints pass, include the existing live remote MCP and
model status output:

```bash
python3 scripts/check_lab_progress.py --live
```

The live mode calls `make status`. Review every remote MCP and model result;
the status command is informational and can complete even when an external
service is unavailable.
