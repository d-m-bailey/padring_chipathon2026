from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


@dataclass(frozen=True)
class DefComponent:
    instance: str
    macro: str
    x: int
    y: int
    orientation: str
    placement: str


@dataclass(frozen=True)
class DefRect:
    layer: str
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class DefPin:
    name: str
    net: str
    direction: str
    use: str
    rects: tuple[DefRect, ...]
    x: int
    y: int
    orientation: str
    placement: str


@dataclass
class DefDesign:
    name: str
    units: int
    diearea: tuple[int, int, int, int] | None
    components: dict[str, DefComponent]
    pins: dict[str, DefPin]


DESIGN_RE = re.compile(r"^\s*DESIGN\s+(\S+)\s*;")
UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;")
DIEAREA_RE = re.compile(r"^\s*DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;")
COMP_RE = re.compile(
    r"-\s+(?P<instance>\S+)\s+(?P<macro>\S+).*?\+\s+"
    r"(?P<placement>FIXED|PLACED|COVER)\s+\(\s*(?P<x>-?\d+)\s+(?P<y>-?\d+)\s*\)\s+"
    r"(?P<orient>N|S|E|W|FN|FS|FE|FW)\b",
    re.S,
)
PIN_NAME_RE = re.compile(r"^-\s+(\S+)")
PIN_NET_RE = re.compile(r"\+\s+NET\s+(\S+)")
PIN_DIRECTION_RE = re.compile(r"\+\s+DIRECTION\s+(\S+)")
PIN_USE_RE = re.compile(r"\+\s+USE\s+(\S+)")
PIN_LAYER_RE = re.compile(
    r"\+\s+LAYER\s+(?P<layer>\S+)\s+"
    r"\(\s*(?P<x1>-?\d+)\s+(?P<y1>-?\d+)\s*\)\s+"
    r"\(\s*(?P<x2>-?\d+)\s+(?P<y2>-?\d+)\s*\)"
)
PIN_PLACEMENT_RE = re.compile(
    r"\+\s+(?P<placement>FIXED|PLACED|COVER)\s+"
    r"\(\s*(?P<x>-?\d+)\s+(?P<y>-?\d+)\s*\)\s+"
    r"(?P<orient>N|S|E|W|FN|FS|FE|FW)\b"
)


def _pin_point(x: int, y: int, orient: str) -> tuple[int, int]:
    transforms = {
        "N": (x, y), "S": (-x, -y), "W": (-y, x), "E": (y, -x),
        "FN": (-x, y), "FS": (x, -y), "FE": (-y, -x), "FW": (y, x),
    }
    try:
        return transforms[orient]
    except KeyError as exc:
        raise ConfigError(f"unsupported DEF pin orientation {orient!r}") from exc


def _parse_pin_entry(entry: str) -> DefPin:
    name_match = PIN_NAME_RE.search(entry)
    placement_match = PIN_PLACEMENT_RE.search(entry)
    if name_match is None or placement_match is None:
        raise ConfigError(f"cannot parse DEF pin entry: {entry!r}")
    name = name_match.group(1)
    px, py = int(placement_match.group("x")), int(placement_match.group("y"))
    orient = placement_match.group("orient")
    rects = []
    for match in PIN_LAYER_RE.finditer(entry):
        points = [
            _pin_point(int(match.group("x1")), int(match.group("y1")), orient),
            _pin_point(int(match.group("x2")), int(match.group("y2")), orient),
        ]
        xs, ys = [p[0] + px for p in points], [p[1] + py for p in points]
        rects.append(DefRect(match.group("layer"), min(xs), min(ys), max(xs), max(ys)))
    if not rects:
        raise ConfigError(f"DEF pin {name!r} has no LAYER rectangles")
    net_match = PIN_NET_RE.search(entry)
    direction_match = PIN_DIRECTION_RE.search(entry)
    use_match = PIN_USE_RE.search(entry)
    return DefPin(
        name=name,
        net=net_match.group(1) if net_match else name,
        direction=direction_match.group(1).upper() if direction_match else "INOUT",
        use=use_match.group(1).upper() if use_match else "SIGNAL",
        rects=tuple(rects),
        x=px,
        y=py,
        orientation=orient,
        placement=placement_match.group("placement"),
    )


def parse_def_text(text: str) -> DefDesign:
    name = "project"
    units = 1000
    diearea = None
    components: dict[str, DefComponent] = {}
    pins: dict[str, DefPin] = {}

    for line in text.splitlines():
        if m := DESIGN_RE.match(line):
            name = m.group(1)
        elif m := UNITS_RE.match(line):
            units = int(m.group(1))
        elif m := DIEAREA_RE.match(line):
            diearea = tuple(int(m.group(i)) for i in range(1, 5))  # type: ignore[assignment]

    in_components = False
    buffer = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("COMPONENTS "):
            in_components = True
            continue
        if in_components and stripped == "END COMPONENTS":
            in_components = False
            buffer = ""
            continue
        if not in_components:
            continue
        if stripped.startswith("-"):
            buffer = stripped
        elif buffer:
            buffer += " " + stripped
        if buffer and ";" in stripped:
            m = COMP_RE.search(buffer)
            if m:
                instance = m.group("instance")
                if instance in components:
                    raise ConfigError(f"DEF contains duplicate component instance {instance!r}")
                components[instance] = DefComponent(
                    instance=instance,
                    macro=m.group("macro"),
                    x=int(m.group("x")),
                    y=int(m.group("y")),
                    orientation=m.group("orient"),
                    placement=m.group("placement"),
                )
            buffer = ""

    in_pins = False
    buffer = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("PINS "):
            in_pins = True
            continue
        if in_pins and stripped == "END PINS":
            in_pins = False
            buffer = ""
            continue
        if not in_pins:
            continue
        if stripped.startswith("-"):
            if buffer:
                raise ConfigError("unterminated DEF pin entry")
            buffer = stripped
        elif buffer:
            buffer += " " + stripped
        if buffer and stripped.endswith(";"):
            pin = _parse_pin_entry(buffer)
            if pin.name in pins:
                raise ConfigError(f"DEF contains duplicate pin {pin.name!r}")
            pins[pin.name] = pin
            buffer = ""

    return DefDesign(name, units, diearea, components, pins)


def load_def(path: Path) -> DefDesign:
    try:
        return parse_def_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read DEF {path}: {exc}") from exc
