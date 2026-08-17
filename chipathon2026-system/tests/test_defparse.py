from chipathon2026_integration.defparse import parse_def_text


def test_parse_components():
    text = '''
VERSION 5.8 ;
DESIGN d ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 200000 ) ;
COMPONENTS 2 ;
- reset_n gf180mcu_fd_io__in_c
  + FIXED ( 1000 2000 ) N ;
- data_7 gf180mcu_fd_io__bi_t + PLACED ( 3000 4000 ) FW ;
END COMPONENTS
END DESIGN
'''
    d = parse_def_text(text)
    assert d.units == 1000
    assert d.diearea == (0, 0, 100000, 200000)
    assert d.components["reset_n"].macro == "gf180mcu_fd_io__in_c"
    assert d.components["data_7"].orientation == "FW"
