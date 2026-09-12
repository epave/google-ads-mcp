from pathlib import Path

import pytest

from google_ads_mcp.config import Settings


def test_missing_explicit_yaml_raises(tmp_path: Path) -> None:
    settings = Settings.model_validate({"yaml_path": tmp_path / "missing.yaml"})
    with pytest.raises(FileNotFoundError, match="GOOGLE_ADS_CONFIGURATION_FILE_PATH"):
        settings.resolved_yaml_path()
