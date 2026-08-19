from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .constants import (
    ALL_PHYSICAL_SLOTS,
    ANALOG_PLACEHOLDER_CELL,
    BLOCK_SLOTS,
    GROUND_CELL,
    IO_CELLS,
    POWER_CELL,
    REQUIRED_TEMPLATE_BREAKS,
    RESERVED_VERTICAL_POWER_GROUND_SLOTS,
    SPEC_BLOB_SHA,
    UNFINALIZED_BLOCKS,
)
from .errors import ConfigError, NotFinalizedError
from .info import validate_pins

PAD_RE = re.compile(
    r"^(?P<indent>\s*)PAD\s+(?P<instance>\S+)\s+(?P<location>[NSEW])\s+"
    r"(?:(?P<flip>FLIP)\s+)?(?P<cell>\S+?)\s*;(?P<trailing>\s*(?:#.*)?)$"
)
PHYSICAL_SLOT_RE = re.compile(r"^[NESW](?:0[1-9]|1[0-9]|2[0-2])$")


@dataclass(frozen=True)
class PadEntry:
    line_index: int
    instance: str
    location: str
    flip: bool
    cell: str


def safe_identifier(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not value:
        value = "pin"
    if value[0].isdigit():
        value = "_" + value
    return value


def parse_pad_entries(lines: list[str]) -> list[PadEntry]:
    result: list[PadEntry] = []
    names: set[str] = set()
    for i, line in enumerate(lines):
        m = PAD_RE.match(line)
        if not m:
            continue
        name = m.group("instance")
        if name in names:
            raise ConfigError(f"template contains duplicate PAD instance name {name!r}")
        names.add(name)
        result.append(PadEntry(i, name, m.group("location"), bool(m.group("flip")), m.group("cell")))
    return result


def read_template(path: Path) -> tuple[str, list[str], list[PadEntry]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    lines = text.splitlines()
    return text, lines, parse_pad_entries(lines)


def audit_physical_template(path: Path) -> dict[str, Any]:
    _text, lines, entries = read_template(path)
    by_name = {entry.instance: entry for entry in entries}
    immutable = {name for name in by_name if PHYSICAL_SLOT_RE.fullmatch(name)}
    missing = [slot for slot in ALL_PHYSICAL_SLOTS if slot not in immutable]
    extra = sorted(immutable - set(ALL_PHYSICAL_SLOTS))
    legacy = sorted(entry.instance for entry in entries if entry.instance not in immutable)
    break_issues: list[str] = []
    found_breaks: list[str] = []
    expected_boundaries = {
        "BRK_W10_W11": ("W10", "W11"), "BRK_W12_W13": ("W12", "W13"),
        "BRK_E10_E11": ("E10", "E11"), "BRK_E12_E13": ("E12", "E13"),
    }
    for name, (before, after) in expected_boundaries.items():
        if before in by_name and after in by_name:
            between = lines[by_name[before].line_index + 1:by_name[after].line_index]
            count = sum(line.strip() == "BREAK ;" for line in between)
            if count == 1:
                found_breaks.append(name)
            else:
                break_issues.append(f"{name} requires exactly one BREAK ; directive")
    total_breaks = sum(line.strip() == "BREAK ;" for line in lines)
    if total_breaks != len(REQUIRED_TEMPLATE_BREAKS):
        break_issues.append(
            f"template contains {total_breaks} BREAK directives; expected {len(REQUIRED_TEMPLATE_BREAKS)}"
        )
    if not any(line.strip().startswith("BREAKFILLER ") for line in lines):
        break_issues.append("template is missing BREAKFILLER")
    side_mismatches = [
        slot for slot in immutable if by_name[slot].location != slot[0]
    ]

    reserved_issues: list[str] = []
    for side_slots in (("W11", "W12"), ("E11", "E12")):
        if all(slot in by_name for slot in side_slots):
            cells = {by_name[slot].cell for slot in side_slots}
            if cells != {POWER_CELL, GROUND_CELL}:
                reserved_issues.append(
                    f"{side_slots[0]}/{side_slots[1]} must contain one {POWER_CELL} and one {GROUND_CELL}; found {sorted(cells)}"
                )

    return {
        "pad_count": len(entries),
        "immutable_slot_count": len(immutable),
        "missing_physical_slots": missing,
        "extra_physical_slots": extra,
        "side_mismatches": side_mismatches,
        "reserved_power_ground_issues": reserved_issues,
        "legacy_instance_names": legacy,
        "break_boundaries": sorted(found_breaks),
        "break_issues": break_issues,
        "valid_for_production": not missing and not extra and not legacy and not break_issues and not side_mismatches and not reserved_issues,
    }


def _require_block(block: str) -> tuple[str, ...]:
    block = block.upper()
    if block in UNFINALIZED_BLOCKS:
        raise NotFinalizedError(
            f"block {block} slot ordering is explicitly listed as not finalized in ChatGPT_spec.md"
        )
    try:
        return tuple(BLOCK_SLOTS[block])
    except KeyError as exc:
        raise ConfigError(f"unknown block type {block!r}") from exc


def _format_pad_line(original: str, instance: str, cell: str) -> str:
    m = PAD_RE.match(original)
    if not m:
        raise ConfigError(f"internal error: expected PAD line, got {original!r}")
    flip = " FLIP" if m.group("flip") else ""
    return (
        f"{m.group('indent')}PAD {instance} {m.group('location')}{flip} {cell} ;"
        f"{m.group('trailing')}"
    )


def generate_padring_config(
    *,
    info: dict[str, Any],
    info_path: Path,
    template_path: Path,
    block: str = "A",
    team_code: str | None = None,
    require_complete_template: bool = True,
) -> tuple[str, dict[str, Any]]:
    pins = validate_pins(info)
    if team_code is not None:
        normalized_team_code = safe_identifier(team_code.strip())
        if not team_code.strip() or normalized_team_code != team_code.strip():
            raise ConfigError(
                f"team code {team_code!r} must already be a valid canonical identifier"
            )
        design_name = f"{normalized_team_code}_padring"
    else:
        design_name = None
    slots = _require_block(block)
    if len(pins) > len(slots):
        raise ConfigError(
            f"project defines {len(pins)} pins but block {block.upper()} has only {len(slots)} user I/O slots"
        )

    template_text, lines, entries = read_template(template_path)
    if design_name is not None:
        design_lines = [i for i, line in enumerate(lines) if line.strip().startswith("DESIGN ")]
        if len(design_lines) != 1:
            raise ConfigError(f"{template_path}: expected exactly one DESIGN directive")
        lines[design_lines[0]] = f"DESIGN {design_name};"
    by_name = {entry.instance: entry for entry in entries}

    if require_complete_template:
        audit = audit_physical_template(template_path)
        if not audit["valid_for_production"]:
            details = []
            if audit["missing_physical_slots"]:
                details.append(f"missing {len(audit['missing_physical_slots'])} immutable physical slots")
            if audit["side_mismatches"]:
                details.append(f"side mismatch: {audit['side_mismatches']}")
            if audit["legacy_instance_names"]:
                details.append(f"unexpected PAD instances: {audit['legacy_instance_names']}")
            if audit["break_issues"]:
                details.append(f"missing or unexpected fixed breaks: {audit['break_issues']}")
            if audit["reserved_power_ground_issues"]:
                details.extend(audit["reserved_power_ground_issues"])
            raise ConfigError(
                f"{template_path}: not a production immutable-slot template ({'; '.join(details)})"
            )

    missing_block_slots = [slot for slot in slots if slot not in by_name]
    if missing_block_slots:
        raise ConfigError(
            f"{template_path}: missing physical block slots: {', '.join(missing_block_slots)}"
        )

    configurable_names = set(slots)
    fixed_names = {entry.instance for entry in entries} - configurable_names
    generated_names: set[str] = set()
    mapping: list[dict[str, Any]] = []

    for pin_index, slot_name in enumerate(slots):
        slot = by_name[slot_name]
        if pin_index < len(pins):
            pin = pins[pin_index]
            try:
                cell = IO_CELLS[pin["io_type"]]
            except KeyError as exc:
                raise ConfigError(f"missing required cell mapping for io_type {pin['io_type']!r}") from exc
            instance = slot_name
            if instance in generated_names:
                raise ConfigError(
                    f"pin {pin['name']!r} collides after sanitization as {instance!r}"
                )
            if instance in fixed_names:
                raise ConfigError(
                    f"pin {pin['name']!r} sanitizes to {instance!r}, which conflicts with a fixed PAD instance"
                )
            generated_names.add(instance)
            entry: dict[str, Any] = {
                "pin_index": pin_index,
                "pin_name": pin["name"],
                "slot": slot_name,
                "instance": instance,
                "io_type": pin["io_type"],
                "cell": cell,
            }
            if pin["io_type"] == "analog":
                entry["secondary_esd"] = pin["secondary_esd"]
        else:
            cell = ANALOG_PLACEHOLDER_CELL
            instance = slot_name
            if instance in generated_names or instance in fixed_names:
                raise ConfigError(f"generated placeholder name {instance!r} conflicts with another PAD instance")
            generated_names.add(instance)
            entry = {
                "slot": slot_name,
                "instance": instance,
                "generated": True,
                "cell": cell,
            }

        lines[slot.line_index] = _format_pad_line(lines[slot.line_index], instance, cell)
        mapping.append(entry)

    break_entries: list[dict[str, str]] = []
    insertions: list[tuple[int, list[str]]] = []
    power_count = 0
    for pin_index, pin in enumerate(pins):
        slot = by_name[slots[pin_index]]
        if pin["io_type"] == "power":
            power_count += 1
            if power_count > 1:
                name = f"BRK_BEFORE_{slot.instance}"
                insertions.append((slot.line_index, ["BREAK ;"]))
                break_entries.append({"instance": name, "reason": "repeated_power", "before_slot": slot.instance})

    last_slot = by_name[slots[len(pins) - 1]]
    after_name = f"BRK_AFTER_{block.upper()}"
    insertions.append((last_slot.line_index + 1, ["BREAK ;"]))
    break_entries.append({"instance": after_name, "reason": "project_boundary", "after_slot": last_slot.instance})
    for line_index, break_lines in sorted(insertions, reverse=True):
        lines[line_index:line_index] = break_lines

    # Reserved template-owned positions must never be touched by the A mapping.
    if set(slots) & set(RESERVED_VERTICAL_POWER_GROUND_SLOTS):
        raise ConfigError("internal configuration error: user slot list overlaps reserved power/ground slots")

    ending = "\n" if template_text.endswith("\n") else ""
    map_doc = {
        "spec_blob_sha": SPEC_BLOB_SHA,
        "source_info": str(info_path),
        "source_template": str(template_path),
        "block": block.upper(),
        "team_code": team_code,
        "design_name": design_name,
        "pin_count": len(pins),
        "user_slot_count": len(slots),
        "pads": mapping,
        "breaks": break_entries,
    }
    return "\n".join(lines) + ending, map_doc


def write_mapping(path: Path, mapping: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(mapping, stream, sort_keys=False)
