"""FastMCP entrypoint."""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from google_ads_mcp import __version__
from google_ads_mcp.errors import AdsError
from google_ads_mcp.tools import register_all

INSTRUCTIONS = """
Google Ads MCP for managing campaigns from Claude Code, Codex, and other agents.

Read tools match the official Google Ads MCP: list_accessible_customers, search,
get_resource_metadata, get_server_info. Additional tools list campaigns/ads/keywords,
return a compact dashboard (get_campaign_dashboard), one-call diagnostics
(get_campaign_diagnostics), Google recommendations (get_recommendations) and local
hints (get_campaign_hints), search-term insight categories (get_search_term_insights),
and impression share (get_impression_share_summary). Campaign callouts and structured
snippets use add_campaign_callouts / add_campaign_structured_snippet.
Audience and YouTube creator tools stay hidden until
GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true (Google allowlist required).

Writes are off until GOOGLE_ADS_WRITE_ENABLED=true. New campaigns are created
PAUSED. Mutates default to dry_run and return a confirm_token with expires_at;
call again with that token to apply, or refresh_preview to extend TTL. Demand Gen
uses create_demand_gen_campaign (not the Display builder) plus list_user_lists /
create_audience. Start with a test account.

Typical flow:
1. get_server_info
2. list_accessible_customers
3. get_campaign_dashboard / get_campaign_diagnostics
4. preview a write (dry_run=true)
5. apply with confirm_token
""".strip()


def create_server() -> FastMCP:
    mcp = FastMCP("google-ads", instructions=INSTRUCTIONS, version=__version__)
    register_all(mcp)
    return mcp


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        from google_ads_mcp.auth import main as auth_main

        auth_main(sys.argv[2:])
        return
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        create_server().run()
    except AdsError as exc:
        logging.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
