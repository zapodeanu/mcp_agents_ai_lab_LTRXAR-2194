# Security Policy

## Supported version

Security updates apply to the current `main` branch.

## Reporting a vulnerability

Do not open a public issue containing a vulnerability, credential, token,
private hostname, account identifier, or platform data.

Use GitHub's private vulnerability reporting for this repository:

<https://github.com/zapodeanu/mcp_agents_ai_lab_LTRXAR-2194/security/advisories/new>

If a credential may have been exposed, revoke or rotate it immediately before
continuing the report. Removing a value from Git does not make the credential
safe again.

## Repository security model

- Real credentials belong only in the protected, Git-ignored
  `$HOME/lab.env`.
- Tracked environment examples contain placeholders only.
- Generated certificates and private keys remain under the ignored `certs/`
  directory.
- The local self-signed certificate is limited to the isolated teaching lab.
- Platform exercises default to read-only behavior and use bounded requests.
