from pathlib import Path

import pytest

from google_ads_mcp.tools.assets import read_asset_bytes


def test_rejects_http_url() -> None:
    with pytest.raises(ValueError, match="https"):
        read_asset_bytes("http://example.com/ad.png")


def test_rejects_loopback_https() -> None:
    with pytest.raises(ValueError, match="non-public"):
        read_asset_bytes("https://127.0.0.1/ad.png")


def test_rejects_path_outside_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    secret = tmp_path / "google-ads.yaml"
    secret.write_text("refresh_token: nope")
    monkeypatch.setenv("GOOGLE_ADS_ASSET_ROOT", str(root))
    with pytest.raises(ValueError, match="credential-like|must be under"):
        read_asset_bytes(str(secret))


def test_reads_png_under_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    image = root / "ad.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
    monkeypatch.setenv("GOOGLE_ADS_ASSET_ROOT", str(root))
    assert read_asset_bytes(str(image)).startswith(b"\x89PNG")
