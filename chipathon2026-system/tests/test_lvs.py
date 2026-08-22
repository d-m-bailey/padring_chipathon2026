import pytest

from chipathon2026_integration.errors import ConfigError
from chipathon2026_integration.lvs import (
    get_layout_file,
    normalize_repo_path,
    resolve_downloaded_gds,
    resolve_json_variables,
)


def test_variable_resolution():
    cfg = {
        "TOP_SOURCE": "demo",
        "GDS_DIR": "$UPRJ_ROOT/gds",
        "LAYOUT_FILE": "$GDS_DIR/${TOP_SOURCE}.gds",
    }
    assert get_layout_file(cfg, uprj_root="/work/repo") == "/work/repo/gds/demo.gds"


def test_uprj_root_can_remain_for_repo_normalization():
    cfg = {"TOP_SOURCE": "demo", "LAYOUT_FILE": "$UPRJ_ROOT/gds/$TOP_SOURCE.gds"}
    assert normalize_repo_path(get_layout_file(cfg)) == "gds/demo.gds"


def test_layout_file_not_layout_data():
    with pytest.raises(ConfigError, match="LAYOUT_FILE"):
        get_layout_file({"LAYOUT_DATA": "$UPRJ_ROOT/demo.gds"})


def test_cycle_rejected():
    with pytest.raises(ConfigError, match="cyclic"):
        resolve_json_variables({"A": "$B", "B": "$A", "LAYOUT_FILE": "$A"})


def test_downloaded_gds_comes_from_layout_file_not_directory_order(tmp_path):
    team_dir = tmp_path / "A01"
    team_dir.mkdir()
    selected = team_dir / "selected.gds"
    selected.write_bytes(b"selected")
    (team_dir / "aaa_first.gds").write_bytes(b"wrong")
    config = {
        "TOP_SOURCE": "selected",
        "GDS_DIR": "$UPRJ_ROOT/layout",
        "LAYOUT_FILE": "$GDS_DIR/$TOP_SOURCE.gds",
    }
    assert resolve_downloaded_gds(config, team="A01", gds_dir=tmp_path) == selected
