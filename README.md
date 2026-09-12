# google-ads-mcp

MCP server so Claude Code, Codex, Cursor, and other agents can **read, pause/run, and create** Google Ads campaigns.

It covers the official [Google Ads MCP](https://developers.google.com/google-ads/api/docs/developer-toolkit/mcp-server) read surface (`list_accessible_customers`, `search`, `get_resource_metadata`) and adds writes plus an MCP-native dashboard. There is no web UI — `get_campaign_dashboard` returns a compact table an agent can act on.

New campaigns are created **PAUSED**. Writes default to a preview + `confirm_token` step.

## Stack

- [uv](https://docs.astral.sh/uv/)
- [FastMCP](https://gofastmcp.com/)
- Official [google-ads](https://github.com/googleads/google-ads-python) Python client
- **DuckDB 2.0 alpha** for the local audit log, preview tokens, and dashboard snapshots (not live campaign state)

DuckDB 2.0 is not stable yet (GA targeted late October 2026). This project installs the current `--pre` Python wheel, which bundles DuckDB `2.0.0-alpha`. Payloads use the 2.0 `VARIANT` type. Pin or upgrade the pre-release as you like; rollback is `duckdb==1.5.5` if the alpha breaks.

## Prerequisites

1. A Google Cloud project with the [Google Ads API](https://console.cloud.google.com/apis/library/googleads.googleapis.com) enabled
2. An OAuth **Desktop** client ID / secret
3. A [developer token](https://developers.google.com/google-ads/api/docs/get-started/dev-token) (Explorer+ for production reads). Use a **test account** until you trust writes.
4. If you access accounts through a manager (MCC), the manager customer ID

## Install

```bash
uv sync --extra dev
```

One-time OAuth (writes `~/.google-ads-mcp/google-ads.yaml`):

```bash
uv run google-ads-mcp-auth \
  --client-id "$GOOGLE_ADS_CLIENT_ID" \
  --client-secret "$GOOGLE_ADS_CLIENT_SECRET" \
  --developer-token "$GOOGLE_ADS_DEVELOPER_TOKEN"
```

Or copy `.env.example` / `google-ads.yaml.example` and fill them in.

## Connect an agent host

All hosts should launch via stdio with `uv run`. Point `GOOGLE_ADS_CONFIGURATION_FILE_PATH` at your yaml, or set the `GOOGLE_ADS_*` env vars.

### Claude Code

```bash
claude mcp add google-ads -- uv run --directory /ABS/PATH/TO/google-ads-mcp google-ads-mcp
```

### Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.google-ads]
command = "uv"
args = ["run", "--directory", "/ABS/PATH/TO/google-ads-mcp", "google-ads-mcp"]
```

### Cursor

`.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "google-ads": {
      "command": "uv",
      "args": ["run", "--directory", "/ABS/PATH/TO/google-ads-mcp", "google-ads-mcp"]
    }
  }
}
```

## Safety

| Control | Default | Env |
|---|---|---|
| Writes | off | `GOOGLE_ADS_WRITE_ENABLED=true` |
| Confirm token | required | `GOOGLE_ADS_SKIP_CONFIRM=true` to skip |
| Customer allowlist | none | `GOOGLE_ADS_ALLOWED_CUSTOMER_IDS=123,456` |
| Budget increase cap | 20% | `GOOGLE_ADS_BUDGET_INCREASE_CAP=0.20` (`force=true` to override) |
| Local store | `~/.google-ads-mcp/state.duckdb` | `GOOGLE_ADS_MCP_DB` |

Typical write: call the tool with `dry_run=true` → inspect the preview → call again with `confirm_token`. Then `set_campaign_status(..., status="ENABLED")` when you are ready to spend.

## Tools

**Read (official parity)**

- `list_accessible_customers`
- `search` — GAQL builder
- `get_resource_metadata`

**Read (convenience)**

- `list_campaigns`, `get_campaign`, `list_ad_groups`, `list_ads`, `list_keywords`
- `get_search_terms`, `get_change_events`, `get_recommendations`
- `get_campaign_dashboard` — running campaigns, spend, CPA, alerts, vs last snapshot
- `get_local_audit` — DuckDB write history

**Manage**

- `set_campaign_status` / `set_ad_group_status` / `set_ad_status` / `set_keyword_status`
- `update_campaign_budget`, `update_campaign_bidding`

**Create / expand** (always PAUSED at campaign create)

- `create_search_campaign` — budget + campaign + ad group + RSA + keywords
- `create_display_campaign` — needs image assets (1.91:1 and 1:1)
- `create_pmax_campaign` — standard Performance Max, not retail/Merchant Center
- `upload_image_asset`, `create_ad_group`, `add_keywords`

Shopping, Demand Gen, Video, and App campaign *creation* are out of scope. Those types can still be listed, reported, paused, and enabled.

## Sample prompts

- What customers can I access?
- Show the dashboard for running campaigns on account 1234567890
- Pause campaign 111 unless it is already paused
- Create a paused Search campaign named "Spring shoes" with $25/day, these headlines, and these keywords

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
```

Live API calls are not run in CI. Use a Google Ads test account for end-to-end writes.
