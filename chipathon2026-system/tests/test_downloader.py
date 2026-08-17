import json
from unittest.mock import Mock

import pytest

from chipathon2026_integration.downloader import parse_info_bytes, parse_lvs_bytes, process_team
from chipathon2026_integration.errors import ConfigError


def test_parse_info_uses_project_lvs_config():
    info, path = parse_info_bytes(b"project:\n  lvs_config: lvs/lvs_config.json\npins:\n  - name: a\n    io_type: input_cmos\n")
    assert path == "lvs/lvs_config.json"


def test_parse_lvs_resolves_top_layout_and_layout_file():
    cfg = {
        "TOP_SOURCE": "user_project_wrapper",
        "TOP_LAYOUT": "$TOP_SOURCE",
        "GDS_DIR": "$UPRJ_ROOT/gds",
        "LAYOUT_FILE": "$GDS_DIR/$TOP_SOURCE.gds",
    }

    assert parse_lvs_bytes(json.dumps(cfg).encode()) == (
        "user_project_wrapper",
        "gds/user_project_wrapper.gds",
    )


@pytest.mark.parametrize("top_layout", [None, "", "   "])
def test_parse_lvs_rejects_missing_or_empty_top_layout(top_layout):
    cfg = {"LAYOUT_FILE": "$UPRJ_ROOT/gds/chip.gds"}
    if top_layout is not None:
        cfg["TOP_LAYOUT"] = top_layout

    with pytest.raises(ConfigError, match="TOP_LAYOUT"):
        parse_lvs_bytes(json.dumps(cfg).encode())


def test_process_team_rejects_unknown_repo_without_network(tmp_path, capsys):
    session = Mock()

    assert not process_team(session, "A03", "???", tmp_path / "info", tmp_path / "gds", False)
    session.get.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == "A03: ???\n"
    assert captured.err == "ERROR: Unknown repo for A03\n"
