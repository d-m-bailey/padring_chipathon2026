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


@dataclass
class DefDesign:
    name: str
    units: int
    diearea: tuple[int, int, int, int] | None
    components: dict[str, DefComponent]


DESIGN_RE = re.compile(r"^\s*DESIGN\s+(\S+)\s*;")
UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;")
DIEAREA_RE = re.compile(r"^\s*DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;")
COMP_RE = re.compile(
    r"-\s+(?P<instance>\S+)\s+(?P<macro>\S+).*?\+\s+"
    r"(?P<placement>FIXED|PLACED|COVER)\s+\(\s*(?P<x>-?\d+)\s+(?P<y>-?\d+)\s*\)\s+"
    r"(?P<orient>N|S|E|W|FN|FS|FE|FW)\b",
    re.S,
)


def parse_def_text(text: str) -> DefDesign:
    name = "project"
    units = 1000
    diearea = None
    components: dict[str, DefComponent] = {}

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

    return DefDesign(name, units, diearea, components)


def load_def(path: Path) -> DefDesign:
    try:
        return parse_def_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read DEF {path}: {exc}") from exc
