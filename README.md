# google-ads-mcp

MCP server to manage Google Ads campaigns.

This is a [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes tools for inspecting and managing Google Ads campaigns, so an MCP client
(Cursor, Claude Desktop, etc.) can drive Google Ads through natural language.

## Tools

| Tool | Description |
| --- | --- |
| `health_check` | Report server status and whether credentials are configured. |
| `list_accessible_customers` | List customer accounts the credentials can access. |
| `list_campaigns` | List campaigns for a customer account. |
| `set_campaign_status` | Enable, pause, or remove a campaign. |
| `update_campaign_budget` | Update the daily amount of a campaign budget. |

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) for dependency management

## Setup

```bash
# Install dependencies (creates .venv automatically)
uv sync --extra dev

# Configure Google Ads credentials
cp .env.example .env
# ...then edit .env with your developer token and OAuth credentials
```

See [`.env.example`](.env.example) for how to obtain each credential. The server
starts and advertises its tools even without credentials; tool calls that need
the API return a clear error until credentials are configured.

## Running the server

The server speaks MCP over stdio, so it is normally launched by an MCP client:

```bash
uv run google-ads-mcp
# or
uv run python -m google_ads_mcp
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "google-ads": {
      "command": "uv",
      "args": ["run", "google-ads-mcp"],
      "env": {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "...",
        "GOOGLE_ADS_CLIENT_ID": "...",
        "GOOGLE_ADS_CLIENT_SECRET": "...",
        "GOOGLE_ADS_REFRESH_TOKEN": "...",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "..."
      }
    }
  }
}
```

## Development

```bash
# Run the test suite
uv run pytest

# Run the end-to-end stdio smoke test (spawns the server as a subprocess)
uv run python scripts/smoke_test.py
```
