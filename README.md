# google-ads-mcp

MCP server so Claude Code, Codex, Cursor, and other agents can **read, pause/run, and create** Google Ads campaigns.

It covers the official [Google Ads MCP](https://developers.google.com/google-ads/api/docs/developer-toolkit/mcp-server) read surface (`list_accessible_customers`, `search`, `get_resource_metadata`) and adds writes plus an MCP-native dashboard. There is no web UI — `get_campaign_dashboard` returns a compact table an agent can act on.

New campaigns are created **PAUSED**. Writes default to a preview + `confirm_token` step.

## Stack

- [uv](https://docs.astral.sh/uv/)
- [FastMCP 4](https://gofastmcp.com/)
- Official [google-ads](https://github.com/googleads/google-ads-python) Python client against **Google Ads API v25** (library default in `google-ads` 32.x)
- **DuckDB 2.0 alpha** for the local audit log, preview tokens, and dashboard snapshots (not live campaign state)

DuckDB 2.0 is not stable yet (GA targeted late October 2026). This project installs the current `--pre` Python wheel (`duckdb>=2.0.0.dev0`). Payloads use the 2.0 `VARIANT` type.

## Prerequisites

1. A Google Cloud project with the [Google Ads API](https://console.cloud.google.com/apis/library/googleads.googleapis.com) enabled
2. An OAuth **Desktop** client ID / secret
3. A [developer token](https://developers.google.com/google-ads/api/docs/get-started/dev-token) (Explorer+ for production reads). Use a **test account** until you trust writes.
4. If you access accounts through a manager (MCC), the manager customer ID

## Install

```bash
uv sync --extra dev
```

Copy `.env.example` to `.env` in this repo (gitignored) and fill in:

```bash
GOOGLE_ADS_DEVELOPER_TOKEN=...
GOOGLE_ADS_CLIENT_ID=...
GOOGLE_ADS_CLIENT_SECRET=...
GOOGLE_ADS_REFRESH_TOKEN=...
# Only if you access client accounts through an MCC:
# GOOGLE_ADS_LOGIN_CUSTOMER_ID=0000000000
GOOGLE_ADS_WRITE_ENABLED=false
```

One-time OAuth if you do not already have a refresh token (writes `~/.google-ads-mcp/google-ads.yaml`):

```bash
uv run google-ads-mcp auth \
  --client-id "$GOOGLE_ADS_CLIENT_ID" \
  --client-secret "$GOOGLE_ADS_CLIENT_SECRET" \
  --developer-token "$GOOGLE_ADS_DEVELOPER_TOKEN"
```

`google-ads-mcp-auth` and `uv run python scripts/auth.py` are the same helper.

You can also drop an ADC JSON file at `~/.config/google-ads-mcp/adc.json` (or set `GOOGLE_ADS_ADC_PATH`). Include `developer_token` plus either installed-app OAuth fields (`client_id`, `client_secret`, `refresh_token`) or a standard `authorized_user` / `service_account` ADC object.

Load order: `google-ads.yaml` (if present) → `adc.json` → `GOOGLE_ADS_*` / `.env`.

## Connect an agent host

All hosts launch the server over **stdio**. Set `cwd` (or `--directory`) to this repo so `.env` is found. Restart the host after editing config.

Replace `/ABS/PATH/TO/google-ads-mcp` with the clone path (example: `/Users/you/personal/google-ads-mcp`).

### Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.google-ads]
command = "uv"
args = ["run", "--directory", "/ABS/PATH/TO/google-ads-mcp", "google-ads-mcp"]
cwd = "/ABS/PATH/TO/google-ads-mcp"
```

`cwd` is required for `.env`. Restart Codex, then:

```bash
codex mcp list
```

You should see `google-ads`. Optional: require a click-to-run on specific tools:

```toml
[mcp_servers.google-ads.tools.get_campaign_dashboard]
approval_mode = "approve"
```

### Claude Code

```bash
claude mcp add google-ads -- uv run --directory /ABS/PATH/TO/google-ads-mcp google-ads-mcp
```

### Cursor

`.cursor/mcp.json` in the project (or your user MCP config):

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
| Confirm token | required | Leave `GOOGLE_ADS_SKIP_CONFIRM` unset. `true` applies writes in one shot — keep it off for Codex/Claude. |
| Customer allowlist | none | `GOOGLE_ADS_ALLOWED_CUSTOMER_IDS=123,456` |
| Budget increase cap | 20% | `GOOGLE_ADS_BUDGET_INCREASE_CAP=0.20` (`force=true` to override) |
| Remove entity | blocked | `REMOVED` on status tools requires `force=true` |
| Local store | `~/.google-ads-mcp/state.duckdb` | `GOOGLE_ADS_MCP_DB` |
| Image uploads | cwd | `GOOGLE_ADS_ASSET_ROOT` |
| Audience / creator insights | off | `GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true` (Google allowlist required) |

Typical write: call the tool with `dry_run=true` → inspect the preview → call again with the same arguments, `dry_run=false`, and `confirm_token`. Status is stored uppercase (`paused` and `PAUSED` are the same token). New campaigns, ad groups, and keywords stay **PAUSED**; enabling is a second call. Do not set `GOOGLE_ADS_SKIP_CONFIRM=true` in an agent host — that skips the preview and mutates immediately.

## Tools

**Read (official parity)**

- `list_accessible_customers`
- `search` — GAQL builder
- `get_resource_metadata`

**Read (convenience)**

- `list_campaigns`, `get_campaign`, `list_ad_groups`, `list_ads`, `list_keywords`
- `get_search_terms`, `get_change_events`, `get_recommendations`
- `get_search_term_insights` / `get_search_term_insight_terms` — category-level Search term insights (volume, clicks, conversions, emerging vs prior window; PMax included)
- `get_impression_share_summary` — search / top / absolute-top share, lost to budget vs rank, period-over-period
- `get_campaign_dashboard` — running campaigns, spend, CPA, alerts, vs last snapshot
- `get_local_audit` — DuckDB write history

**Audience insights** (off until `GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true`; Google allowlist required)

- `list_audience_insights_attributes`, `generate_audience_composition_insights`, `generate_suggested_targeting_insights`
- Also gated: `list_insights_eligible_dates`, `generate_audience_definition`, `generate_audience_overlap_insights`, `generate_targeting_suggestion_metrics`, `generate_insights_finder_report`, `generate_creator_insights`, `generate_trending_insights`

**Manage**

- `set_campaign_status` / `set_ad_group_status` / `set_ad_status` / `set_keyword_status` (`REMOVED` needs `force=true`)
- `update_campaign_budget`, `update_campaign_bidding`

**Create / expand** (campaigns, ad groups, and keywords default PAUSED)

- `create_search_campaign` — budget + campaign + ad group + RSA + keywords
- `create_display_campaign` — needs image assets (1.91:1 and 1:1)
- `create_pmax_campaign` — standard Performance Max, not retail/Merchant Center
- `upload_image_asset`, `create_ad_group`, `add_keywords` (pass `status=ENABLED` only if you intend to serve immediately)
- `update_responsive_search_ad` — replace RSA headlines/descriptions (headlines ≤30 chars, descriptions ≤90)
- `add_campaign_locations` / `add_campaign_languages` — geo (e.g. `2840` US) and language (e.g. `1000` English)
- `add_asset_group_text` — add headlines/descriptions to a PMax asset group

Shopping, Demand Gen, Video, and App campaign *creation* are out of scope. Those types can still be listed, reported, paused, and enabled.

## Practical examples

IDs below are placeholders. Start every session with `list_accessible_customers` and copy a **non-manager** `customer_id`. Manager (MCC) accounts cannot return campaign metrics.

### 1. See the dashboard (no web UI)

Chat:

```text
List the Google Ads accounts I can access.
Then show the campaign dashboard for <customer_id>, including paused campaigns.
```

What the agent should call:

```text
list_accessible_customers()
get_campaign_dashboard(customer_id="1234567890", include_paused=true)
```

Example payload (markdown is in `markdown`):

```text
| Campaign | Type | Status | Budget/day | Spend today | Spend 7d | Clicks 7d | Conv 7d | CPA 7d |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Campaign #1 | PERFORMANCE_MAX | ENABLED | 100.00 | 0.00 | 86.66 | 33 | 0.0 | — |
```

Alerts look like `LIMITED`, `BIDDING_STRATEGY_LEARNING`, or policy limits on asset groups. Call the same tool again later to get spend deltas vs the last local snapshot.

Same thing from a terminal (no chat host):

```bash
uv run python -c "
import asyncio
from google_ads_mcp.server import create_server
from fastmcp import Client

async def main():
    async with Client(create_server()) as c:
        r = await c.call_tool('get_campaign_dashboard', {
            'customer_id': '1234567890',
            'include_paused': True,
        })
        print(r.structured_content['markdown'])

asyncio.run(main())
"
```

### 2. Inspect one campaign

```text
List all campaigns on <customer_id>, then get details and last-7-day metrics for campaign <campaign_id>.
```

```text
list_campaigns(customer_id="1234567890", status="ALL", limit=20)
get_campaign(customer_id="1234567890", campaign_id="111")
list_ad_groups(customer_id="1234567890", campaign_id="111")
get_search_terms(customer_id="1234567890", campaign_id="111", limit=25)
get_search_term_insights(customer_id="1234567890", campaign_id="111")
get_recommendations(customer_id="1234567890")
```

### 3. Pause or resume (two-step write)

Set `GOOGLE_ADS_WRITE_ENABLED=true` in `.env` first. Leave confirm tokens on.

Chat:

```text
Pause campaign 111 on account 1234567890 if it is ENABLED.
Preview first, show me the confirm_token, then apply only after I say go.
```

Tool sequence:

```text
# 1) preview
set_campaign_status(
  customer_id="1234567890",
  campaign_id="111",
  status="PAUSED",
  dry_run=true,
)
# → { "status": "preview", "confirm_token": "...", "description": "Set campaign 111 to PAUSED" }

# 2) apply (same arguments + token)
set_campaign_status(
  customer_id="1234567890",
  campaign_id="111",
  status="PAUSED",
  dry_run=false,
  confirm_token="<token from step 1>",
)
# → { "status": "applied", "campaign_status": "PAUSED" }

# 3) verify
get_campaign(customer_id="1234567890", campaign_id="111")
```

Resume the same way with `status="ENABLED"`. Do not pass `confirm_token` on a `dry_run=true` call. `REMOVED` is a hard delete — it needs `force=true` on both the preview and the apply.

### 4. Change budget

Amounts are in account currency, not micros. A raise of more than 20% needs `force=true`.

```text
update_campaign_budget(
  customer_id="1234567890",
  campaign_id="111",
  daily_budget=120,
  dry_run=true,
)
```

### 5. Raw GAQL

```text
search(
  customer_id="1234567890",
  resource="campaign",
  fields=["campaign.id", "campaign.name", "campaign.status", "metrics.clicks", "metrics.cost_micros"],
  conditions=["campaign.status = 'ENABLED'", "segments.date DURING LAST_7_DAYS"],
  orderings=["metrics.clicks DESC"],
  limit=10,
)
```

If you are unsure of field names:

```text
get_resource_metadata(resource="campaign")
```

### 6. Create a paused Search campaign

Needs ≥3 headlines (≤30 chars) and ≥2 descriptions (≤90 chars). Always created **PAUSED**.

```text
Create a paused Search campaign on 1234567890 named "Spring shoes", $25/day,
final URL https://example.com, headlines ["Buy shoes","Spring sale","Free shipping"],
descriptions ["Shop the new drop.","Limited time offer."], keywords ["running shoes"].
Preview, then apply when I confirm. Do not enable it.
```

```text
create_search_campaign(
  customer_id="1234567890",
  name="Spring shoes",
  daily_budget=25,
  final_url="https://example.com",
  headlines=["Buy shoes", "Spring sale", "Free shipping"],
  descriptions=["Shop the new drop.", "Limited time offer."],
  keywords=["running shoes"],
  dry_run=true,
)
```

After apply, enable only with an explicit `set_campaign_status(..., status="ENABLED")`.

Optional follow-ups:

```text
add_campaign_locations(customer_id="1234567890", campaign_id="111", geo_target_constant_ids=["2840"])
add_campaign_languages(customer_id="1234567890", campaign_id="111", language_constant_ids=["1000"])
add_keywords(customer_id="1234567890", ad_group_id="222", keywords=["trail running shoes"], match_type="PHRASE")
create_ad_group(customer_id="1234567890", campaign_id="111", name="Second ad group")
update_responsive_search_ad(
  customer_id="1234567890",
  ad_id="333",
  headlines=["Buy shoes", "Spring sale", "Free shipping"],
  descriptions=["Shop the new drop.", "Limited time offer."],
)
```

### 7. Display or Performance Max (images first)

Put files under `GOOGLE_ADS_ASSET_ROOT` (defaults to the process cwd, i.e. this repo if you set `cwd` correctly).

Required sizes:

- Display RDA: landscape **600×314** (1.91:1) and square **300×300**
- PMax: logo + landscape marketing image + square marketing image

```text
upload_image_asset(customer_id="1234567890", name="hero-landscape", source="./assets/hero-600x314.png")
upload_image_asset(customer_id="1234567890", name="hero-square", source="./assets/hero-300x300.png")
upload_image_asset(customer_id="1234567890", name="logo", source="./assets/logo.png")
```

HTTPS URLs are allowed if they are public, non-redirecting, and under 10MB. Then:

```text
create_display_campaign(
  customer_id="1234567890",
  name="Display spring",
  daily_budget=20,
  final_url="https://example.com",
  business_name="Acme",
  headlines=["Spring sale"],
  long_headline="New drop with free shipping",
  descriptions=["Shop the collection."],
  marketing_image_asset="customers/1234567890/assets/AAA",
  square_marketing_image_asset="customers/1234567890/assets/BBB",
)

create_pmax_campaign(
  customer_id="1234567890",
  name="PMax spring",
  daily_budget=30,
  final_url="https://example.com",
  business_name="Acme",
  headlines=["H1", "H2", "H3"],
  long_headline="Long headline here",
  descriptions=["D1", "D2"],
  logo_asset="customers/1234567890/assets/CCC",
  marketing_image_asset="customers/1234567890/assets/AAA",
  square_marketing_image_asset="customers/1234567890/assets/BBB",
)
```

Retail / Merchant Center PMax is out of v1.

### 8. Insights (audience, creators, search categories)

Audience and YouTube creator tools stay unregistered until `GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true` (the Ads account must also be allowlisted). Search term insights and impression share do not need that flag. Geo targets are numeric IDs (`2840` is the United States). Discover topics first, then pass the knowledge-graph ids through:

```text
list_audience_insights_attributes(
  customer_id="1234567890",
  query_text="running shoes",
  country_location="2840",
  entity_capabilities=["CREATOR_TOPIC_INSIGHTS"],
)
generate_suggested_targeting_insights(
  customer_id="1234567890",
  country_location="2840",
  audience_description="runners in their 30s who buy trail shoes",
)
generate_creator_insights(
  customer_id="1234567890",
  country_locations=["2840"],
  topics=["/m/06ntj"],
)
get_search_term_insights(customer_id="1234567890", campaign_id="111")
get_search_term_insight_terms(customer_id="1234567890", campaign_id="111", insight_id="9")
get_impression_share_summary(customer_id="1234567890")
```

`get_search_terms` is still the raw `search_term_view` list. Use `get_search_term_insights` for grouped categories (including Performance Max) and the `emerging` list for new or fast-growing demand.

### 9. MCC vs client accounts

`list_accessible_customers` may return both a manager and a client. Dashboards and metrics must use the **client** id. On an MCC you will get a message to pick a non-manager customer instead of a metrics API error.

Every Ads tool accepts optional `login_customer_id`. The client is rebuilt when that header changes (it is no longer a single process-wide cache). If client-account calls fail because a manager header is stuck, pass `login_customer_id="none"` on that call.

If client-account calls fail with “login-customer-id must be set”, pass the MCC id on the tool or add it to `.env`:

```bash
GOOGLE_ADS_LOGIN_CUSTOMER_ID=0000000000
```

### 10. See what the agent already mutated

```text
get_local_audit(limit=20)
```

That reads the local DuckDB log (previews and applies), not live Google Ads change history. Use `get_change_events` for the API change stream.

## Build harness

CI (`.github/workflows/ci.yml`) installs with uv, runs ruff + pytest, then `google-ads-mcp-harness` until findings converge (max 3 rounds). A scheduled/manual workflow reviews every open PR.

```bash
uv sync --extra dev --prerelease=allow
uv run pytest
uv run ruff check src tests
uv run python scripts/smoke_mcp.py --stdio
uv run google-ads-mcp-harness --max-rounds 3 --fix
uv run google-ads-mcp-harness --all-open
```

`scripts/smoke_mcp.py` talks to the server like Claude Code / Codex would: lists tools, previews a paused Search create, confirms writes stay blocked, and reads the DuckDB audit. It does **not** call the live Ads API.

The harness fingerprints findings. It stops when the set is empty or unchanged. High-severity leftovers fail the build.

Live API calls are not run in CI. Use a Google Ads test account for end-to-end writes.
