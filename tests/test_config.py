from pathlib import Path

import pytest

from google_ads_mcp.config import Settings, mkdir_private


def test_missing_explicit_yaml_raises(tmp_path: Path) -> None:
    settings = Settings.model_validate({"yaml_path": tmp_path / "missing.yaml"})
    with pytest.raises(FileNotFoundError, match="GOOGLE_ADS_CONFIGURATION_FILE_PATH"):
        settings.resolved_yaml_path()


def test_mkdir_private_skips_existing_parent(tmp_path: Path) -> None:
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o755)
    settings = Settings.model_validate({"db_path": parent / "state.duckdb"})
    settings.resolved_db_path()
    assert oct(parent.stat().st_mode)[-3:] == "755"


def test_mkdir_private_chmods_created_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "created" / "leaf"
    mkdir_private(nested)
    assert oct((tmp_path / "created").stat().st_mode)[-3:] == "700"
    assert oct(nested.stat().st_mode)[-3:] == "700"
