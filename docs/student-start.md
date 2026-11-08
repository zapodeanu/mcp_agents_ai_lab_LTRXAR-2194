# MCP AI Agent Lab: Student Start

Developed by Gabi Zapodeanu, PTME + Cursor/GPT-5.6 Sol

Use this page before cloning the lab repository. Complete each step in order
and stop if a verification fails.

## 1. Collect the instructor-provided access information

The instructor completes the following placeholders in a private handout or
learning-management system. Never replace them with real credentials in the
public Git repository.

```text
VPN access
  Client/application: <vpn-client>
  Endpoint:           <vpn-endpoint>
  Username:           <vpn-username>
  Password:           <provided-privately>

Ubuntu Sandbox access
  Hostname or IP:     <sandbox-host>
  Username:           <sandbox-user>
  Password:           <provided-privately>

LibreChat access
  Account procedure:  <signup-or-login-instructions>
  Username/email:     <student-account>
  Password:           <provided-privately>
```

Also obtain confirmation that `$HOME/lab.env` is already installed on the
Sandbox.

Do not request or post API keys, passwords, tokens, or the contents of
`lab.env` in chat, screenshots, issues, or shared notes.

## 2. Connect the Lab Computer to the VPN

1. Open `<vpn-client>` on the Lab Computer.
2. Enter `<vpn-endpoint>`.
3. Authenticate with the privately supplied VPN username and password.
4. Confirm that the VPN reports **Connected** before opening the Sandbox.

If VPN authentication fails, stop and contact the instructor. Do not continue
by exposing the Sandbox directly to the Internet.

## 3. Open a terminal and connect to the Ubuntu Sandbox

Use Terminal on macOS or Linux, or PowerShell/Windows Terminal on Windows.
Connect to the Ubuntu Sandbox:

```bash
ssh <sandbox-user>@<sandbox-host>
```

After login, confirm that the prompt belongs to the Sandbox:

```text
<sandbox-user>@<sandbox-host>:~$
```

All remaining commands on this page run on the Sandbox.

## 4. Confirm Ubuntu 24.04

```bash
. /etc/os-release
printf 'Operating system: %s %s\nArchitecture: ' "$NAME" "$VERSION_ID"
uname -m
printf '\n'
```

Continue only when the operating-system version is `24.04`.

## 5. Confirm the protected lab configuration exists

Check the file without opening, printing, copying, or sourcing it:

```bash
test -s "$HOME/lab.env" && echo "lab.env: present" || {
  echo "STOP: ask the instructor to restore lab.env"
  exit 1
}

test "$(stat -c '%a' "$HOME/lab.env")" = "600" && \
  echo "lab.env permissions: OK" || {
    echo "STOP: ask the instructor to correct lab.env permissions"
    exit 1
  }
printf '\n'
```

Expected:

```text
lab.env: present
lab.env permissions: OK
```

## 6. Install Git and clone the public repository

No GitHub account, token, or login is required:

```bash
sudo apt update
sudo apt install -y git

cd "$HOME"
git clone \
  https://github.com/zapodeanu/mcp_agents_ai_lab_LTRXAR-2194.git \
  mcp-ai-agent-lab

cd "$HOME/mcp-ai-agent-lab"
export LAB_ROOT="$PWD"
```

Verify the clone:

```bash
test -f "$LAB_ROOT/README.md"
test -f "$LAB_ROOT/docs/lab-guide.md"
test -f "$LAB_ROOT/scripts/check_lab_progress.py"
printf 'Lab repository: READY\n\n'
```

Expected:

```text
Lab repository: READY
```

## 7. Check the starting point

The progress checker is read-only and does not display credentials:

```bash
python3 scripts/check_lab_progress.py
```

At this early stage, later checkpoints can report `NOT READY`. That is
expected. Follow the reported next action.

## 8. Continue with the complete lab

Open the
[MCP AI Agent Lab Guide](https://github.com/zapodeanu/mcp_agents_ai_lab_LTRXAR-2194/blob/main/docs/lab-guide.md)
and continue at **Chapter 1.3: Install common packages**.

Useful links:

- [Repository README](https://github.com/zapodeanu/mcp_agents_ai_lab_LTRXAR-2194)
- [Complete student lab guide](https://github.com/zapodeanu/mcp_agents_ai_lab_LTRXAR-2194/blob/main/docs/lab-guide.md)

If the SSH connection closes later, reconnect and restore the lab shell
context:

```bash
cd "$HOME/mcp-ai-agent-lab"
export LAB_ROOT="$PWD"
test -d .venv && source .venv/bin/activate
```
