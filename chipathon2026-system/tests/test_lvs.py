import pytest

from chipathon2026_integration.errors import ConfigError
from chipathon2026_integration.lvs import get_layout_file, normalize_repo_path, resolve_json_variables


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
