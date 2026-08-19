from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .constants import (
    ALL_PHYSICAL_SLOTS,
    CELL_PORTS,
    CELL_PROJECT_TERMINALS,
    GROUND_CELL,
    POWER_CELL,
)
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
                "use": lef_pin.use or "SIGNAL",
                "rects": [_absolute_rect(r, macro, comp, design.units) for r in lef_pin.rects],
            })
    return design, pins


def add_canonical_pins_to_def(def_path: Path, mapping_path: Path, lef_paths: list[Path]) -> None:
    mapping = load_mapping(mapping_path)
    design, pins = _canonical_pins(mapping, def_path, lef_paths)
    macros = parse_lef_files(lef_paths)
    pad_rects = None
    for macro in macros.values():
        if "PAD" in macro.pins:
            candidate = [rect for rect in macro.pins["PAD"].rects if rect.layer == "Metal5"]
            if candidate:
                pad_rects = candidate
                break
    if not pad_rects:
        raise ConfigError("LEF inputs contain no Metal5 PAD geometry for canonical physical pins")

    physical_pins = []
    for slot in ALL_PHYSICAL_SLOTS:
        comp = design.components.get(slot)
        if comp is None:
            raise ConfigError(f"padring DEF is missing canonical component {slot!r}")
        macro = macros.get(comp.macro)
        if macro is None:
            raise ConfigError(f"LEF macro {comp.macro!r} not found")
        rects = [_absolute_rect(rect, macro, comp, design.units) for rect in pad_rects]
        use = "SIGNAL"
        if comp.macro == POWER_CELL:
            terminal, use = "DVDD", "POWER"
        elif comp.macro == GROUND_CELL:
            terminal, use = "DVSS", "GROUND"
        else:
            terminal = None
        if terminal is not None:
            metal2 = [rect for rect in macro.pins[terminal].rects if rect.layer == "Metal2"]
            if not metal2:
                raise ConfigError(f"LEF macro {comp.macro} pin {terminal} has no Metal2 geometry")
            rects.extend(_absolute_rect(rect, macro, comp, design.units) for rect in metal2)
        physical_pins.append({
            "name": slot,
            "direction": "INOUT",
            "use": use,
            "rects": rects,
        })
    pins = physical_pins + pins
    text = def_path.read_text(encoding="utf-8")
    if "END PINS" in text:
        raise ConfigError(f"padring DEF already contains a PINS section: {def_path}")
    lines = [f"PINS {len(pins)} ;"]
    for pin in pins:
        name = pin["name"]
        lines.append(
            f"- {name} + NET {name} + DIRECTION {pin['direction']} + USE {pin['use']}"
        )
        for rect in pin["rects"]:
            lines.append(f"  + LAYER {rect.layer} ( {rect.x1} {rect.y1} ) ( {rect.x2} {rect.y2} )")
        lines.append("  + FIXED ( 0 0 ) N ;")
    lines.append("END PINS")
    marker = "END DESIGN"
    if marker not in text:
        raise ConfigError(f"padring DEF has no END DESIGN statement: {def_path}")
    def_path.write_text(text.replace(marker, "\n".join(lines) + "\n" + marker, 1), encoding="utf-8")


def write_canonical_verilog(
    output_path: Path,
    def_path: Path,
    mapping_path: Path,
    cfg_path: Path,
    lef_paths: list[Path],
) -> None:
    mapping = load_mapping(mapping_path)
    design, pins = _canonical_pins(mapping, def_path, lef_paths)
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for pin in pins:
        by_slot.setdefault(pin["slot"], []).append(pin)
    break_edges: set[frozenset[str]] = set()
    side_slots: dict[str, list[str]] = {side: [] for side in "NESW"}
    previous: str | None = None
    pending_break = False
    for raw in cfg_path.read_text(encoding="utf-8").splitlines():
        words = raw.split("#", 1)[0].split()
        if words[:1] == ["PAD"] and len(words) >= 4 and re.fullmatch(r"[NESW]\d{2}", words[1]):
            slot, side = words[1], words[2]
            side_slots[side].append(slot)
            if pending_break and previous is not None:
                break_edges.add(frozenset((previous, slot)))
            previous, pending_break = slot, False
        elif words[:1] == ["BREAK"]:
            pending_break = True

    graph: dict[str, set[str]] = {slot: set() for slot in ALL_PHYSICAL_SLOTS}
    physical_edges = []
    for slots in side_slots.values():
        physical_edges.extend(zip(slots, slots[1:]))
    physical_edges.extend((("N01", "W22"), ("N22", "E22"), ("E01", "S22"), ("S01", "W01")))
    for left, right in physical_edges:
        if frozenset((left, right)) not in break_edges:
            graph[left].add(right)
            graph[right].add(left)

    segment_net: dict[str, str] = {}
    unpowered_segment_ports: set[str] = set()
    remaining = set(graph)
    while remaining:
        seed = next(iter(remaining))
        component = set()
        stack = [seed]
        while stack:
            slot = stack.pop()
            if slot in component:
                continue
            component.add(slot)
            stack.extend(graph[slot] - component)
        remaining -= component
        power_slots = sorted(
            slot for slot in component
            if slot in design.components and design.components[slot].macro == POWER_CELL
        )
        if len(power_slots) > 1:
            raise ConfigError(
                "internal power-topology error: DVDD pads inherently break the VDD/DVDD rails, "
                f"but topology component {sorted(component)} contains {power_slots}"
            )
        if power_slots:
            net = power_slots[0]
        else:
            net = f"{sorted(component)[0]}_DVDD"
            unpowered_segment_ports.add(net)
        segment_net.update({slot: net for slot in component})

    ground_slots = sorted(
        slot for slot in ALL_PHYSICAL_SLOTS
        if slot in design.components and design.components[slot].macro == GROUND_CELL
    )
    if not ground_slots:
        raise ConfigError("padring contains no canonical DVSS pad")
    ground_net = ground_slots[0]

    physical_ports = list(ALL_PHYSICAL_SLOTS) + sorted(unpowered_segment_ports)
    port_names = physical_ports + [pin["name"] for pin in pins]
    lines = [f"module {safe_identifier(design.name)} ("]
    lines.extend(f"    {name}{',' if i + 1 < len(port_names) else ''}" for i, name in enumerate(port_names))
    lines.append(");")
    for name in physical_ports:
        lines.append(f"  inout {name};")
    for pin in pins:
        direction = str(pin["direction"]).lower()
        lines.append(f"  {direction} {pin['name']};")
    lines.append("")
    for ground_slot in ground_slots[1:]:
        lines.append(f"  assign {ground_slot} = {ground_net};")
    lines.append("")
    macros = parse_lef_files(lef_paths)
    for slot, comp in design.components.items():
        if re.fullmatch(r"[NESW]\d{2}", slot) is None:
            continue
        slot_pins = by_slot.get(slot, [])
        connection_map = {p["terminal"]: p["name"] for p in slot_pins}
        ports = CELL_PORTS.get(comp.macro, ())
        if "PAD" in ports:
            connection_map["PAD"] = slot
        elif "ASIG5V" in ports:
            if "ASIG5V" in connection_map:
                lines.append(f"  assign {connection_map['ASIG5V']} = {slot};")
            connection_map["ASIG5V"] = slot
        if comp.macro == POWER_CELL:
            connection_map["DVDD"] = slot
        if comp.macro == GROUND_CELL:
            connection_map["DVSS"] = slot
        for terminal in ("VSS", "DVSS"):
            if terminal in ports and terminal not in connection_map:
                connection_map[terminal] = ground_net
        for terminal in ("VDD", "DVDD"):
            if terminal in ports and terminal not in connection_map:
                connection_map[terminal] = segment_net[slot]
        connections = ", ".join(f".{terminal}({net})" for terminal, net in connection_map.items())
        lines.append(f"  {comp.macro} {slot} ({connections});")

    pad_components = {
        slot: design.components[slot]
        for slot in ALL_PHYSICAL_SLOTS
        if slot in design.components
    }
    for instance, comp in design.components.items():
        if instance in pad_components:
            continue
        macro = macros.get(comp.macro)
        if macro is None:
            raise ConfigError(f"LEF macro {comp.macro!r} not found for component {instance!r}")
        nearest_slot = min(
            pad_components,
            key=lambda slot: (
                (pad_components[slot].x - comp.x) ** 2
                + (pad_components[slot].y - comp.y) ** 2
            ),
        )
        connection_map = {}
        if "VSS" in macro.pins:
            connection_map["VSS"] = ground_net
        if "DVSS" in macro.pins:
            connection_map["DVSS"] = ground_net
        if "VDD" in macro.pins:
            connection_map["VDD"] = segment_net[nearest_slot]
        if "DVDD" in macro.pins:
            connection_map["DVDD"] = segment_net[nearest_slot]
        connections = ", ".join(f".{terminal}({net})" for terminal, net in connection_map.items())
        lines.append(f"  {comp.macro} {instance} ({connections});")
    lines.extend(["endmodule", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")
