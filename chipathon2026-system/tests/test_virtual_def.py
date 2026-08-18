from pathlib import Path

import pytest
import yaml

from chipathon2026_integration.errors import NotFinalizedError
from chipathon2026_integration.virtual_def import generate_virtual_def


LEF = r'''
MACRO gf180mcu_fd_io__in_c
  ORIGIN 0 0 ;
  SIZE 10 BY 20 ;
  PIN PU
    DIRECTION INPUT ;
    PORT
      LAYER Metal3 ;
      RECT 1 2 2 3 ;
    END
  END PU
  PIN PD
    DIRECTION INPUT ;
    PORT
      LAYER Metal3 ;
      RECT 3 2 4 3 ;
    END
  END PD
  PIN PAD
    DIRECTION INPUT ;
    PORT
      LAYER Metal5 ;
      RECT 0 0 10 1 ;
    END
  END PAD
  PIN Y
    DIRECTION OUTPUT ;
    PORT
      LAYER Metal3 ;
      RECT 5 2 6 3 ;
    END
  END Y
END gf180mcu_fd_io__in_c
'''


def setup_files(tmp_path: Path):
    mapping = {
        "pads": [
            {"pin_index": 0, "pin_name": "reset_n", "slot": "W13", "instance": "W13", "io_type": "input_cmos", "cell": "gf180mcu_fd_io__in_c"}
        ]
    }
    mp = tmp_path / "map.yaml"
    mp.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    dp = tmp_path / "ring.def"
    dp.write_text('''
VERSION 5.8 ;
DESIGN ring ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 100000 ) ;
COMPONENTS 1 ;
- W13 gf180mcu_fd_io__in_c + FIXED ( 10000 20000 ) N ;
END COMPONENTS
END DESIGN
''', encoding="utf-8")
    lp = tmp_path / "in_c.lef"
    lp.write_text(LEF, encoding="utf-8")
    return mp, dp, lp


def test_virtual_def_requires_explicit_diearea(tmp_path):
    mp, dp, lp = setup_files(tmp_path)
    with pytest.raises(NotFinalizedError, match="DIEAREA"):
        generate_virtual_def(mapping_path=mp, padring_def=dp, lef_paths=[lp], diearea=None)


def test_virtual_def_exposes_control_and_data_terminals(tmp_path):
    mp, dp, lp = setup_files(tmp_path)
    text, meta = generate_virtual_def(
        mapping_path=mp,
        padring_def=dp,
        lef_paths=[lp],
        diearea=(0, 0, 50000, 50000),
    )
    assert "PINS 3 ;" in text
    assert "reset_n_PU" in text
    assert "reset_n_PD" in text
    assert "reset_n_Y" in text
    # PU/PD are inputs to the I/O cell, hence outputs from the project.
    assert any(p["project_pin"] == "reset_n_PU" and p["direction"] == "OUTPUT" for p in meta["pins"])
    # Y is output from the I/O cell, hence input to the project.
    assert any(p["project_pin"] == "reset_n_Y" and p["direction"] == "INPUT" for p in meta["pins"])
