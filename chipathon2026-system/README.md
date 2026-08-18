# Chipathon 2026 Padframe Integration System

Python implementation recreated from the live `ChatGPT_spec.md` in
`d-m-bailey/padring_chipathon2026` on branch `chipathon2026`.

## What is implemented

- Parse and validate participant `info.yaml`.
- Require `project.lvs_config` and read the existing cf-precheck JSON format.
- Resolve `$KEY`, `${KEY}`, and `$UPRJ_ROOT` references in `LAYOUT_FILE`.
- Map the documented `io_type` values to GF180MCU I/O cells.
- Use the explicit authoritative A-block sequence:
  `W13..W22, N01..N11`.
- Parse a YosysHQ padring `.cfg` as the sole physical-geometry source.
- Require immutable physical slot instance names `N01..N22`, `E01..E22`,
  `S01..S22`, `W01..W22` for production generation.
- Preserve unrelated PAD entries, comments, side, `FLIP`, AREA/GRID/CORNER/
  FILLER/LOC/SPACE directives.
- Replace only selected A-block user slots and make unused A slots
  `gf180mcu_fd_io__asig_5p0` placeholders.
- Detect malformed YAML, unsupported types, duplicate user pins, missing or
  illegal `secondary_esd`, too many pins, sanitization collisions, missing
  slots, fixed-instance collisions, and missing cell mappings.
- Generate machine-readable pin-to-slot metadata.
- Build/run YosysHQ padring with every LEF required by the current cell map.
- Parse GF180 LEF pin geometry and validate the project-facing terminal set.
- Generate an operator-gated virtual-interface DEF from a padring-generated DEF
  plus LEF geometry; because the canonical project DIEAREA is not finalized,
  `--diearea` is mandatory.
- Download `info.yaml -> project.lvs_config -> LAYOUT_FILE -> GDS` from GitHub,
  fetching fresh metadata even when local copies already exist.

## Important strictness

The current repository's `Workshop_CASS/padring/workshop_padring.cfg` is a legacy
physical template. It uses `ana*`/`config*` instance names rather than immutable
`N01/E01/S01/W01` slot names. The production converter rejects it instead of
silently assigning physical slot identities that the specification says must be
explicit.

Run:

```bash
chipathon-integrate audit-template Workshop_CASS/padring/workshop_padring.cfg
```

Once the production template itself uses immutable slot names, the A-block flow
is:

```bash
chipathon-integrate generate-padring \
  info.yaml physical_88pad.cfg \
  --block A \
  -o build/project_padring.cfg \
  --map-out build/project_pad_map.yaml
```

Then invoke padring:

```bash
chipathon-integrate run-padring \
  --padring /path/to/padring \
  --tech-pdk "$TECH_PDK" \
  --cfg build/project_padring.cfg \
  --def-out build/project_padring.def \
  --svg-out build/project_padring.svg \
  --verilog-out build/project_padring.v
```

The `Makefile.padframe` GDS stage also writes a `name,type,x,y` CSV. Its
coordinates are the transformed center of the single square on GDS layer
`37/0` in each I/O macro, in microns; they are not inferred from the LEF macro
bounding box.

To generate the project-side virtual DEF, supply the canonical block DIEAREA
once integration has chosen it:

```bash
chipathon-integrate generate-virtual-def \
  --mapping build/project_pad_map.yaml \
  --padring-def build/project_padring.def \
  --lef "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__in_c.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__in_s.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__bi_t.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__bi_24t.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__asig_5p0.lef \
  --diearea 0,0,1467500,1467500 \
  -o build/project_interface.def \
  --interface-map build/project_interface.yaml
```

The numeric DIEAREA above is only command syntax illustration; it is **not** a
specification value.

## Download flow

```bash
python3 -u scripts/download_chipathon_gds_v2.py \
  --info-dir info \
  --gds-dir gds \
  --overwrite \
  repo.list 2>&1 | tee download.report
```

The script also calls `sys.stdout.reconfigure(line_buffering=True)` as specified.

## Install and test

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

See `SPEC_GAPS.md` before treating any B-E block, package mapping, transform, or
power-polarity behavior as finalized.
