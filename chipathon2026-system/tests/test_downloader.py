import json

from chipathon2026_integration.downloader import parse_info_bytes, parse_lvs_bytes


def test_download_parsers_use_project_lvs_and_layout_file():
    info, path = parse_info_bytes(b"project:\n  lvs_config: lvs/lvs_config.json\npins:\n  - name: a\n    io_type: input_cmos\n")
    assert path == "lvs/lvs_config.json"
    cfg = {"TOP": "chip", "LAYOUT_FILE": "$UPRJ_ROOT/gds/$TOP.gds"}
    assert parse_lvs_bytes(json.dumps(cfg).encode()) == "gds/chip.gds"
