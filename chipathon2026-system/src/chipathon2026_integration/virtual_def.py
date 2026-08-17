from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .constants import CELL_PROJECT_TERMINALS, SPEC_BLOB_SHA
from .defparse import DefComponent, load_def
from .errors import ConfigError, NotFinalizedError
from .lef import LefMacro, LefRect, parse_lef_files, validate_project_terminals
from .padring_cfg import safe_identifier


@dataclass(frozen=True)
class AbsRect:
    layer: str
    x1: int
    y1: int
    x2: int
    y2: int


def _transform_point(x: float, y: float, w: float, h: float, orient: str) -> tuple[float, float]:
    # LEF/DEF standard orientation matrices, translated to a positive macro bbox.
    if orient == "N":
        return x, y
    if orient == "S":
        return w - x, h - y
    if orient == "W":
        return h - y, x
    if orient == "E":
        return y, w - x
    if orient == "FN":
        return w - x, y
    if orient == "FS":
        return x, h - y
    if orient == "FW":
        return h - y, w - x
    if orient == "FE":
        return y, x
    raise ConfigError(f"unsupported DEF orientation {orient!r}")


def _absolute_rect(rect: LefRect, macro: LefMacro, comp: DefComponent, units: int) -> AbsRect:
    coords = []
    for x, y in ((rect.x1, rect.y1), (rect.x1, rect.y2), (rect.x2, rect.y1), (rect.x2, rect.y2)):
        x -= macro.origin_x
        y -= macro.origin_y
        tx, ty = _transform_point(x, y, macro.width, macro.height, comp.orientation)
        coords.append((comp.x + round(tx * units), comp.y + round(ty * units)))
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return AbsRect(rect.layer, min(xs), min(ys), max(xs), max(ys))


def _invert_direction(direction: str | None) -> str:
    if direction == "INPUT":
        return "OUTPUT"
    if direction == "OUTPUT":
        return "INPUT"
    if direction == "INOUT":
        return "INOUT"
    return "INOUT"


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read mapping {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pads"), list):
        raise ConfigError("mapping YAML must contain a pads list")
    return data


def generate_virtual_def(
    *,
    mapping_path: Path,
    padring_def: Path,
    lef_paths: list[Path],
    diearea: tuple[int, int, int, int] | None,
    design_name: str = "chipathon_project_interface",
) -> tuple[str, dict[str, Any]]:
    """Generate a pin-constraint DEF from fixed I/O-cell terminal geometry.

    The live spec does not yet define the canonical project DIEAREA.  Therefore
    callers must supply it explicitly; the tool will not infer a 1/4-die box.
    """
    if diearea is None:
        raise NotFinalizedError(
            "canonical project DIEAREA/floorplan is not finalized; supply --diearea explicitly"
        )

    mapping = load_mapping(mapping_path)
    design = load_def(padring_def)
    macros = parse_lef_files(lef_paths)
    cells = [entry.get("cell") for entry in mapping["pads"] if isinstance(entry, dict) and not entry.get("generated")]
    missing = validate_project_terminals(macros, [cell for cell in cells if isinstance(cell, str)])
    if missing:
        raise ConfigError(f"LEF inputs do not contain required project-facing terminals: {missing}")

    interface: list[dict[str, Any]] = []
    pin_defs: list[tuple[str, str, list[AbsRect]]] = []
    names: set[str] = set()

    for pad in mapping["pads"]:
        if not isinstance(pad, dict) or pad.get("generated"):
            continue
        cell = pad.get("cell")
        instance = pad.get("instance")
        pin_name = pad.get("pin_name")
        if not all(isinstance(v, str) for v in (cell, instance, pin_name)):
            raise ConfigError(f"invalid mapping entry: {pad!r}")
        terminals = CELL_PROJECT_TERMINALS.get(cell)
        if terminals is None:
            # Power/ground participant ownership is explicitly not finalized.
            raise NotFinalizedError(
                f"project-facing terminal policy for cell {cell} is not finalized"
            )
        comp = design.components.get(instance)
        if comp is None:
            raise ConfigError(f"padring DEF is missing mapped component instance {instance!r}")
        if comp.macro != cell:
            raise ConfigError(
                f"padring DEF component {instance!r} uses macro {comp.macro!r}, expected {cell!r}"
            )
        macro = macros.get(cell)
        if macro is None:
            raise ConfigError(f"LEF macro {cell!r} not found")

        for terminal in terminals:
            lef_pin = macro.pins[terminal]
            if not lef_pin.rects:
                raise ConfigError(f"LEF macro {cell} pin {terminal} has no RECT geometry")
            out_name = safe_identifier(f"{pin_name}__{terminal}")
            if out_name in names:
                raise ConfigError(f"duplicate generated project-interface pin name {out_name!r}")
            names.add(out_name)
            rects = [_absolute_rect(rect, macro, comp, design.units) for rect in lef_pin.rects]
            direction = _invert_direction(lef_pin.direction)
            pin_defs.append((out_name, direction, rects))
            interface.append({
                "pin_name": pin_name,
                "pad_instance": instance,
                "cell": cell,
                "cell_terminal": terminal,
                "project_pin": out_name,
                "direction": direction,
                "rectangles": [r.__dict__ for r in rects],
            })

    x1, y1, x2, y2 = diearea
    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        f"DESIGN {safe_identifier(design_name)} ;",
        f"UNITS DISTANCE MICRONS {design.units} ;",
        f"DIEAREA ( {x1} {y1} ) ( {x2} {y2} ) ;",
        f"PINS {len(pin_defs)} ;",
    ]
    for name, direction, rects in pin_defs:
        lines.append(f"- {name} + NET {name} + DIRECTION {direction} + USE SIGNAL")
        for rect in rects:
            # Geometry is absolute because the pin placement origin is fixed at (0,0).
            lines.append(
                f"  + LAYER {rect.layer} ( {rect.x1} {rect.y1} ) ( {rect.x2} {rect.y2} )"
            )
        lines.append("  + FIXED ( 0 0 ) N ;")
    lines.extend(["END PINS", "END DESIGN", ""])

    metadata = {
        "spec_blob_sha": SPEC_BLOB_SHA,
        "source_mapping": str(mapping_path),
        "source_padring_def": str(padring_def),
        "diearea": list(diearea),
        "pins": interface,
    }
    return "\n".join(lines), metadata
