# Chipathon 2026 Padframe Integration System

Python implementation recreated from the live `ChatGPT_spec.md` in
`d-m-bailey/padring_chipathon2026` on branch `chipathon2026`.

## What is implemented

- Parse and validate participant `info.yaml`.
- Require `project.lvs_config` and read the existing cf-precheck JSON format.
- Resolve `$KEY`, `${KEY}`, and `$UPRJ_ROOT` references in `LAYOUT_FILE`.
- Map the documented `io_type` values to GF180MCU I/O cells.
- Use the definitive block-variant slot orders. The A participant sequence is
  `W12..W22, N01..N11`; every listed slot is participant-configurable.
- Parse a YosysHQ padring `.cfg` as the sole physical-geometry source.
- Require immutable physical slot instance names `N01..N22`, `E01..E22`,
  `S01..S22`, `W01..W22` for production generation.
- Preserve unrelated PAD entries, comments, side, `FLIP`, AREA/GRID/CORNER/
  FILLER/LOC/SPACE directives.
- Replace only selected block-variant user slots and make unused selected slots
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
  --team-code A01 \
  -o build/project_padring.cfg \
  --map-out build/project_pad_map.yaml \
  --map-json-out build/project_pad_map.json
```

Then invoke padring:

```bash
chipathon-integrate run-padring \
  --padring /path/to/padring \
  --tech-pdk "$TECH_PDK" \
  --cfg build/project_padring.cfg \
  --def-out build/project_padring.def \
  --svg-out build/project_padring.svg \
  --mapping build/project_pad_map.yaml \
  --verilog-out build/project_padring.v
```

Padring components retain canonical slot names such as `W01`. The generated
DEF and Verilog expose user-area terminals such as `W01_A`; project virtual
DEF terminals use the participant name instead, such as `RST_A`.
The layout top cell and Verilog module are named `<team-code>_padring`, such as
`A01_padring`.

The Verilog physical-pad ports use bare canonical names such as `W01`. E11,
E12, W11, and W12 are ordinary participant-configurable positions rather than
fixed ground pads. The common ground net is named from an actual participant
DVSS pad. Each DVDD pad
inherently breaks the `VDD`/`DVDD` rails and names its resulting power segment
with its canonical pad name. `BREAK ;` controls the additional physical
`brk5` isolation rather than creating the DVDD-pad electrical discontinuity.
Unpowered regions use unique explicit nets such as `FLOAT_VDD_1`. Every
break-delimited project group contains exactly one participant power pad and
one participant ground pad. Generation adds a break before the first project
I/O and after the last. A second power or second ground causes a break before
that pad and resets both group counters. The physical template contains no
fixed breaks.

The generated padring DEF has an `INOUT` Metal5 pin at the physical pad
location for every canonical slot. DVDD and DVSS canonical pins also contain
their transformed user-area-facing Metal2 LEF geometry and are marked `USE
POWER` or `USE GROUND`.

The structural Verilog includes every DEF component for LVS, including
device-containing `fill5`, `brk5`, and corner cells. Their available supply
ports connect to the common ground and neighboring canonical DVDD segment;
`brk5` connects only its available VSS port and does not bridge DVDD.
Filler instances use location-based names such as `FILL_E00_1` and
`BRK_E10_1` in both DEF and Verilog.

The template selects `fill5` with `FILLER`, selects `brk5` with `BREAKFILLER`,
and uses a parameterless `BREAK ;` between selected I/O cells. The normal gap
width is preserved, but every filler cell in that gap is `brk5` rather than
`fill5`.

The `Makefile.padframe` GDS stage also writes a
`canonical_pin_name,project_pin_name,type,x,y` CSV. Project pin names are
prefixed by the team code, for example `A01_RST`. Its
coordinates are the transformed center of the single square on GDS layer
`37/0` in each I/O macro, in microns; they are not inferred from the LEF macro
bounding box.

To generate canonical project DEFs, provide the implemented project dimensions
in microns. The command selects every minimum-area fitting configuration and
writes one DEF and one interface-mapping YAML per selected variant:

```bash
chipathon-integrate generate-project-def \
  --mapping build/project_pad_map.yaml \
  --padring-def build/project_padring.def \
  --lef "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__in_c.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__in_s.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__bi_t.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__bi_24t.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__asig_5p0.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__dvdd.lef \
        "$TECH_PDK"/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__dvss.lef \
  --project-width 500 \
  --project-height 500 \
  --output-dir build/project_defs
```

Use `--variant CODE` to request one particular fitting variant. By default,
GF180 Metal1 through Metal5 are blocked wherever a variant defines a blockage;
repeat `--routing-layer` to override that layer list. Coordinates are accepted
in microns and must be exactly representable in the padring DEF database grid.
Pin geometry is read from named padring DEF pins. Each project pin starts at
the I/O terminal's innermost block boundary, extends 1 micron into the block,
and is translated to a local DIEAREA beginning at `(0,0)`. Rectangle portions
outside that DIEAREA are clipped; wholly outside rectangles are omitted as long
as another positive-area rectangle remains for the terminal.
EV/CV require the first participant I/O to be power or ground, while EH/CH
require the last participant I/O to be power or ground. Incompatible variants
are excluded from automatic selection and rejected when explicitly requested.
BV, BH, D, ACV, ACH, and ACE also emit their specified Metal2-only corner
routing blockages; D and ACE have both lower-left and upper-right blockages.
Input-pad `Y` terminals use the bare user pad name. Bidirectional `Y` and `A`
terminals use `<pad>_IN` and `<pad>_OUT`, respectively; other terminal names
retain their cell-terminal suffix.
Control-terminal names default to the I/O-cell terminal case, such as
`DATA_OE`. If direct text in the selected project GDS top cell matches the
complete signal name case-insensitively, the project DEF uses that exact text
spelling instead (for example, `DATA_oe`). Conflicting spellings such as both
`DATA_OE` and `DATA_oe` are rejected. Interface metadata records both names.
For bus pins, the qualifier is inserted before the unchanged bracket suffix:
`DATA[0]` produces `DATA_PU[0]`, `DATA_PD[0]`, `DATA_IN[0]`, and
`DATA_OUT[0]` as applicable. Malformed bracket syntax is rejected.

The Makefile derives those dimensions automatically from the single top-cell
rectangle on GDS layer `0/0` and combines them with the info.yaml pin count:

```bash
make -f chipathon2026-system/Makefile.padframe project-def-A01
```

By default it reads `info/A01_lvs_config.json`, expands its `LAYOUT_FILE`, and
uses the matching downloaded basename under `gds/A01/`; directory ordering is
never used. The downloader writes this retained LVS-config copy. Existing
download directories must be refreshed, or supplied with
`PROJECT_LVS_CONFIG=/path/to/lvs_config.json`. `PROJECT_GDS=/path/to/project.gds`
remains an explicit override. The outline layer is overrideable with
`PROJECT_OUTLINE_LAYER` and `PROJECT_OUTLINE_DATATYPE`. One variant-specific
padring and project DEF are written for every minimum-area fitting block type.

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
