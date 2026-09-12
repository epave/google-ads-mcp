"""End-to-end smoke test for the google-ads-mcp server.

Spawns the MCP server as a subprocess over stdio (exactly how an MCP client such
as Claude Desktop or Cursor would launch it), then lists the advertised tools and
calls a couple of them. Run with::

    uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "google_ads_mcp"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"Connected to server: {init.server_info.name} "
                  f"v{init.server_info.version}")

            tools = await session.list_tools()
            print("\nAdvertised tools:")
            for tool in tools.tools:
                summary = (tool.description or "").splitlines()[0]
                print(f"  - {tool.name}: {summary}")

            print("\nCalling health_check ...")
            health = _payload(await session.call_tool("health_check", {}))
            print(json.dumps(health, indent=2))

            print("\nCalling list_campaigns (no credentials configured) ...")
            campaigns = _payload(
                await session.call_tool("list_campaigns", {"customer_id": "123-456-7890"})
            )
            print(json.dumps(campaigns, indent=2))

    print("\nSmoke test completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
