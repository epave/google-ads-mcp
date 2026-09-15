import sys

from google_ads_mcp.server import main


def test_google_ads_mcp_auth_subcommand(monkeypatch) -> None:
    called: list[list[str]] = []

    def fake_auth(argv=None):
        called.append(list(argv or []))

    monkeypatch.setattr("google_ads_mcp.auth.main", fake_auth)
    monkeypatch.setattr(sys, "argv", ["google-ads-mcp", "auth", "--client-id", "x"])
    main()
    assert called == [["--client-id", "x"]]
