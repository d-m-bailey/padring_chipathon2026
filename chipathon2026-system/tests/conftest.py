from pathlib import Path

import pytest

from chipathon2026_integration.constants import GROUND_CELL, POWER_CELL


@pytest.fixture
def full_template(tmp_path: Path) -> Path:
    lines = [
        "# synthetic production-style immutable-slot template for tests",
        "DESIGN test_padring;",
        "AREA 2935 2935;",
        "GRID 0.005;",
        "CORNER C1 SE gf180mcu_fd_io__cor ;",
        "CORNER C2 SW gf180mcu_fd_io__cor ;",
        "CORNER C3 NE gf180mcu_fd_io__cor ;",
        "CORNER C4 NW gf180mcu_fd_io__cor ;",
        "FILLER gf180mcu_fd_io__fill5 ;",
        "BREAKFILLER gf180mcu_fd_io__brk5 ;",
    ]
    for side in "NESW":
        for n in range(1, 23):
            slot = f"{side}{n:02d}"
            cell = "gf180mcu_fd_io__asig_5p0"
            if slot in {"W11", "E11"}:
                cell = POWER_CELL
            elif slot in {"W12", "E12"}:
                cell = GROUND_CELL
            flip = " FLIP" if slot == "W14" else ""
            comment = " # keep me" if slot == "W15" else ""
            lines.append(f"PAD {slot} {side}{flip} {cell} ;{comment}")
            break_name = {
                "W12": "BRK_W12_W13", "E10": "BRK_E10_E11",
            }.get(slot)
            if break_name:
                lines.append("BREAK ;")
    path = tmp_path / "physical.cfg"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def minimal_info():
    return {
        "project": {"title": "Demo", "lvs_config": "lvs_config.json"},
        "pins": [
            {"name": "reset_n", "io_type": "input_schmitt"},
            {"name": "data[7]", "io_type": "bidirectional"},
            {"name": "ain", "io_type": "analog", "secondary_esd": True},
        ],
    }
