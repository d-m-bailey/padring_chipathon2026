from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import yaml

from .constants import CELL_PROJECT_TERMINALS, GROUND_CELL, POWER_CELL, SPEC_BLOB_SHA
from .defparse import DefComponent, DefPin, DefRect, load_def
from .errors import ConfigError
from .lef import LefMacro, LefPin, LefRect, parse_lef_files
from .padring_cfg import safe_identifier


GF180_ROUTING_LAYERS = ("Metal1", "Metal2", "Metal3", "Metal4", "Metal5")


@dataclass(frozen=True)
class BlockVariant:
    code: str
    slots: tuple[str, ...]
    origin: tuple[Decimal, Decimal]
    width: Decimal
    height: Decimal
    area: int
    vss_fixed: tuple[str, ...] = ()
    blockages: tuple[tuple[Decimal, Decimal, Decimal, Decimal], ...] = ()


def _slots(*ranges: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in ranges:
        side = value[0]
        start, end = (int(part[1:]) for part in value.split("-"))
        step = 1 if end >= start else -1
        result.extend(f"{side}{number:02d}" for number in range(start, end + step, step))
    return tuple(result)


BLOCK_VARIANTS = {
    v.code: v
    for v in (
        BlockVariant("A", _slots("W12-W22", "N01-N11"), (Decimal(350), Decimal(1475)), Decimal(1110), Decimal(1110), 1_232_100, ("W12",)),
        BlockVariant("BV", _slots("W12-W22", "N01-N05"), (Decimal(350), Decimal(1475)), Decimal(550), Decimal(1110), 610_500, ("W12",)),
        BlockVariant("BH", _slots("W18-W22", "N01-N11"), (Decimal(350), Decimal(2035)), Decimal(1110), Decimal(550), 610_500),
        BlockVariant("CH", _slots("W12-W17"), (Decimal(350), Decimal(1475)), Decimal(1110), Decimal(550), 610_500, ("W12",)),
        BlockVariant("CV", _slots("N06-N11"), (Decimal(910), Decimal(1475)), Decimal(550), Decimal(1110), 610_500),
        BlockVariant("D", _slots("W18-W22", "N01-N05"), (Decimal(350), Decimal(2035)), Decimal(550), Decimal(550), 302_500),
        BlockVariant("EV", _slots("N06-N11"), (Decimal(910), Decimal(2035)), Decimal(550), Decimal(550), 302_500),
        BlockVariant("EH", _slots("W12-W17"), (Decimal(350), Decimal(1475)), Decimal(550), Decimal(550), 302_500, ("W12",)),
        BlockVariant("ACV", _slots("W12-W22", "N01-N16"), (Decimal(350), Decimal(1475)), Decimal(1675), Decimal(1110), 1_859_250, ("W12",)),
        BlockVariant("ACH", _slots("W07-W22", "N01-N11"), (Decimal(350), Decimal(910)), Decimal(1110), Decimal(1675), 1_859_250, ("W11", "W12")),
        BlockVariant("ACE", _slots("W07-W22", "N01-N16"), (Decimal(350), Decimal(910)), Decimal(1675), Decimal(1675), 2_805_625, ("W11", "W12")),
        BlockVariant(
            "ACE2", _slots("W07-W22", "N01-N16", "E16-E01", "S22-S07"),
            (Decimal(350), Decimal(350)), Decimal(2235), Decimal(2235), 5_308_750,
            ("W11", "W12", "E11", "E12"),
            ((Decimal(0), Decimal(0), Decimal(560), Decimal(560)),
             (Decimal(1675), Decimal(1675), Decimal(2235), Decimal(2235))),
        ),
    )
}


@dataclass(frozen=True)
class ProjectRect:
    layer: str
    top: DefRect
    extended: DefRect
    local: DefRect


def _transform_point(x: float, y: float, w: float, h: float, orient: str) -> tuple[float, float]:
    transforms = {
        "N": (x, y), "S": (w - x, h - y), "W": (h - y, x), "E": (y, w - x),
        "FN": (w - x, y), "FS": (x, h - y), "FE": (h - y, w - x), "FW": (y, x),
    }
    try:
        return transforms[orient]
    except KeyError as exc:
        raise ConfigError(f"unsupported DEF orientation {orient!r}") from exc


def _absolute_rect(rect: LefRect, macro: LefMacro, comp: DefComponent, units: int) -> DefRect:
    coords = []
    for x, y in ((rect.x1, rect.y1), (rect.x1, rect.y2), (rect.x2, rect.y1), (rect.x2, rect.y2)):
        tx, ty = _transform_point(x - macro.origin_x, y - macro.origin_y, macro.width, macro.height, comp.orientation)
        coords.append((comp.x + round(tx * units), comp.y + round(ty * units)))
    xs, ys = [point[0] for point in coords], [point[1] for point in coords]
    return DefRect(rect.layer, min(xs), min(ys), max(xs), max(ys))


def _decimal(value: Decimal | str | int | float, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ConfigError(f"{name} must be a decimal micron value") from exc
    if not result.is_finite():
        raise ConfigError(f"{name} must be a finite decimal micron value")
    return result


def micron_to_dbu(value: Decimal | str | int | float, units: int, name: str) -> int:
    scaled = _decimal(value, name) * units
    if scaled != scaled.to_integral_value():
        raise ConfigError(f"{name}={value} microns is not exactly representable with DEF units {units}")
    return int(scaled)


def select_block_variants(
    *, project_width: Decimal | str | int | float,
    project_height: Decimal | str | int | float,
    pin_count: int,
) -> tuple[BlockVariant, ...]:
    width, height = _decimal(project_width, "project width"), _decimal(project_height, "project height")
    if width <= 0 or height <= 0 or pin_count < 0:
        raise ConfigError("project width and height must be positive and pin count must be non-negative")
    fitting = [
        variant for variant in BLOCK_VARIANTS.values()
        if width <= variant.width
        and height <= variant.height
        and pin_count <= len(variant.slots) - len(variant.vss_fixed)
    ]
    if not fitting:
        raise ConfigError(f"no block variant fits {width} x {height} microns and {pin_count} pins")
    minimum_area = min(variant.area for variant in fitting)
    return tuple(variant for variant in fitting if variant.area == minimum_area)


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read mapping {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pads"), list):
        raise ConfigError("mapping YAML must contain a pads list")
    return data


def mapped_pads(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    pads = [pad for pad in mapping["pads"] if isinstance(pad, dict) and not pad.get("generated")]
    try:
        indexed = [(int(pad["pin_index"]), pad) for pad in pads]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("every mapped participant pad must have an integer pin_index") from exc
    indexes = [item[0] for item in indexed]
    if len(indexes) != len(set(indexes)):
        raise ConfigError("mapping contains duplicate participant pin_index values")
    return [item[1] for item in sorted(indexed)]


def _lef_terminal(macros: dict[str, LefMacro], cell: str, terminal: str) -> LefPin:
    macro = macros.get(cell)
    if macro is None:
        raise ConfigError(f"LEF macro {cell!r} not found")
    pin = macro.pins.get(terminal)
    if pin is None or not pin.rects:
        raise ConfigError(f"LEF macro {cell} pin {terminal} has no RECT geometry")
    return pin


def _select_source_rects(source: DefPin, lef_pin: LefPin, *, metal2_only: bool = False) -> tuple[DefRect, ...]:
    layers = {rect.layer for rect in lef_pin.rects}
    if metal2_only:
        layers = {"Metal2"}
    rects = tuple(rect for rect in source.rects if rect.layer in layers)
    if not rects:
        wanted = "Metal2" if metal2_only else ", ".join(sorted(layers))
        raise ConfigError(f"padring DEF pin {source.name!r} has no required geometry on {wanted}")
    return rects


def _extend_and_translate(
    rects: Iterable[DefRect], *, slot: str, origin: tuple[int, int],
    size: tuple[int, int], extension: int,
) -> tuple[ProjectRect, ...]:
    rects = tuple(rects)
    side = slot[0]
    boundaries = {
        "W": {rect.x2 for rect in rects}, "E": {rect.x1 for rect in rects},
        "N": {rect.y1 for rect in rects}, "S": {rect.y2 for rect in rects},
    }[side]
    if len(boundaries) != 1:
        raise ConfigError(
            f"project-facing geometry for {slot} is ambiguous: expected one shared {side}-side boundary, found {sorted(boundaries)}"
        )
    boundary = next(iter(boundaries))
    expected_boundary = {
        "W": origin[0], "E": origin[0] + size[0],
        "N": origin[1] + size[1], "S": origin[1],
    }[side]
    if boundary != expected_boundary:
        raise ConfigError(
            f"project-facing boundary for {slot} is {boundary}, expected block boundary {expected_boundary}"
        )
    output = []
    ox, oy = origin
    width, height = size
    for rect in rects:
        values = [rect.x1, rect.y1, rect.x2, rect.y2]
        if side == "W":
            values[0], values[2] = boundary, boundary + extension
        elif side == "E":
            values[0], values[2] = boundary - extension, boundary
        elif side == "N":
            values[1], values[3] = boundary - extension, boundary
        else:
            values[1], values[3] = boundary, boundary + extension
        extended = DefRect(rect.layer, *values)
        local = DefRect(rect.layer, values[0] - ox, values[1] - oy, values[2] - ox, values[3] - oy)
        if local.x1 < 0 or local.y1 < 0 or local.x2 > width or local.y2 > height:
            raise ConfigError(
                f"translated geometry for {slot} lies outside user block (0,0)-({width},{height}): {local}"
            )
        output.append(ProjectRect(rect.layer, rect, extended, local))
    return tuple(output)


def _invert_direction(direction: str | None) -> str:
    value = (direction or "INOUT").upper()
    return {"INPUT": "OUTPUT", "OUTPUT": "INPUT"}.get(value, value)


def _project_terminal_name(io_type: str, user_name: str, terminal: str) -> str:
    base_name = safe_identifier(user_name)
    if io_type in {"input_cmos", "input_schmitt"} and terminal == "Y":
        return base_name
    if io_type in {"bidirectional", "bidirectional_24ma"}:
        if terminal == "Y":
            return f"{base_name}_IN"
        if terminal == "A":
            return f"{base_name}_OUT"
    return f"{base_name}_{terminal}"


def _rect_list(rect: DefRect) -> list[int]:
    return [rect.x1, rect.y1, rect.x2, rect.y2]


def generate_project_def(
    *, mapping_path: Path, padring_def: Path, lef_paths: list[Path],
    variant_code: str, design_name: str = "chipathon_project_interface",
    routing_layers: tuple[str, ...] = GF180_ROUTING_LAYERS,
) -> tuple[str, dict[str, Any]]:
    try:
        variant = BLOCK_VARIANTS[variant_code.upper()]
    except KeyError as exc:
        raise ConfigError(f"unknown block variant {variant_code!r}") from exc
    mapping = load_mapping(mapping_path)
    pads = mapped_pads(mapping)
    if not routing_layers or any(not layer.strip() for layer in routing_layers):
        raise ConfigError("at least one non-empty routing blockage layer is required")
    if len(routing_layers) != len(set(routing_layers)):
        raise ConfigError("routing blockage layer names must be unique")
    capacity = len(variant.slots) - len(variant.vss_fixed)
    if len(pads) > capacity:
        raise ConfigError(f"variant {variant.code} has {capacity} participant pin sites but mapping contains {len(pads)} pins")

    design = load_def(padring_def)
    macros = parse_lef_files(lef_paths)
    origin = tuple(micron_to_dbu(v, design.units, f"{variant.code} origin") for v in variant.origin)
    size = (
        micron_to_dbu(variant.width, design.units, f"{variant.code} width"),
        micron_to_dbu(variant.height, design.units, f"{variant.code} height"),
    )
    extension = micron_to_dbu(Decimal("1.0"), design.units, "pin extension")

    pin_defs: list[dict[str, Any]] = []
    names: set[str] = set()
    previous_slot_index = -1
    for index, pad in enumerate(pads):
        cell, instance, user_name, slot = (pad.get(key) for key in ("cell", "instance", "pin_name", "slot"))
        if not all(isinstance(value, str) for value in (cell, instance, user_name, slot)):
            raise ConfigError(f"invalid mapping entry: {pad!r}")
        if instance != slot or slot not in variant.slots:
            raise ConfigError(
                f"mapping pin {index} uses {slot!r}/{instance!r}, which is not a canonical slot in variant {variant.code}"
            )
        slot_index = variant.slots.index(slot)
        if slot_index <= previous_slot_index:
            raise ConfigError(f"mapping slots do not follow the authoritative {variant.code} pin order")
        previous_slot_index = slot_index
        component = design.components.get(instance)
        if component is None:
            raise ConfigError(f"padring DEF is missing mapped component instance {instance!r}")
        if component.macro != cell:
            raise ConfigError(f"padring DEF component {instance!r} uses {component.macro!r}, expected {cell!r}")

        io_type = pad.get("io_type")
        if io_type == "analog":
            terminals = (("ASIG5V", user_name, f"{slot}_ASIG5V", True),)
        elif io_type == "power" or cell == POWER_CELL:
            terminals = (("DVDD", user_name, slot, True),)
        elif io_type == "ground" or cell == GROUND_CELL:
            terminals = (("DVSS", user_name, slot, True),)
        else:
            cell_terminals = CELL_PROJECT_TERMINALS.get(cell)
            if cell_terminals is None:
                raise ConfigError(f"no project-facing terminal policy for cell {cell!r}")
            terminals = tuple(
                (
                    terminal,
                    _project_terminal_name(str(io_type), user_name, terminal),
                    f"{slot}_{terminal}",
                    False,
                )
                for terminal in cell_terminals
            )

        for terminal, raw_name, source_name, metal2_only in terminals:
            lef_pin = _lef_terminal(macros, cell, terminal)
            source = design.pins.get(source_name)
            if source is None:
                raise ConfigError(f"padring DEF is missing required pin geometry {source_name!r}")
            rects = _select_source_rects(source, lef_pin, metal2_only=metal2_only)
            transformed = _extend_and_translate(rects, slot=slot, origin=origin, size=size, extension=extension)
            out_name = safe_identifier(raw_name)
            if out_name in names:
                raise ConfigError(f"duplicate generated project pin name {out_name!r}")
            names.add(out_name)
            pin_defs.append({
                "name": out_name, "user_pin_name": user_name, "terminal": terminal,
                "slot": slot, "instance": instance, "cell": cell,
                "direction": _invert_direction(lef_pin.direction or source.direction),
                "use": lef_pin.use or source.use, "rects": transformed,
            })

    lines = [
        "VERSION 5.8 ;", 'DIVIDERCHAR "/" ;', 'BUSBITCHARS "[]" ;',
        f"DESIGN {safe_identifier(design_name)} ;",
        f"UNITS DISTANCE MICRONS {design.units} ;",
        f"DIEAREA ( 0 0 ) ( {size[0]} {size[1]} ) ;",
        f"PINS {len(pin_defs)} ;",
    ]
    for pin in pin_defs:
        lines.append(f"- {pin['name']} + NET {pin['name']} + DIRECTION {pin['direction']} + USE {pin['use']}")
        for item in pin["rects"]:
            rect = item.local
            lines.append(f"  + LAYER {rect.layer} ( {rect.x1} {rect.y1} ) ( {rect.x2} {rect.y2} )")
        lines.append("  + FIXED ( 0 0 ) N ;")
    lines.append("END PINS")

    blockage_rects = [
        tuple(micron_to_dbu(value, design.units, f"{variant.code} blockage") for value in rect)
        for rect in variant.blockages
    ]
    blockage_count = len(blockage_rects) * (1 + len(routing_layers))
    if blockage_count:
        lines.append(f"BLOCKAGES {blockage_count} ;")
        for x1, y1, x2, y2 in blockage_rects:
            lines.append(f"- PLACEMENT + RECT ( {x1} {y1} ) ( {x2} {y2} ) ;")
            for layer in routing_layers:
                lines.append(f"- LAYER {layer} + RECT ( {x1} {y1} ) ( {x2} {y2} ) ;")
        lines.append("END BLOCKAGES")
    lines.extend(["END DESIGN", ""])

    metadata = {
        "spec_blob_sha": SPEC_BLOB_SHA, "source_mapping": str(mapping_path),
        "source_padring_def": str(padring_def), "variant": variant.code,
        "origin_microns": [str(v) for v in variant.origin], "origin_dbu": list(origin),
        "size_microns": [str(variant.width), str(variant.height)], "diearea_dbu": [0, 0, *size],
        "usable_area": variant.area, "vss_fixed": list(variant.vss_fixed),
        "blockages": [list(rect) for rect in blockage_rects],
        "routing_blockage_layers": list(routing_layers),
        "pins": [
            {
                "user_pin_name": pin["user_pin_name"], "project_pin": pin["name"],
                "cell_terminal": pin["terminal"], "padring_instance": pin["instance"],
                "physical_pad_slot": pin["slot"], "cell": pin["cell"],
                "direction": pin["direction"], "use": pin["use"],
                "rectangles": [
                    {"routing_layer": item.layer, "top_level": _rect_list(item.top),
                     "extended_top_level": _rect_list(item.extended), "translated_user": _rect_list(item.local)}
                    for item in pin["rects"]
                ],
            }
            for pin in pin_defs
        ],
    }
    return "\n".join(lines), metadata
