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


def test_parse_named_pin_geometry_and_properties():
    design = parse_def_text('''
VERSION 5.8 ;
DESIGN d ;
UNITS DISTANCE MICRONS 200 ;
PINS 1 ;
- E18_Y + NET E18_Y + DIRECTION OUTPUT + USE SIGNAL
  + LAYER Metal3 ( 10 20 ) ( 30 40 )
  + LAYER Metal3 ( 50 20 ) ( 70 40 )
  + FIXED ( 100 200 ) N ;
END PINS
END DESIGN
''')
    pin = design.pins["E18_Y"]
    assert pin.direction == "OUTPUT"
    assert pin.use == "SIGNAL"
    assert [(rect.x1, rect.y1, rect.x2, rect.y2) for rect in pin.rects] == [
        (110, 220, 130, 240), (150, 220, 170, 240),
    ]
