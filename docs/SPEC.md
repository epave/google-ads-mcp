# Specification: Google Ads MCP

Tracking issue: https://github.com/epave/google-ads-mcp/issues/3  
Insights: https://github.com/epave/google-ads-mcp/issues/9  
Plan: `/opt/cursor/artifacts/plans/google_ads_mcp_cd0b18ff.plan.md`

Speckit skills are not available in this environment. This file is the specify → plan → tasks record.

## Specify

Agents (Claude Code, Codex, Cursor) manage Google Ads from MCP:

- Official-parity reads: `list_accessible_customers`, `search`, `get_resource_metadata`
- Convenience lists + MCP dashboard (`get_campaign_dashboard`)
- Pause/enable, budget, bidding
- Create/modify Search, Display, and standard Performance Max
- Writes gated: disabled by default, preview + `confirm_token`, creates PAUSED
- Official Insights reads ([overview](https://developers.google.com/google-ads/api/docs/insights/overview)):
  - Audience insights (`AudienceInsightsService`, allowlisted)
  - YouTube creator / trending insights (`ContentCreatorInsightsService`, allowlisted)
  - Search term insight categories (`campaign_search_term_insight` / `customer_search_term_insight`)

DuckDB is local audit/snapshots only. User override: **DuckDB 2.0 alpha**, not plan 1.5.x.

## Plan

uv + FastMCP 4 + official `google-ads` 32.x client (Google Ads API v25) + DuckDB 2.0 (`VARIANT` payloads). Stdio for local hosts. No web UI.

Insights tools are reads, except `generate_insights_finder_report`, which creates a remote report through SafetyGate. Search term insights and impression share are always registered. Audience/creator tools register only when `GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true`. Audience/creator calls set `customer_insights_group` to `google-ads-mcp` by default. Attributes accept compact dicts (`{"entity": "/m/014trl"}`) or metadata returned by `list_audience_insights_attributes`. No live Insights API in CI — request building is unit-tested with the fake Ads client.

## Tasks

1. Scaffold, OAuth helper, official-parity reads
2. Dashboard + DuckDB snapshots
3. Safety gate + status/budget writes + audit
4. Search create/edit (PAUSED)
5. Image assets, Display, PMax
6. Host docs + unit tests (no live API in CI)
7. Insights API tools (audience, creator, search-term categories) — issue #9
