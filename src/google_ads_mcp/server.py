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
get_resource_metadata. Additional tools list campaigns/ads/keywords and return a
compact dashboard (get_campaign_dashboard).

Writes are off until GOOGLE_ADS_WRITE_ENABLED=true. New campaigns are created
PAUSED. Mutates default to dry_run and return a confirm_token; call again with
that token to apply. Start with a test account.

Typical flow:
1. list_accessible_customers
2. get_campaign_dashboard
3. preview a write (dry_run=true)
4. apply with confirm_token
""".strip()


def create_server() -> FastMCP:
    mcp = FastMCP("google-ads", instructions=INSTRUCTIONS, version=__version__)
    register_all(mcp)
    return mcp


def main() -> None:
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
