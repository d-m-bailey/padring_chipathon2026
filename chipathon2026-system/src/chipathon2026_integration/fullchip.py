from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import yaml

from .constants import ALL_PHYSICAL_SLOTS
from .defparse import DefDesign, load_def
from .errors import ConfigError
from .info import load_info, validate_pins
from .lvs import load_lvs_config, resolve_downloaded_gds
from .padring_cfg import PAD_RE, audit_physical_template, parse_pad_entries, safe_identifier
from .virtual_def import BLOCK_VARIANTS, BlockVariant


QUADRANTS = {"NW", "NE", "SE", "SW"}
SUPPLY_TYPES = {"power", "ground"}
BLOCKAGE_RE = re.compile(
    r"-\s+(?:(?P<placement>PLACEMENT)|LAYER\s+(?P<layer>\S+))\s+"
    r"\+\s+RECT\s+\(\s*(?P<x1>-?\d+)\s+(?P<y1>-?\d+)\s*\)\s+"
    r"\(\s*(?P<x2>-?\d+)\s+(?P<y2>-?\d+)\s*\)\s*;"
)


@dataclass(frozen=True)
class ProjectRequest:
    team: str
    variant: str
    quadrant: str


@dataclass(frozen=True)
class BaseVariantGeometry:
    origin: tuple[Decimal, Decimal]
    width: Decimal
    height: Decimal


@dataclass(frozen=True)
class BaseChipDefinition:
    path: Path
    name: str
    diearea: tuple[Decimal, Decimal, Decimal, Decimal]
    io_cells: dict[str, str]
    variant_geometry: dict[str, BaseVariantGeometry]

    def variant(self, code: str) -> BlockVariant:
        policy = BLOCK_VARIANTS[code]
        geometry = self.variant_geometry[code]
        return BlockVariant(
            code, policy.slots, geometry.origin, geometry.width, geometry.height,
            int(geometry.width * geometry.height), policy.blockages,
            policy.metal2_blockages,
        )


@dataclass(frozen=True)
class ChipRequest:
    name: str
    base_chip: BaseChipDefinition
    minimum_gap: Decimal
    projects: tuple[ProjectRequest, ...]

    @property
    def floorplan(self) -> str:
        return self.base_chip.name

    @property
    def diearea(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return self.base_chip.diearea

    @property
    def io_cells(self) -> dict[str, str]:
        return self.base_chip.io_cells

    def variant(self, code: str) -> BlockVariant:
        return self.base_chip.variant(code)


@dataclass(frozen=True)
class ProjectArtifacts:
    request: ProjectRequest
    info_path: Path
    lvs_config_path: Path
    gds_path: Path
    def_path: Path
    interface_path: Path
    info: dict[str, Any]
    pins: tuple[dict[str, Any], ...]
    design: DefDesign
    interface: dict[str, Any]


@dataclass(frozen=True)
class Placement:
    artifacts: ProjectArtifacts
    source_top: str
    integrated_top: str
    prboundary: tuple[Decimal, Decimal, Decimal, Decimal]
    transformed_boundary: tuple[Decimal, Decimal, Decimal, Decimal]
    transformed_slots: tuple[str, ...]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ConfigError(f"{field} must be a decimal number") from exc
    if not result.is_finite():
        raise ConfigError(f"{field} must be finite")
    return result


def _exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ConfigError(f"{context}: {'; '.join(details)}")


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping,
)


def _load_yaml(path: Path, description: str) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {description} {path}: {exc}") from exc


def load_base_chip(path: Path) -> BaseChipDefinition:
    path = path.resolve()
    raw = _load_yaml(path, "base-chip YAML")
    if not isinstance(raw, dict):
        raise ConfigError("base-chip YAML top level must be a mapping")
    _exact_keys(raw, {"schema_version", "chip", "io_cells", "block_variants"}, "base-chip YAML")
    if raw["schema_version"] != 1:
        raise ConfigError("base-chip YAML schema_version must be 1")
    chip = raw["chip"]
    if not isinstance(chip, dict):
        raise ConfigError("base-chip chip must be a mapping")
    _exact_keys(chip, {"name", "diearea_um"}, "base-chip chip")
    name = chip["name"]
    if not isinstance(name, str) or safe_identifier(name) != name:
        raise ConfigError("base-chip chip.name must be a non-empty canonical identifier")
    raw_diearea = chip["diearea_um"]
    if not isinstance(raw_diearea, list) or len(raw_diearea) != 4:
        raise ConfigError("base-chip chip.diearea_um must contain four coordinates")
    diearea = tuple(_decimal(value, "base-chip chip.diearea_um") for value in raw_diearea)
    if diearea[2] <= diearea[0] or diearea[3] <= diearea[1]:
        raise ConfigError("base-chip chip.diearea_um must describe a positive-area rectangle")

    raw_cells = raw["io_cells"]
    if not isinstance(raw_cells, dict) or not raw_cells:
        raise ConfigError("base-chip io_cells must be a non-empty mapping")
    io_cells: dict[str, str] = {}
    for io_type, macro in raw_cells.items():
        if not isinstance(io_type, str) or not io_type or safe_identifier(io_type) != io_type:
            raise ConfigError(f"base-chip io_cells has invalid io_type {io_type!r}")
        if not isinstance(macro, str) or not macro or safe_identifier(macro) != macro:
            raise ConfigError(f"base-chip io_cells.{io_type} must be a canonical macro name")
        io_cells[io_type] = macro
    for required_type in ("analog", "power", "ground"):
        if required_type not in io_cells:
            raise ConfigError(f"base-chip io_cells is missing required type {required_type!r}")

    raw_variants = raw["block_variants"]
    if not isinstance(raw_variants, dict):
        raise ConfigError("base-chip block_variants must be a mapping")
    expected_variants = set(BLOCK_VARIANTS)
    actual_variants = set(raw_variants)
    if actual_variants != expected_variants:
        missing = sorted(expected_variants - actual_variants)
        extra = sorted(actual_variants - expected_variants)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ConfigError("base-chip block_variants: " + "; ".join(details))
    variants: dict[str, BaseVariantGeometry] = {}
    x1, y1, x2, y2 = diearea
    for code in BLOCK_VARIANTS:
        value = raw_variants[code]
        if not isinstance(value, dict):
            raise ConfigError(f"base-chip block_variants.{code} must be a mapping")
        _exact_keys(value, {"origin_um", "size_um"}, f"base-chip block_variants.{code}")
        origin_raw, size_raw = value["origin_um"], value["size_um"]
        if not isinstance(origin_raw, list) or len(origin_raw) != 2:
            raise ConfigError(f"base-chip block_variants.{code}.origin_um must contain two coordinates")
        if not isinstance(size_raw, list) or len(size_raw) != 2:
            raise ConfigError(f"base-chip block_variants.{code}.size_um must contain width and height")
        origin = tuple(_decimal(v, f"base-chip block_variants.{code}.origin_um") for v in origin_raw)
        size = tuple(_decimal(v, f"base-chip block_variants.{code}.size_um") for v in size_raw)
        if origin[0] < 0 or origin[1] < 0 or size[0] <= 0 or size[1] <= 0:
            raise ConfigError(f"base-chip block_variants.{code} origin must be nonnegative and size positive")
        if origin[0] < x1 or origin[1] < y1 or origin[0] + size[0] > x2 or origin[1] + size[1] > y2:
            raise ConfigError(f"base-chip block_variants.{code} lies outside chip DIEAREA")
        variants[code] = BaseVariantGeometry(origin, size[0], size[1])
    return BaseChipDefinition(path, name, diearea, io_cells, variants)


def load_chip_request(path: Path, *, base_chip_override: Path | None = None) -> ChipRequest:
    raw = _load_yaml(path, "integration YAML")
    if not isinstance(raw, dict):
        raise ConfigError("integration YAML top level must be a mapping")
    _exact_keys(raw, {"schema_version", "base_chip", "chip", "projects"}, "integration YAML")
    if raw["schema_version"] != 2:
        raise ConfigError("integration YAML schema_version must be 2")
    base_reference = raw["base_chip"]
    if not isinstance(base_reference, str) or not base_reference.strip():
        raise ConfigError("integration YAML base_chip must be a non-empty path")
    base_path = base_chip_override
    if base_path is None:
        base_path = Path(base_reference)
        if not base_path.is_absolute():
            base_path = path.parent / base_path
    base_chip = load_base_chip(base_path)
    chip = raw["chip"]
    if not isinstance(chip, dict):
        raise ConfigError("chip must be a mapping")
    _exact_keys(chip, {"name", "minimum_project_gap_um"}, "chip")
    name = chip["name"]
    if not isinstance(name, str) or safe_identifier(name) != name:
        raise ConfigError("chip.name must be a non-empty canonical identifier")
    gap = _decimal(chip["minimum_project_gap_um"], "chip.minimum_project_gap_um")
    if gap < 10:
        raise ConfigError("minimum_project_gap_um must be at least 10")
    raw_projects = raw["projects"]
    if not isinstance(raw_projects, list) or not raw_projects:
        raise ConfigError("projects must be a non-empty list")
    projects = []
    seen_teams: set[str] = set()
    for index, item in enumerate(raw_projects):
        if not isinstance(item, dict):
            raise ConfigError(f"projects[{index}] must be a mapping")
        _exact_keys(item, {"team", "variant", "quadrant"}, f"projects[{index}]")
        team, variant, quadrant = item["team"], item["variant"], item["quadrant"]
        if not isinstance(team, str) or safe_identifier(team) != team:
            raise ConfigError(f"projects[{index}].team must be a canonical identifier")
        team_key = team.casefold()
        if team_key in seen_teams:
            raise ConfigError(f"team {team!r} appears more than once")
        seen_teams.add(team_key)
        variant = str(variant).upper()
        if variant not in base_chip.variant_geometry:
            raise ConfigError(f"projects[{index}] has unknown variant {variant!r}")
        quadrant = str(quadrant).upper()
        if quadrant not in QUADRANTS:
            raise ConfigError(f"projects[{index}] has invalid quadrant {quadrant!r}")
        projects.append(ProjectRequest(team, variant, quadrant))
    return ChipRequest(name, base_chip, gap, tuple(projects))


def _artifact_pair(project_root: Path, team: str, variant: str) -> tuple[Path, Path]:
    candidates = [
        project_root / team / "project_defs" / variant,
        project_root / team / variant,
        project_root / variant,
    ]
    pairs = []
    for root in candidates:
        def_path = root / f"{team}_{variant}.def"
        interface_path = root / f"{team}_{variant}_interface.yaml"
        if def_path.is_file() and interface_path.is_file():
            pairs.append((def_path, interface_path))
    if len(pairs) != 1:
        raise ConfigError(
            f"expected exactly one canonical DEF/interface pair for {team}/{variant} "
            f"under {project_root}; found {len(pairs)}"
        )
    return pairs[0]


def discover_project(
    request: ProjectRequest, *, base_chip: BaseChipDefinition, info_root: Path,
    project_root: Path, gds_root: Path,
) -> ProjectArtifacts:
    info_path = info_root / f"{request.team}_info.yaml"
    lvs_path = info_root / f"{request.team}_lvs_config.json"
    info = load_info(info_path)
    pins = tuple(validate_pins(info, io_cells=base_chip.io_cells))
    variant = base_chip.variant(request.variant)
    if len(pins) > len(variant.slots):
        raise ConfigError(
            f"{request.team}: {len(pins)} pins exceed {request.variant} capacity {len(variant.slots)}"
        )
    _validate_endpoint(request.team, variant, pins)
    config = load_lvs_config(lvs_path)
    gds_path = resolve_downloaded_gds(config, team=request.team, gds_dir=gds_root)
    def_path, interface_path = _artifact_pair(project_root, request.team, request.variant)
    design = load_def(def_path)
    try:
        interface = yaml.safe_load(interface_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read interface metadata {interface_path}: {exc}") from exc
    if not isinstance(interface, dict) or interface.get("variant") != request.variant:
        raise ConfigError(f"{interface_path}: interface variant does not match {request.variant}")
    expected_diearea = (
        0, 0, _micron_to_dbu(variant.width, design.units, "variant width"),
        _micron_to_dbu(variant.height, design.units, "variant height"),
    )
    if design.diearea != expected_diearea:
        raise ConfigError(
            f"{def_path}: DIEAREA {design.diearea} does not match {request.variant} {expected_diearea}"
        )
    raw_origin = interface.get("origin_microns")
    try:
        interface_origin = tuple(_decimal(value, "interface origin_microns") for value in raw_origin)
    except TypeError as exc:
        raise ConfigError(f"{interface_path}: origin_microns must contain two coordinates") from exc
    if len(interface_origin) != 2 or interface_origin != variant.origin:
        raise ConfigError(
            f"{interface_path}: origin {raw_origin} does not match {[str(value) for value in variant.origin]}"
        )
    return ProjectArtifacts(
        request, info_path, lvs_path, gds_path, def_path, interface_path,
        info, pins, design, interface,
    )


def _validate_endpoint(team: str, variant: BlockVariant, pins: tuple[dict[str, Any], ...]) -> None:
    if not pins:
        raise ConfigError(f"{team}: project has no pins")
    if variant.code in {"EV", "CV"} and pins[0]["io_type"] not in SUPPLY_TYPES:
        raise ConfigError(f"{team}: {variant.code} requires first I/O to be power or ground")
    if variant.code in {"EH", "CH"} and pins[-1]["io_type"] not in SUPPLY_TYPES:
        raise ConfigError(f"{team}: {variant.code} requires last I/O to be power or ground")


def transform_point(
    x: Decimal, y: Decimal, quadrant: str,
    diearea: tuple[Decimal, Decimal, Decimal, Decimal],
) -> tuple[Decimal, Decimal]:
    x1, y1, x2, y2 = diearea
    return {
        "NW": (x, y), "NE": (x1 + x2 - x, y),
        "SE": (x1 + x2 - x, y1 + y2 - y), "SW": (x, y1 + y2 - y),
    }[quadrant]


def transform_box(
    box: tuple[Decimal, Decimal, Decimal, Decimal], quadrant: str,
    diearea: tuple[Decimal, Decimal, Decimal, Decimal],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    x1, y1, x2, y2 = box
    points = [transform_point(x, y, quadrant, diearea) for x, y in ((x1, y1), (x1, y2), (x2, y1), (x2, y2))]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def transform_slot(slot: str, quadrant: str) -> str:
    side, number = slot[0], int(slot[1:])
    reverse = 23 - number
    table = {
        "NW": {"N": ("N", number), "E": ("E", number), "S": ("S", number), "W": ("W", number)},
        "NE": {"N": ("N", reverse), "E": ("W", number), "S": ("S", reverse), "W": ("E", number)},
        "SE": {"N": ("S", reverse), "E": ("W", reverse), "S": ("N", reverse), "W": ("E", reverse)},
        "SW": {"N": ("S", number), "E": ("E", reverse), "S": ("N", number), "W": ("W", reverse)},
    }
    new_side, new_number = table[quadrant][side]
    return f"{new_side}{new_number:02d}"


def prefix_name(team: str, name: str) -> str:
    prefix = f"{team}_"
    return name if name.casefold().startswith(prefix.casefold()) else prefix + name


def build_placements(
    chip: ChipRequest, artifacts: Iterable[ProjectArtifacts], measurements: dict[str, Any],
) -> tuple[Placement, ...]:
    placements = []
    for artifact in artifacts:
        team = artifact.request.team
        measured = measurements.get(team)
        if not isinstance(measured, dict):
            raise ConfigError(f"missing GDS measurement for {team}")
        source_top = measured.get("top_cell")
        rectangle = measured.get("prboundary_microns")
        if not isinstance(source_top, str) or not isinstance(rectangle, list) or len(rectangle) != 4:
            raise ConfigError(f"invalid GDS measurement for {team}")
        boundary = tuple(_decimal(v, f"{team} PR boundary") for v in rectangle)
        if boundary[0:2] != (Decimal(0), Decimal(0)):
            raise ConfigError(f"{team}: PR boundary origin must be (0,0), found {boundary[0:2]}")
        variant = chip.variant(artifact.request.variant)
        if boundary[2] <= 0 or boundary[3] <= 0 or boundary[2] > variant.width or boundary[3] > variant.height:
            raise ConfigError(
                f"{team}: PR boundary {boundary} does not fit {variant.code} "
                f"{variant.width}x{variant.height}"
            )
        canonical = (variant.origin[0], variant.origin[1], variant.origin[0] + boundary[2], variant.origin[1] + boundary[3])
        transformed = transform_box(canonical, artifact.request.quadrant, chip.diearea)
        slots = tuple(transform_slot(slot, artifact.request.quadrant) for slot in variant.slots[:len(artifact.pins)])
        if len(set(slots)) != len(slots):
            raise ConfigError(f"{team}: transformed slot mapping contains duplicates")
        integrated_top = prefix_name(team, source_top)
        placements.append(Placement(artifact, source_top, integrated_top, boundary, transformed, slots))
    _validate_placements(chip, placements)
    return tuple(placements)


def _box_distance(a: tuple[Decimal, Decimal, Decimal, Decimal], b: tuple[Decimal, Decimal, Decimal, Decimal]) -> Decimal:
    dx = max(Decimal(0), a[0] - b[2], b[0] - a[2])
    dy = max(Decimal(0), a[1] - b[3], b[1] - a[3])
    return (dx * dx + dy * dy).sqrt()


def _validate_placements(chip: ChipRequest, placements: list[Placement]) -> None:
    used_slots: dict[str, str] = {}
    top_cells: dict[str, str] = {}
    top_pins: dict[str, str] = {}
    x1, y1, x2, y2 = chip.diearea
    for placement in placements:
        team = placement.artifacts.request.team
        top_key = placement.integrated_top.casefold()
        if top_key in top_cells:
            raise ConfigError(
                f"integrated project top-cell collision: {top_cells[top_key]!r}/{placement.integrated_top!r}"
            )
        top_cells[top_key] = placement.integrated_top
        box = placement.transformed_boundary
        if box[0] < x1 or box[1] < y1 or box[2] > x2 or box[3] > y2:
            raise ConfigError(f"{placement.artifacts.request.team}: transformed PR boundary is outside chip DIEAREA")
        for slot in placement.transformed_slots:
            if slot in used_slots:
                raise ConfigError(f"physical I/O slot {slot} is allocated by both {used_slots[slot]} and {placement.artifacts.request.team}")
            used_slots[slot] = placement.artifacts.request.team
        for pin in placement.artifacts.pins:
            name = prefix_name(team, pin["name"])
            key = name.casefold()
            if key in top_pins:
                raise ConfigError(f"case-insensitive top-level project pin collision: {top_pins[key]!r}/{name!r}")
            top_pins[key] = name
    conflicts = []
    for i, left in enumerate(placements):
        for right in placements[i + 1:]:
            distance = _box_distance(left.transformed_boundary, right.transformed_boundary)
            if distance < chip.minimum_gap:
                conflicts.append(f"{left.artifacts.request.team}/{right.artifacts.request.team}: gap {distance} < {chip.minimum_gap}")
    if conflicts:
        raise ConfigError("project spacing violation(s): " + "; ".join(conflicts))


def _format_pad(original: str, cell: str) -> str:
    match = PAD_RE.match(original)
    if match is None:
        raise ConfigError(f"internal PAD formatting error: {original!r}")
    flip = " FLIP" if match.group("flip") else ""
    return f"{match.group('indent')}PAD {match.group('instance')} {match.group('location')}{flip} {cell} ;{match.group('trailing')}"


def generate_chip_padring(
    chip: ChipRequest, placements: Iterable[Placement], template_path: Path,
) -> tuple[str, dict[str, Any]]:
    audit = audit_physical_template(template_path)
    if not audit["valid_for_production"]:
        raise ConfigError(f"{template_path}: invalid production padring template: {audit}")
    text = template_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    entries = parse_pad_entries(lines)
    by_slot = {entry.instance: entry for entry in entries}
    design_lines = [i for i, line in enumerate(lines) if line.strip().startswith("DESIGN ")]
    if len(design_lines) != 1:
        raise ConfigError("padring template must contain exactly one DESIGN directive")
    lines[design_lines[0]] = f"DESIGN {chip.name}_padring;"
    allocated: dict[str, dict[str, Any]] = {}
    breaks: list[dict[str, Any]] = []
    break_indexes: set[int] = set()

    def gap_index(left: str, right: str) -> int | None:
        if left[0] != right[0]:
            # A corner cell already occupies and isolates a cross-side gap.
            return None
        if abs(int(left[1:]) - int(right[1:])) != 1:
            raise ConfigError(f"non-adjacent slots cannot define a break gap: {left}/{right}")
        return max(by_slot[left].line_index, by_slot[right].line_index)

    for placement in placements:
        team = placement.artifacts.request.team
        pins = placement.artifacts.pins
        region_power = region_ground = False
        full_slots = tuple(
            transform_slot(slot, placement.artifacts.request.quadrant)
            for slot in chip.variant(placement.artifacts.request.variant).slots
        )
        for index, (pin, slot) in enumerate(zip(pins, placement.transformed_slots)):
            if slot in allocated:
                raise ConfigError(f"duplicate physical slot {slot}")
            io_type = pin["io_type"]
            if (io_type == "power" and region_power) or (io_type == "ground" and region_ground):
                if not region_power or not region_ground:
                    raise ConfigError(f"{team}: incomplete power/ground group before {slot}")
                rendered_gap = gap_index(placement.transformed_slots[index - 1], slot)
                if rendered_gap is not None:
                    break_indexes.add(rendered_gap)
                breaks.append({"team": team, "before_slot": slot, "reason": "additional_power_ground_set"})
                region_power = region_ground = False
            region_power |= io_type == "power"
            region_ground |= io_type == "ground"
            top_name = prefix_name(team, pin["name"])
            allocated[slot] = {
                "pin_index": len(allocated), "pin_name": pin["name"], "top_pin_name": top_name,
                "slot": slot, "instance": slot, "io_type": io_type,
                "cell": chip.io_cells[io_type], "team_code": team,
                **({"secondary_esd": pin["secondary_esd"]} if io_type == "analog" else {}),
            }
        if not region_power or not region_ground:
            raise ConfigError(f"{team}: final power/ground group is incomplete")
        first, last = placement.transformed_slots[0], placement.transformed_slots[-1]
        first_step = int(full_slots[1][1:]) - int(full_slots[0][1:])
        before_first = f"{first[0]}{int(first[1:]) - first_step:02d}"
        if len(placement.transformed_slots) < len(full_slots):
            after_last = full_slots[len(placement.transformed_slots)]
        else:
            last_step = int(full_slots[-1][1:]) - int(full_slots[-2][1:])
            after_last = f"{last[0]}{int(last[1:]) + last_step:02d}"
        for left, right in ((before_first, first), (last, after_last)):
            rendered_gap = gap_index(left, right)
            if rendered_gap is not None:
                break_indexes.add(rendered_gap)
        breaks.extend([
            {"team": team, "before_slot": first, "reason": "project_boundary"},
            {"team": team, "after_slot": last, "reason": "project_boundary"},
        ])
    for slot, pad in allocated.items():
        entry = by_slot[slot]
        lines[entry.line_index] = _format_pad(lines[entry.line_index], pad["cell"])
    for index in sorted(break_indexes, reverse=True):
        lines[index:index] = ["BREAK ;"]
    pads = []
    for slot in ALL_PHYSICAL_SLOTS:
        pads.append(allocated.get(slot, {
            "slot": slot, "instance": slot, "generated": True,
            "cell": chip.io_cells["analog"],
        }))
    mapping = {
        "schema_version": 1, "team_code": chip.name, "design_name": f"{chip.name}_padring",
        "pin_count": len(allocated), "pads": pads, "breaks": breaks,
    }
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), mapping


def _micron_to_dbu(value: Decimal, units: int, context: str) -> int:
    scaled = value * units
    if scaled != scaled.to_integral_value():
        raise ConfigError(f"{context}={value} is not exactly representable in DEF units {units}")
    return int(scaled)


def _def_transform(
    chip: ChipRequest, placement: Placement, units: int,
) -> tuple[int, int, str]:
    variant = chip.variant(placement.artifacts.request.variant)
    ox, oy = variant.origin
    x1, y1, x2, y2 = chip.diearea
    values = {
        "NW": (ox, oy, "N"), "NE": (x1 + x2 - ox, oy, "FN"),
        "SE": (x1 + x2 - ox, y1 + y2 - oy, "S"),
        "SW": (ox, y1 + y2 - oy, "FS"),
    }[placement.artifacts.request.quadrant]
    return _micron_to_dbu(values[0], units, "project X"), _micron_to_dbu(values[1], units, "project Y"), values[2]


def interface_pins(placement: Placement) -> list[dict[str, Any]]:
    raw = placement.artifacts.interface.get("pins")
    if not isinstance(raw, list):
        raise ConfigError(f"{placement.artifacts.interface_path}: missing pins list")
    return [pin for pin in raw if isinstance(pin, dict)]


def _interface_net(placement: Placement, pin: dict[str, Any]) -> str:
    team = placement.artifacts.request.team
    project_pin = str(pin["project_pin"])
    source_slot = pin.get("physical_pad_slot")
    source_pad = next(
        (pad for pad, slot in zip(placement.artifacts.pins, BLOCK_VARIANTS[placement.artifacts.request.variant].slots) if slot == source_slot),
        None,
    )
    net = prefix_name(team, project_pin)
    if (
        source_pad is not None
        and source_pad.get("io_type") in {"input_cmos", "input_schmitt"}
        and pin.get("cell_terminal") == "Y"
    ):
        return net + "__CORE"
    return net


def write_integrated_def(
    path: Path, chip: ChipRequest, placements: Iterable[Placement], padring_def: Path,
) -> None:
    ring = load_def(padring_def)
    units = ring.units
    placements = tuple(placements)
    components = [("PADRING", f"{chip.name}_padring", 0, 0, "N")]
    for placement in placements:
        x, y, orient = _def_transform(chip, placement, units)
        components.append((f"{placement.artifacts.request.team}_PROJECT", placement.integrated_top, x, y, orient))
    top_pins = []
    nets: dict[str, list[tuple[str, str]]] = {}

    def connect(net: str, instance: str, pin: str) -> None:
        connection = (instance, pin)
        nets.setdefault(net, [])
        if connection not in nets[net]:
            nets[net].append(connection)

    for placement in placements:
        team = placement.artifacts.request.team
        by_slot = {pin["physical_pad_slot"]: pin for pin in interface_pins(placement) if "physical_pad_slot" in pin}
        for pad, slot in zip(placement.artifacts.pins, placement.transformed_slots):
            top_name = prefix_name(team, pad["name"])
            source = ring.pins.get(slot)
            if source is None:
                raise ConfigError(f"chip padring DEF is missing physical pin {slot}")
            top_pins.append((top_name, source))
            connect(top_name, "PADRING", slot)
        for pin in interface_pins(placement):
            source_slot = pin.get("physical_pad_slot")
            project_pin = pin.get("project_pin")
            terminal = pin.get("cell_terminal")
            if not all(isinstance(v, str) for v in (source_slot, project_pin, terminal)):
                continue
            transformed_slot = transform_slot(source_slot, placement.artifacts.request.quadrant)
            net = _interface_net(placement, pin)
            if terminal not in {"DVDD", "DVSS"}:
                connect(net, "PADRING", f"{transformed_slot}_{terminal}")
            connect(net, f"{team}_PROJECT", project_pin)
    blockages = []
    for placement in placements:
        variant = chip.variant(placement.artifacts.request.variant)
        source_text = placement.artifacts.def_path.read_text(encoding="utf-8")
        for match in BLOCKAGE_RE.finditer(source_text):
            local = tuple(Decimal(match.group(name)) / placement.artifacts.design.units for name in ("x1", "y1", "x2", "y2"))
            canonical = (
                variant.origin[0] + local[0], variant.origin[1] + local[1],
                variant.origin[0] + local[2], variant.origin[1] + local[3],
            )
            transformed = transform_box(canonical, placement.artifacts.request.quadrant, chip.diearea)
            rect = tuple(_micron_to_dbu(value, units, "transformed blockage") for value in transformed)
            blockages.append(("PLACEMENT" if match.group("placement") else match.group("layer"), rect))
    diearea_dbu = tuple(
        _micron_to_dbu(value, units, "chip DIEAREA") for value in chip.diearea
    )
    lines = [
        "VERSION 5.8 ;", 'DIVIDERCHAR "/" ;', 'BUSBITCHARS "[]" ;',
        f"DESIGN {chip.name} ;", f"UNITS DISTANCE MICRONS {units} ;",
        f"DIEAREA ( {diearea_dbu[0]} {diearea_dbu[1]} ) ( {diearea_dbu[2]} {diearea_dbu[3]} ) ;",
        f"COMPONENTS {len(components)} ;",
    ]
    lines.extend(f"- {inst} {macro} + FIXED ( {x} {y} ) {orient} ;" for inst, macro, x, y, orient in components)
    lines.extend(["END COMPONENTS", f"PINS {len(top_pins)} ;"])
    for name, pin in top_pins:
        lines.append(f"- {name} + NET {name} + DIRECTION INOUT + USE {pin.use}")
        for rect in pin.rects:
            lines.append(f"  + LAYER {rect.layer} ( {rect.x1} {rect.y1} ) ( {rect.x2} {rect.y2} )")
        lines.append("  + FIXED ( 0 0 ) N ;")
    lines.extend(["END PINS", f"NETS {len(nets)} ;"])
    for name, connections in nets.items():
        lines.append(f"- {name} " + " ".join(f"( {inst} {pin} )" for inst, pin in connections) + " ;")
    lines.append("END NETS")
    if blockages:
        lines.append(f"BLOCKAGES {len(blockages)} ;")
        for kind, (x1, y1, x2, y2) in blockages:
            prefix = "PLACEMENT" if kind == "PLACEMENT" else f"LAYER {kind}"
            lines.append(f"- {prefix} + RECT ( {x1} {y1} ) ( {x2} {y2} ) ;")
        lines.append("END BLOCKAGES")
    lines.extend(["END DESIGN", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_top_verilog(path: Path, chip: ChipRequest, placements: Iterable[Placement]) -> None:
    placements = tuple(placements)
    physical_ports = []
    project_connections: dict[str, dict[str, str]] = {}
    padring_connections: dict[str, str] = {}
    for placement in placements:
        team = placement.artifacts.request.team
        project_connections[team] = {}
        for pad, slot in zip(placement.artifacts.pins, placement.transformed_slots):
            top_name = prefix_name(team, pad["name"])
            physical_ports.append(top_name)
            padring_connections[slot] = top_name
        for pin in interface_pins(placement):
            source_slot, project_pin, terminal = pin.get("physical_pad_slot"), pin.get("project_pin"), pin.get("cell_terminal")
            if not all(isinstance(v, str) for v in (source_slot, project_pin, terminal)):
                continue
            slot = transform_slot(source_slot, placement.artifacts.request.quadrant)
            net = _interface_net(placement, pin)
            project_connections[team][project_pin] = net
            if terminal not in {"DVDD", "DVSS"}:
                padring_connections[f"{slot}_{terminal}"] = net
    all_nets = sorted(set(padring_connections.values()) | {n for c in project_connections.values() for n in c.values()})
    lines = [f"module {chip.name} (", *[
        f"    {name}{',' if i + 1 < len(physical_ports) else ''}" for i, name in enumerate(physical_ports)
    ], ");"]
    lines.extend(f"  inout {name};" for name in physical_ports)
    lines.extend(f"  wire {name};" for name in all_nets if name not in physical_ports)
    ring_connections = ", ".join(f".{port}({net})" for port, net in sorted(padring_connections.items()))
    lines.append(f"  {chip.name}_padring PADRING ({ring_connections});")
    for placement in placements:
        team = placement.artifacts.request.team
        connections = ", ".join(f".{port}({net})" for port, net in project_connections[team].items())
        lines.append(f"  {placement.integrated_top} {team}_PROJECT ({connections});")
    lines.extend(["endmodule", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def rewrite_pin_csv(raw_path: Path, output_path: Path, placements: Iterable[Placement]) -> list[dict[str, Any]]:
    assignment = {}
    for placement in placements:
        team = placement.artifacts.request.team
        for pin, slot in zip(placement.artifacts.pins, placement.transformed_slots):
            assignment[slot] = (team, prefix_name(team, pin["name"]), pin["io_type"])
    rows = []
    seen_slots: set[str] = set()
    with raw_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            slot = row["canonical_pin_name"]
            if slot not in assignment:
                continue
            if slot in seen_slots:
                raise ConfigError(f"raw padring CSV contains duplicate physical slot {slot}")
            seen_slots.add(slot)
            team, name, io_type = assignment[slot]
            rows.append({
                "team_code": team, "project_pin_name": name,
                "canonical_pad_name": slot, "type": io_type,
                "x": row["x"], "y": row["y"],
            })
    missing = sorted(set(assignment) - seen_slots)
    if missing:
        raise ConfigError("raw padring CSV is missing allocated slots: " + ", ".join(missing))
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["team_code", "project_pin_name", "canonical_pad_name", "type", "x", "y"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
