from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .constants import CELL_PROJECT_TERMINALS
from .defparse import load_def
from .errors import ConfigError
from .lef import parse_lef_files, validate_project_terminals
from .padring_cfg import safe_identifier
from .virtual_def import _absolute_rect, load_mapping


def _canonical_pins(mapping: dict[str, Any], def_path: Path, lef_paths: list[Path]):
    design = load_def(def_path)
    macros = parse_lef_files(lef_paths)
    cells = [p.get("cell") for p in mapping["pads"] if isinstance(p, dict) and not p.get("generated")]
    missing = validate_project_terminals(macros, [c for c in cells if isinstance(c, str)])
    if missing:
        raise ConfigError(f"LEF inputs do not contain required project-facing terminals: {missing}")

    pins = []
    for pad in mapping["pads"]:
        if not isinstance(pad, dict) or pad.get("generated"):
            continue
        slot, cell = pad.get("slot"), pad.get("cell")
        if not isinstance(slot, str) or not isinstance(cell, str):
            raise ConfigError(f"invalid mapping entry: {pad!r}")
        terminals = CELL_PROJECT_TERMINALS.get(cell)
        if terminals is None:
            continue
        comp = design.components.get(slot)
        if comp is None or comp.macro != cell:
            raise ConfigError(f"padring DEF does not contain canonical component {slot!r} using {cell!r}")
        macro = macros[cell]
        for terminal in terminals:
            lef_pin = macro.pins[terminal]
            if not lef_pin.rects:
                raise ConfigError(f"LEF macro {cell} pin {terminal} has no RECT geometry")
            pins.append({
                "name": safe_identifier(f"{slot}_{terminal}"),
                "slot": slot,
                "cell": cell,
                "terminal": terminal,
                "direction": lef_pin.direction or "INOUT",
                "rects": [_absolute_rect(r, macro, comp, design.units) for r in lef_pin.rects],
            })
    return design, pins


def add_canonical_pins_to_def(def_path: Path, mapping_path: Path, lef_paths: list[Path]) -> None:
    mapping = load_mapping(mapping_path)
    _design, pins = _canonical_pins(mapping, def_path, lef_paths)
    text = def_path.read_text(encoding="utf-8")
    if "END PINS" in text:
        raise ConfigError(f"padring DEF already contains a PINS section: {def_path}")
    lines = [f"PINS {len(pins)} ;"]
    for pin in pins:
        name = pin["name"]
        lines.append(f"- {name} + NET {name} + DIRECTION {pin['direction']} + USE SIGNAL")
        for rect in pin["rects"]:
            lines.append(f"  + LAYER {rect.layer} ( {rect.x1} {rect.y1} ) ( {rect.x2} {rect.y2} )")
        lines.append("  + FIXED ( 0 0 ) N ;")
    lines.append("END PINS")
    marker = "END DESIGN"
    if marker not in text:
        raise ConfigError(f"padring DEF has no END DESIGN statement: {def_path}")
    def_path.write_text(text.replace(marker, "\n".join(lines) + "\n" + marker, 1), encoding="utf-8")


def write_canonical_verilog(
    output_path: Path, def_path: Path, mapping_path: Path, lef_paths: list[Path]
) -> None:
    mapping = load_mapping(mapping_path)
    design, pins = _canonical_pins(mapping, def_path, lef_paths)
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for pin in pins:
        by_slot.setdefault(pin["slot"], []).append(pin)
    lines = [f"module {safe_identifier(design.name)} ("]
    lines.extend(f"    {pin['name']}{',' if i + 1 < len(pins) else ''}" for i, pin in enumerate(pins))
    lines.append(");")
    for pin in pins:
        direction = str(pin["direction"]).lower()
        lines.append(f"  {direction} {pin['name']};")
    lines.append("")
    for slot, comp in design.components.items():
        if re.fullmatch(r"[NESW]\d{2}", slot) is None:
            continue
        slot_pins = by_slot.get(slot, [])
        connections = ", ".join(f".{p['terminal']}({p['name']})" for p in slot_pins)
        lines.append(f"  {comp.macro} {slot} ({connections});")
    lines.extend(["endmodule", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")
