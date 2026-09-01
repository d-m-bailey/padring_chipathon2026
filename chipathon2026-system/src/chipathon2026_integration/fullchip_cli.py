from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from .errors import ConfigError, IntegrationError
from .fullchip import (
    build_placements,
    discover_project,
    file_sha256,
    generate_chip_padring,
    json_dump,
    load_chip_request,
    rewrite_pin_csv,
    write_integrated_def,
    write_top_verilog,
)
from .padring_runner import required_lef_paths, run_padring


SYSTEM_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = SYSTEM_ROOT.parent


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Chipathon 2026 full-chip integration")
    p.add_argument("integration_yaml", type=Path)
    p.add_argument("--base-chip", type=Path, help="override only the base-chip YAML path")
    p.add_argument("--info-root", type=Path, default=Path("info"))
    p.add_argument("--project-root", type=Path, default=Path("build/padframes"))
    p.add_argument("--gds-root", type=Path, default=Path("gds"))
    p.add_argument("--template", type=Path, default=SYSTEM_ROOT / "padring_template.cfg")
    p.add_argument("--padring", type=Path, required=True)
    p.add_argument("--tech-pdk", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--klayout", type=Path, default=Path("klayout"))
    p.add_argument("--def2stream", type=Path, default=REPOSITORY_ROOT / "Workshop_CASS/def2stream.py")
    p.add_argument("--gds-script", type=Path, default=SYSTEM_ROOT / "scripts/fullchip_gds.py")
    p.add_argument("--def-dbu", type=float, default=0.005)
    p.add_argument("--outline-layer", type=int, default=0)
    p.add_argument("--outline-datatype", type=int, default=0)
    p.add_argument("--pin-text-layer", type=int, default=81)
    p.add_argument("--pin-text-datatype", type=int, default=10)
    p.add_argument("--pad-marker-layer", type=int, default=37)
    p.add_argument("--pad-marker-datatype", type=int, default=0)
    p.add_argument("--validation-only", action="store_true")
    return p


def _run(command: list[str], context: str) -> None:
    try:
        subprocess.run(command, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigError(f"{context} failed: {exc}") from exc


def _inspection_manifest(artifacts) -> dict:
    return {
        "projects": [
            {"team": artifact.request.team, "gds_path": str(artifact.gds_path)}
            for artifact in artifacts
        ]
    }


def _placement_doc(chip, placement) -> dict:
    request = placement.artifacts.request
    variant = chip.variant(request.variant)
    return {
        "team": request.team,
        "variant": request.variant,
        "quadrant": request.quadrant,
        "pin_count": len(placement.artifacts.pins),
        "info_path": str(placement.artifacts.info_path),
        "lvs_config_path": str(placement.artifacts.lvs_config_path),
        "gds_path": str(placement.artifacts.gds_path),
        "canonical_def": str(placement.artifacts.def_path),
        "interface_metadata": str(placement.artifacts.interface_path),
        "source_top": placement.source_top,
        "integrated_top": placement.integrated_top,
        "origin_microns": [str(value) for value in variant.origin],
        "size_microns": [str(variant.width), str(variant.height)],
        "prboundary_microns": [str(value) for value in placement.prboundary],
        "transformed_boundary_microns": [str(value) for value in placement.transformed_boundary],
        "canonical_slots": list(variant.slots[:len(placement.artifacts.pins)]),
        "transformed_slots": list(placement.transformed_slots),
    }


def _write_report(path: Path, chip, placements, status: str, errors=None) -> None:
    lines = [
        f"Chip: {chip.name}", f"Floorplan: {chip.floorplan}",
        f"Minimum project gap: {chip.minimum_gap} um", f"Status: {status}", "",
    ]
    for placement in placements:
        doc = _placement_doc(chip, placement)
        lines.extend([
            f"[{doc['team']}] {doc['variant']} {doc['quadrant']}",
            f"  PR boundary: {doc['prboundary_microns']}",
            f"  Transformed: {doc['transformed_boundary_microns']}",
            f"  Slots: {', '.join(doc['transformed_slots'])}",
        ])
    if errors:
        lines.extend(["", "Errors:", *[f"  - {error}" for error in errors]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    chip = None
    try:
        chip = load_chip_request(args.integration_yaml, base_chip_override=args.base_chip)
        output = args.output_root
        output.mkdir(parents=True, exist_ok=True)
        artifacts = tuple(
            discover_project(
                request, base_chip=chip.base_chip, info_root=args.info_root,
                project_root=args.project_root,
                gds_root=args.gds_root,
            )
            for request in chip.projects
        )
        inspect_manifest_path = output / f"{chip.name}_gds_inputs.json"
        measurements_path = output / f"{chip.name}_measurements.json"
        json_dump(inspect_manifest_path, _inspection_manifest(artifacts))
        _run([
            str(args.klayout), "-b", "-rd", "mode=inspect",
            "-rd", f"manifest={inspect_manifest_path}", "-rd", f"output={measurements_path}",
            "-rd", f"outline_layer={args.outline_layer}",
            "-rd", f"outline_datatype={args.outline_datatype}", "-r", str(args.gds_script),
        ], "project GDS inspection")
        measurements = json.loads(measurements_path.read_text(encoding="utf-8"))
        placements = build_placements(chip, artifacts, measurements)
        cfg, mapping = generate_chip_padring(chip, placements, args.template)

        cfg_path = output / f"{chip.name}_padring.cfg"
        map_yaml = output / f"{chip.name}_pad_map.yaml"
        map_json = output / f"{chip.name}_pad_map.json"
        manifest_path = output / f"{chip.name}_placement_manifest.json"
        report_json = output / f"{chip.name}_validation.json"
        report_text = output / f"{chip.name}_validation.txt"
        cfg_path.write_text(cfg, encoding="utf-8")
        map_yaml.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
        json_dump(map_json, mapping)
        placement_docs = [_placement_doc(chip, placement) for placement in placements]
        validation = {
            "status": "valid", "chip": chip.name,
            "base_chip": {
                "name": chip.base_chip.name,
                "path": str(chip.base_chip.path),
                "sha256": file_sha256(chip.base_chip.path),
                "diearea_microns": [str(value) for value in chip.diearea],
                "io_cells": chip.io_cells,
            },
            "checks": {
                "integration_and_base_chip_schema": "pass",
                "base_chip_variant_and_io_mapping": "pass",
                "artifact_discovery": "pass",
                "pin_capacity_and_endpoint_constraints": "pass",
                "prboundary_origin_and_size": "pass", "chip_containment": "pass",
                "project_overlap_and_gap": "pass", "physical_slot_uniqueness": "pass",
            },
            "projects": placement_docs,
        }
        json_dump(report_json, validation)
        _write_report(report_text, chip, placements, "VALID")
        if args.validation_only:
            json_dump(manifest_path, {
                "schema_version": 1, "chip_name": chip.name, "validation_only": True,
                "base_chip_name": chip.base_chip.name,
                "base_chip_path": str(chip.base_chip.path),
                "base_chip_sha256": file_sha256(chip.base_chip.path),
                "projects": placement_docs, "validation_report": str(report_json),
            })
            print(f"Validated full-chip integration: {chip.name}")
            return 0

        ring_def = output / f"{chip.name}_padring.def"
        ring_svg = output / f"{chip.name}_padring.svg"
        ring_verilog = output / f"{chip.name}_padring.v"
        ring_gds = output / f"{chip.name}_padring.gds"
        raw_csv = output / f"{chip.name}_padring_raw.csv"
        pin_csv = output / f"{chip.name}_pins.csv"
        run_padring(
            padring_exe=args.padring, tech_pdk=args.tech_pdk, cfg=cfg_path,
            output_def=ring_def, output_svg=ring_svg, output_verilog=ring_verilog,
            mapping_path=map_yaml, def_dbu=args.def_dbu,
        )
        lef_paths = required_lef_paths(args.tech_pdk)
        io_gds = args.tech_pdk / "libs.ref/gf180mcu_fd_io/gds/gf180mcu_fd_io.gds"
        tech_file = args.tech_pdk / "libs.tech/klayout/tech/gf180mcu.lyt"
        layer_map = args.tech_pdk / "libs.tech/klayout/tech/gf180mcu.map"
        _run([
            str(args.klayout), "-zz", "-rd", f"design_name={chip.name}_padring",
            "-rd", f"in_def={ring_def}", "-rd", "lef_files=" + " ".join(map(str, lef_paths)),
            "-rd", f"in_files={io_gds}", "-rd", "seal_file=", "-rd", f"out_file={ring_gds}",
            "-rd", f"tech_file={tech_file}", "-rd", f"layer_map={layer_map}",
            "-rd", f"output_dbu={args.def_dbu}", "-rd", f"csv_file={raw_csv}",
            "-rd", f"mapping_file={map_json}", "-rd", f"marker_layer={args.pad_marker_layer}",
            "-rd", f"marker_datatype={args.pad_marker_datatype}", "-r", str(args.def2stream),
        ], "chip padring GDS conversion")
        pin_rows = rewrite_pin_csv(raw_csv, pin_csv, placements)
        integrated_def = output / f"{chip.name}.def"
        top_verilog = output / f"{chip.name}.v"
        integrated_gds = output / f"{chip.name}.gds"
        cell_map = output / f"{chip.name}_cell_names.json"
        write_integrated_def(integrated_def, chip, placements, ring_def)
        write_top_verilog(top_verilog, chip, placements)
        gds_manifest = {
            "chip_name": chip.name,
            "chip_diearea_microns": [str(value) for value in chip.diearea],
            "dbu_microns": str(args.def_dbu), "padring_gds": str(ring_gds),
            "padring_top": f"{chip.name}_padring", "pin_csv": str(pin_csv),
            "pin_text_layer": args.pin_text_layer, "pin_text_datatype": args.pin_text_datatype,
            "cell_name_map": str(cell_map), "projects": placement_docs,
        }
        gds_manifest_path = output / f"{chip.name}_gds_manifest.json"
        json_dump(gds_manifest_path, gds_manifest)
        _run([
            str(args.klayout), "-b", "-rd", "mode=build",
            "-rd", f"manifest={gds_manifest_path}", "-rd", f"output={integrated_gds}",
            "-r", str(args.gds_script),
        ], "integrated GDS assembly")
        outputs = [cfg_path, map_yaml, map_json, ring_def, ring_verilog, ring_gds, pin_csv, integrated_def, top_verilog, integrated_gds, report_json, report_text]
        manifest = {
            "schema_version": 1, "chip_name": chip.name,
            "base_chip_name": chip.base_chip.name,
            "base_chip_path": str(chip.base_chip.path),
            "base_chip_sha256": file_sha256(chip.base_chip.path),
            "diearea_microns": [str(v) for v in chip.diearea],
            "io_cells": chip.io_cells,
            "minimum_project_gap_microns": str(chip.minimum_gap), "projects": placement_docs,
            "pin_count": len(pin_rows), "pin_text_layer": [args.pin_text_layer, args.pin_text_datatype],
            "validation_report": str(report_json),
            "inputs": {
                str(path): file_sha256(path)
                for path in [args.integration_yaml, chip.base_chip.path, args.template]
                + [item for placement in placements for item in (
                    placement.artifacts.info_path, placement.artifacts.lvs_config_path,
                    placement.artifacts.gds_path, placement.artifacts.def_path,
                    placement.artifacts.interface_path,
                )]
            },
            "outputs": {str(path): file_sha256(path) for path in outputs},
        }
        json_dump(manifest_path, manifest)
        print(f"Built full-chip integration: {integrated_gds}")
        return 0
    except (IntegrationError, OSError, json.JSONDecodeError) as exc:
        try:
            args.output_root.mkdir(parents=True, exist_ok=True)
            report_name = chip.name if chip is not None else args.integration_yaml.stem
            json_dump(args.output_root / f"{report_name}_validation.json", {
                "status": "invalid", "errors": [str(exc)],
            })
            (args.output_root / f"{report_name}_validation.txt").write_text(
                f"Status: INVALID\n\nErrors:\n  - {exc}\n", encoding="utf-8"
            )
        except OSError:
            pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
