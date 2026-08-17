from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .constants import CELL_PROJECT_TERMINALS
from .errors import ConfigError


@dataclass(frozen=True)
class LefRect:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class LefPin:
    name: str
    direction: str | None = None
    use: str | None = None
    rects: list[LefRect] = field(default_factory=list)


@dataclass
class LefMacro:
    name: str
    width: float = 0.0
    height: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    pins: dict[str, LefPin] = field(default_factory=dict)


MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)")
PIN_RE = re.compile(r"^\s*PIN\s+(\S+)")
SIZE_RE = re.compile(r"^\s*SIZE\s+([-+0-9.eE]+)\s+BY\s+([-+0-9.eE]+)\s*;")
ORIGIN_RE = re.compile(r"^\s*ORIGIN\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*;")
DIRECTION_RE = re.compile(r"^\s*DIRECTION\s+(\S+)\s*;")
USE_RE = re.compile(r"^\s*USE\s+(\S+)\s*;")
LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;")
RECT_RE = re.compile(r"^\s*RECT\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*;")
END_RE = re.compile(r"^\s*END\s+(\S+)")


def parse_lef_text(text: str) -> dict[str, LefMacro]:
    macros: dict[str, LefMacro] = {}
    macro: LefMacro | None = None
    pin: LefPin | None = None
    layer: str | None = None

    for raw in text.splitlines():
        if macro is None:
            m = MACRO_RE.match(raw)
            if m:
                macro = LefMacro(m.group(1))
                if macro.name in macros:
                    raise ConfigError(f"duplicate LEF macro {macro.name}")
                macros[macro.name] = macro
            continue

        if pin is None:
            if m := SIZE_RE.match(raw):
                macro.width, macro.height = float(m.group(1)), float(m.group(2))
                continue
            if m := ORIGIN_RE.match(raw):
                macro.origin_x, macro.origin_y = float(m.group(1)), float(m.group(2))
                continue
            if m := PIN_RE.match(raw):
                pin = LefPin(m.group(1))
                macro.pins[pin.name] = pin
                layer = None
                continue
            if (m := END_RE.match(raw)) and m.group(1) == macro.name:
                macro = None
                continue
        else:
            if m := DIRECTION_RE.match(raw):
                pin.direction = m.group(1).upper()
                continue
            if m := USE_RE.match(raw):
                pin.use = m.group(1).upper()
                continue
            if m := LAYER_RE.match(raw):
                layer = m.group(1)
                continue
            if m := RECT_RE.match(raw):
                if layer is not None:
                    pin.rects.append(LefRect(layer, *(float(m.group(i)) for i in range(1, 5))))
                continue
            if (m := END_RE.match(raw)) and m.group(1) == pin.name:
                pin = None
                layer = None
                continue

    return macros


def parse_lef_files(paths: Iterable[Path]) -> dict[str, LefMacro]:
    macros: dict[str, LefMacro] = {}
    for path in paths:
        try:
            parsed = parse_lef_text(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"cannot read LEF {path}: {exc}") from exc
        for name, macro in parsed.items():
            if name in macros:
                raise ConfigError(f"LEF macro {name} appears in more than one input file")
            macros[name] = macro
    return macros


def validate_project_terminals(macros: dict[str, LefMacro], cells: Iterable[str]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for cell in sorted(set(cells)):
        expected = CELL_PROJECT_TERMINALS.get(cell)
        if expected is None:
            continue
        macro = macros.get(cell)
        if macro is None:
            missing[cell] = ["<macro missing>"]
            continue
        absent = [terminal for terminal in expected if terminal not in macro.pins]
        if absent:
            missing[cell] = absent
    return missing
