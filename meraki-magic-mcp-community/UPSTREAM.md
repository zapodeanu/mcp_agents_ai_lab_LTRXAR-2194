# Upstream Source

This directory vendors the Meraki Magic MCP Community project for the
teaching lab.

- Repository: https://github.com/CiscoDevNet/meraki-magic-mcp-community
- Upstream commit: `8797f24b51e0fe3758a9f4f8394157c3c0d0b4e8`
- Upstream commit date: 2026-10-16
- License: MIT; see `LICENSE` in this directory

The upstream Git history is intentionally not bundled. To update this copy,
review a newer upstream revision, replace the vendored files, and update the
commit recorded above.

## Lab Integration Changes

- `requirements.txt` uses MCP SDK `1.30.0`, shared with the other bundled MCP
  servers. Meraki Magic's test suite passes with this version.
- Both server variants load credentials from `$HOME/lab.env`.
- Lab HTTP defaults use `127.0.0.1:8002` and support `MERAKI_MCP_*`
  transport overrides.
