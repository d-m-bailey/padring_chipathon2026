from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .constants import A_SLOTS, CELL_PROJECT_TERMINALS, IO_CELLS, SPEC_BLOB_SHA
from .errors import IntegrationError
from .info import get_lvs_config_reference, load_info, validate_pins
from .lef import parse_lef_files, validate_project_terminals
from .lvs import get_layout_file, load_lvs_config
from .padring_cfg import audit_physical_template, generate_padring_config, write_mapping
from .padring_runner import build_padring_command, run_padring
from .virtual_def import generate_virtual_def


def _diearea(value: str) -> tuple[int, int, int, int]:
    try:
        parts = tuple(int(x.strip()) for x in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("diearea must be x1,y1,x2,y2 in DEF database units") from exc
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("diearea must contain exactly four integers")
    return parts  # type: ignore[return-value]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Chipathon 2026 GF180 padframe integration tools")
    p.add_argument("--spec-sha", action="store_true", help="print the pinned live-spec blob SHA and exit")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("validate-info", help="validate participant info.yaml")
    s.add_argument("info_yaml", type=Path)

    s = sub.add_parser("inspect-lvs", help="resolve project.lvs_config and LAYOUT_FILE")
    s.add_argument("info_yaml", type=Path)
    s.add_argument("--uprj-root")

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

    s = sub.add_parser("generate-virtual-def", help="generate project-side pin constraint DEF from padring DEF and LEFs")
    s.add_argument("--mapping", type=Path, required=True)
    s.add_argument("--padring-def", type=Path, required=True)
    s.add_argument("--lef", type=Path, nargs="+", required=True)
    s.add_argument("--diearea", type=_diearea, required=True, help="x1,y1,x2,y2 in DEF database units; spec has not finalized this")
    s.add_argument("-o", "--output", type=Path, required=True)
    s.add_argument("--interface-map", type=Path, required=True)
    s.add_argument("--design", default="chipathon_project_interface")

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

        if args.command == "generate-virtual-def":
            text, metadata = generate_virtual_def(
                mapping_path=args.mapping,
                padring_def=args.padring_def,
                lef_paths=args.lef,
                diearea=args.diearea,
                design_name=args.design,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            args.interface_map.parent.mkdir(parents=True, exist_ok=True)
            args.interface_map.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
            print(f"Wrote virtual DEF:    {args.output}")
            print(f"Wrote interface map:  {args.interface_map}")
            return 0

        if args.command == "show-config":
            print(yaml.safe_dump({
                "spec_blob_sha": SPEC_BLOB_SHA,
                "io_cells": IO_CELLS,
                "A_SLOTS": list(A_SLOTS),
                "project_terminals": {k: list(v) for k, v in CELL_PROJECT_TERMINALS.items()},
            }, sort_keys=False), end="")
            return 0

        raise AssertionError(args.command)
    except IntegrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
