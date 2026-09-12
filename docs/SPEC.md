# Specification: Google Ads MCP

Tracking issue: https://github.com/epave/google-ads-mcp/issues/3  
Plan: `/opt/cursor/artifacts/plans/google_ads_mcp_cd0b18ff.plan.md`

Speckit skills are not available in this environment. This file is the specify → plan → tasks record.

## Specify

Agents (Claude Code, Codex, Cursor) manage Google Ads from MCP:

- Official-parity reads: `list_accessible_customers`, `search`, `get_resource_metadata`
- Convenience lists + MCP dashboard (`get_campaign_dashboard`)
- Pause/enable, budget, bidding
- Create/modify Search, Display, and standard Performance Max
- Writes gated: disabled by default, preview + `confirm_token`, creates PAUSED

DuckDB is local audit/snapshots only. User override: **DuckDB 2.0 alpha**, not plan 1.5.x.

## Plan

uv + FastMCP + official `google-ads` client + DuckDB 2.0 (`VARIANT` payloads). Stdio for local hosts. No web UI.

## Tasks

1. Scaffold, OAuth helper, official-parity reads
2. Dashboard + DuckDB snapshots
3. Safety gate + status/budget writes + audit
4. Search create/edit (PAUSED)
5. Image assets, Display, PMax
6. Host docs + unit tests (no live API in CI)
