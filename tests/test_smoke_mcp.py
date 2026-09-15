import asyncio
from pathlib import Path

from google_ads_mcp.smoke import smoke_inprocess


def test_inprocess_mcp_smoke(tmp_path: Path) -> None:
    report = asyncio.run(smoke_inprocess(tmp_path / "smoke.duckdb"))
    assert report["ok"] is True
    assert report["live_api"] is False
