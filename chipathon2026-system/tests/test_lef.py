from chipathon2026_integration.lef import parse_lef_text, validate_project_terminals


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


def test_parse_lef_and_project_terminals():
    macros = parse_lef_text(LEF)
    macro = macros["gf180mcu_fd_io__in_c"]
    assert macro.width == 10
    assert macro.pins["Y"].direction == "OUTPUT"
    assert macro.pins["PU"].rects[0].layer == "Metal3"
    assert validate_project_terminals(macros, [macro.name]) == {}


def test_missing_terminal_reported():
    macros = parse_lef_text(LEF.replace("PIN PD", "PIN XX").replace("END PD", "END XX"))
    assert validate_project_terminals(macros, ["gf180mcu_fd_io__in_c"])["gf180mcu_fd_io__in_c"] == ["PD"]
