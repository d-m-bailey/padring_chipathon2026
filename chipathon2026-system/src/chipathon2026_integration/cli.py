from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import yaml

from .constants import A_SLOTS, CELL_PROJECT_TERMINALS, IO_CELLS, SPEC_BLOB_SHA
from .errors import IntegrationError
from .info import get_lvs_config_reference, load_info, validate_pins
from .lef import parse_lef_files, validate_project_terminals
from .lvs import get_layout_file, load_lvs_config, resolve_downloaded_gds
from .padring_cfg import audit_physical_template, generate_padring_config, safe_identifier, write_mapping
from .padring_runner import build_padring_command, required_lef_paths, run_padring
from .defparse import load_def
from .virtual_def import (
    BLOCK_VARIANTS,
    GF180_ROUTING_LAYERS,
    generate_project_def,
    load_mapping,
    mapped_pads,
    micron_to_dbu,
    select_block_variants,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Chipathon 2026 GF180 padframe integration tools")
    p.add_argument("--spec-sha", action="store_true", help="print the pinned live-spec blob SHA and exit")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("validate-info", help="validate participant info.yaml")
    s.add_argument("info_yaml", type=Path)

    s = sub.add_parser("inspect-lvs", help="resolve project.lvs_config and LAYOUT_FILE")
    s.add_argument("info_yaml", type=Path)
    s.add_argument("--uprj-root")

    s = sub.add_parser("resolve-project-gds", help="resolve the downloaded GDS selected by lvs_config.json")
    s.add_argument("--lvs-config", type=Path)
    s.add_argument("--gds-dir", type=Path, required=True)
    s.add_argument("--team-code", required=True)
    s.add_argument("--project-gds", type=Path, help="explicit override")
    s.add_argument("--output", type=Path, required=True)

    s = sub.add_parser("audit-template", help="check an immutable 88-slot padring template")
    s.add_argument("template_cfg", type=Path)

    s = sub.add_parser("generate-padring", help="generate project padring config and mapping")
    s.add_argument("info_yaml", type=Path)
    s.add_argument("template_cfg", type=Path)
    s.add_argument("-o", "--output", type=Path, required=True)
    s.add_argument("--map-out", type=Path, required=True)
    s.add_argument("--map-json-out", type=Path)
    s.add_argument("--block", default="A")
    s.add_argument("--team-code", required=True)
    s.add_argument("--allow-partial-template", action="store_true", help="testing only: do not require all 88 immutable slots")

    s = sub.add_parser("padring-command", help="print the exact padring invocation")
    s.add_argument("--padring", type=Path, required=True)
    s.add_argument("--tech-pdk", type=Path, required=True)
    s.add_argument("--cfg", type=Path, required=True)
    s.add_argument("--def-out", type=Path, required=True)
    s.add_argument("--svg-out", type=Path)
    s.add_argument("--verilog-out", type=Path)
    s.add_argument("--mapping", type=Path)
    s.add_argument("--def-dbu", type=float, default=0.005)

    s = sub.add_parser("run-padring", help="run YosysHQ padring with all required GF180 LEFs")
    s.add_argument("--padring", type=Path, required=True)
    s.add_argument("--tech-pdk", type=Path, required=True)
    s.add_argument("--cfg", type=Path, required=True)
    s.add_argument("--def-out", type=Path, required=True)
    s.add_argument("--svg-out", type=Path)
    s.add_argument("--verilog-out", type=Path)
    s.add_argument("--mapping", type=Path)
    s.add_argument("--def-dbu", type=float, default=0.005)

    s = sub.add_parser("inspect-lef", help="inspect/validate project-facing GF180 terminals in LEFs")
    s.add_argument("lef", type=Path, nargs="+")

    s = sub.add_parser("generate-project-def", help="generate canonical project DEF files for all minimal fitting variants")
    s.add_argument("--mapping", type=Path, required=True)
    s.add_argument("--padring-def", type=Path, required=True)
    s.add_argument("--lef", type=Path, nargs="+", required=True)
    s.add_argument("--project-width", help="project width in microns")
    s.add_argument("--project-height", help="project height in microns")
    s.add_argument("--project-size-json", type=Path, help="dimensions written by scripts/measure_project_gds.py")
    s.add_argument("--variant", choices=tuple(BLOCK_VARIANTS), help="generate one fitting variant instead of all minimum-area variants")
    s.add_argument("--output-dir", type=Path, required=True)
    s.add_argument("--design", help="output design-name prefix; defaults to mapping team code")
    s.add_argument("--routing-layer", action="append", dest="routing_layers", help="routing layer to block; repeat to override GF180 Metal1-Metal5")

    s = sub.add_parser("build-project-defs", help="select variants and build their padring and canonical project DEFs")
    s.add_argument("info_yaml", type=Path)
    s.add_argument("template_cfg", type=Path)
    s.add_argument("--team-code", required=True)
    s.add_argument("--project-size-json", type=Path, required=True)
    s.add_argument("--padring", type=Path, required=True)
    s.add_argument("--tech-pdk", type=Path, required=True)
    s.add_argument("--output-dir", type=Path, required=True)
    s.add_argument("--def-dbu", type=float, default=0.005)
    s.add_argument("--routing-layer", action="append", dest="routing_layers")

    s = sub.add_parser("show-config", help="show source-of-truth semantic constants")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.spec_sha:
        print(SPEC_BLOB_SHA)
        return 0
    if not args.command:
        parser().print_help()
        return 2
    try:
        if args.command == "validate-info":
            info = load_info(args.info_yaml)
            pins = validate_pins(info)
            print(f"OK: {len(pins)} pins")
            print(f"project.lvs_config: {get_lvs_config_reference(info)}")
            return 0

        if args.command == "inspect-lvs":
            info = load_info(args.info_yaml)
            ref = get_lvs_config_reference(info)
            path = (args.info_yaml.parent / ref).resolve()
            config = load_lvs_config(path)
            print(f"lvs_config: {path}")
            print(f"LAYOUT_FILE: {get_layout_file(config, uprj_root=args.uprj_root)}")
            return 0

        if args.command == "resolve-project-gds":
            if args.project_gds is not None:
                gds_path = args.project_gds
                source = "PROJECT_GDS override"
            else:
                if args.lvs_config is None:
                    raise IntegrationError("--lvs-config is required unless --project-gds is supplied")
                config = load_lvs_config(args.lvs_config)
                gds_path = resolve_downloaded_gds(config, team=args.team_code, gds_dir=args.gds_dir)
                source = str(args.lvs_config)
            if not gds_path.is_file():
                raise IntegrationError(f"project GDS not found: {gds_path}")
            result = {
                "project_gds": str(gds_path.resolve()),
                "selection_source": source,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"Resolved project GDS: {gds_path}")
            return 0

        if args.command == "audit-template":
            audit = audit_physical_template(args.template_cfg)
            print(yaml.safe_dump(audit, sort_keys=False), end="")
            return 0 if audit["valid_for_production"] else 1

        if args.command == "generate-padring":
            info = load_info(args.info_yaml)
            cfg, mapping = generate_padring_config(
                info=info,
                info_path=args.info_yaml,
                template_path=args.template_cfg,
                block=args.block,
                team_code=args.team_code,
                require_complete_template=not args.allow_partial_template,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(cfg, encoding="utf-8")
            write_mapping(args.map_out, mapping)
            if args.map_json_out is not None:
                args.map_json_out.parent.mkdir(parents=True, exist_ok=True)
                args.map_json_out.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
            print(f"Wrote padring config: {args.output}")
            print(f"Wrote pad mapping:    {args.map_out}")
            if args.map_json_out is not None:
                print(f"Wrote JSON mapping:   {args.map_json_out}")
            return 0

        if args.command in {"padring-command", "run-padring"}:
            kwargs = dict(
                padring_exe=args.padring,
                tech_pdk=args.tech_pdk,
                cfg=args.cfg,
                output_def=args.def_out,
                output_svg=args.svg_out,
                output_verilog=args.verilog_out,
                mapping_path=args.mapping,
                def_dbu=args.def_dbu,
            )
            if args.command == "padring-command":
                print(" \\\n  ".join(build_padring_command(**kwargs)))
            else:
                run_padring(**kwargs)
            return 0

        if args.command == "inspect-lef":
            macros = parse_lef_files(args.lef)
            cells = sorted(set(CELL_PROJECT_TERMINALS) & set(macros))
            missing = validate_project_terminals(macros, cells)
            report = {
                "macros": {name: sorted(macros[name].pins) for name in cells},
                "required_project_terminals": {name: list(CELL_PROJECT_TERMINALS[name]) for name in cells},
                "missing": missing,
            }
            print(yaml.safe_dump(report, sort_keys=False), end="")
            return 1 if missing else 0

        if args.command == "generate-project-def":
            mapping = load_mapping(args.mapping)
            pins = mapped_pads(mapping)
            design = load_def(args.padring_def)
            if args.project_size_json is not None:
                if args.project_width is not None or args.project_height is not None:
                    raise IntegrationError(
                        "use either --project-size-json or --project-width/--project-height, not both"
                    )
                try:
                    size_data = json.loads(args.project_size_json.read_text(encoding="utf-8"))
                    project_width = size_data["width_microns"]
                    project_height = size_data["height_microns"]
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise IntegrationError(f"cannot read project size JSON {args.project_size_json}: {exc}") from exc
            else:
                if args.project_width is None or args.project_height is None:
                    raise IntegrationError(
                        "provide --project-size-json or both --project-width and --project-height"
                    )
                project_width, project_height = args.project_width, args.project_height
                size_data = {}
            layout_texts = [
                entry["text"] for entry in size_data.get("top_cell_text", [])
                if isinstance(entry, dict) and isinstance(entry.get("text"), str)
            ]
            micron_to_dbu(project_width, design.units, "project width")
            micron_to_dbu(project_height, design.units, "project height")
            fitting = select_block_variants(
                project_width=project_width,
                project_height=project_height,
                pin_count=len(pins),
            )
            if args.variant:
                selected = BLOCK_VARIANTS[args.variant]
                if selected not in fitting:
                    if (
                        selected.width < Decimal(str(project_width))
                        or selected.height < Decimal(str(project_height))
                        or len(selected.slots) - len(selected.vss_fixed) < len(pins)
                    ):
                        raise IntegrationError(
                            f"variant {selected.code} does not fit the requested project dimensions and pin count"
                        )
                variants = (selected,)
            else:
                variants = fitting
            base_name = safe_identifier(args.design or mapping.get("team_code") or "chipathon_project")
            args.output_dir.mkdir(parents=True, exist_ok=True)
            layers = tuple(args.routing_layers or GF180_ROUTING_LAYERS)
            for variant in variants:
                output = args.output_dir / f"{base_name}_{variant.code}.def"
                interface_map = args.output_dir / f"{base_name}_{variant.code}_interface.yaml"
                text, metadata = generate_project_def(
                    mapping_path=args.mapping,
                    padring_def=args.padring_def,
                    lef_paths=args.lef,
                    variant_code=variant.code,
                    design_name=f"{base_name}_{variant.code}",
                    routing_layers=layers,
                    layout_texts=layout_texts,
                )
                output.write_text(text, encoding="utf-8")
                interface_map.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
                print(f"Wrote project DEF:    {output}")
                print(f"Wrote interface map:  {interface_map}")
            return 0

        if args.command == "build-project-defs":
            info = load_info(args.info_yaml)
            pins = validate_pins(info)
            try:
                size_data = json.loads(args.project_size_json.read_text(encoding="utf-8"))
                project_width = size_data["width_microns"]
                project_height = size_data["height_microns"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                raise IntegrationError(f"cannot read project size JSON {args.project_size_json}: {exc}") from exc
            layout_texts = [
                entry["text"] for entry in size_data.get("top_cell_text", [])
                if isinstance(entry, dict) and isinstance(entry.get("text"), str)
            ]
            variants = select_block_variants(
                project_width=project_width,
                project_height=project_height,
                pin_count=len(pins),
            )
            layers = tuple(args.routing_layers or GF180_ROUTING_LAYERS)
            lef_paths = required_lef_paths(args.tech_pdk)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            selection_path = args.output_dir / f"{args.team_code}_selected_variants.json"
            selection_path.write_text(json.dumps({
                "project_size": size_data,
                "participant_pin_count": len(pins),
                "selected_variants": [variant.code for variant in variants],
            }, indent=2) + "\n", encoding="utf-8")
            for variant in variants:
                variant_dir = args.output_dir / variant.code
                cfg_path = variant_dir / f"{args.team_code}_{variant.code}_padring.cfg"
                mapping_path = variant_dir / f"{args.team_code}_{variant.code}_pad_map.yaml"
                def_path = variant_dir / f"{args.team_code}_{variant.code}_padring.def"
                svg_path = variant_dir / f"{args.team_code}_{variant.code}_padring.svg"
                verilog_path = variant_dir / f"{args.team_code}_{variant.code}_padring.v"
                cfg, mapping = generate_padring_config(
                    info=info,
                    info_path=args.info_yaml,
                    template_path=args.template_cfg,
                    block=variant.code,
                    team_code=f"{args.team_code}_{variant.code}",
                )
                variant_dir.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(cfg, encoding="utf-8")
                write_mapping(mapping_path, mapping)
                run_padring(
                    padring_exe=args.padring,
                    tech_pdk=args.tech_pdk,
                    cfg=cfg_path,
                    output_def=def_path,
                    output_svg=svg_path,
                    output_verilog=verilog_path,
                    mapping_path=mapping_path,
                    def_dbu=args.def_dbu,
                )
                project_text, interface = generate_project_def(
                    mapping_path=mapping_path,
                    padring_def=def_path,
                    lef_paths=lef_paths,
                    variant_code=variant.code,
                    design_name=f"{args.team_code}_{variant.code}",
                    routing_layers=layers,
                    layout_texts=layout_texts,
                )
                interface["project_gds_size"] = size_data
                interface["participant_pin_count"] = len(pins)
                project_path = variant_dir / f"{args.team_code}_{variant.code}.def"
                interface_path = variant_dir / f"{args.team_code}_{variant.code}_interface.yaml"
                project_path.write_text(project_text, encoding="utf-8")
                interface_path.write_text(yaml.safe_dump(interface, sort_keys=False), encoding="utf-8")
                print(f"Wrote {variant.code} project DEF: {project_path}")
            print(f"Wrote variant selection: {selection_path}")
            return 0

        if args.command == "show-config":
            print(yaml.safe_dump({
                "spec_blob_sha": SPEC_BLOB_SHA,
                "io_cells": IO_CELLS,
                "A_SLOTS": list(A_SLOTS),
                "project_def_variants": {
                    code: {
                        "slots": list(variant.slots),
                        "origin_microns": [str(value) for value in variant.origin],
                        "size_microns": [str(variant.width), str(variant.height)],
                        "area": variant.area,
                        "vss_fixed": list(variant.vss_fixed),
                    }
                    for code, variant in BLOCK_VARIANTS.items()
                },
                "project_terminals": {k: list(v) for k, v in CELL_PROJECT_TERMINALS.items()},
            }, sort_keys=False), end="")
            return 0

        raise AssertionError(args.command)
    except IntegrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
