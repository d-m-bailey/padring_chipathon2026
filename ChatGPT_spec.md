# **Chipathon 2026** **Padframe Integration Specification**

*Consolidated working specification for padframe, I/O, padring, DEF, and project integration*

*This document is intended to be editable and reusable as the starting context for a new development chat.*

# **1\. Objective**

Develop a Python-based integration system for the 2026 SSCS Chipathon using the GF180MCU process.

The system must:

1\. Read each project's info.yaml.

2\. Locate the project's existing lvs\_config.json.

3\. Use the existing cf-precheck lvs\_config.json format without redefining it.

4\. Read the project's I/O pin definitions from info.yaml.

5\. Convert those pin definitions into GF180MCU I/O pad cells.

6\. Generate a YosysHQ padring configuration from a fixed physical padframe template.

7\. Generate the project-side DEF / virtual padframe used as an implementation constraint.

8\. Allow a completed project to be transformed into any valid physical block location on the final die without rerouting its project-side interface.

9\. Ultimately generate the final top-level padframe and project placement.

The target I/O library is:

gf180mcu\_fd\_io

The padring generator is:

https://github.com/YosysHQ/padring

# **2\. Existing lvs\_config.json**

The lvs\_config.json format is already defined by cf-precheck. Do not create a new format.

The authoritative specification is the existing ChipFoundry cf-precheck documentation.

info.yaml identifies the file as:

project:  
  lvs\_config: "lvs\_config.json"

or, if stored elsewhere:

project:  
  lvs\_config: "lvs/my\_design/lvs\_config.json"

The parser must therefore access:

config\["project"\]\["lvs\_config"\]

or defensively:

config.get("project", {}).get("lvs\_config")

The integration program then reads the referenced lvs\_config.json.

The existing configuration contains the layout information such as:

TOP\_LAYOUT  
LAYOUT\_FILE

and other cf-precheck parameters.

Variable references such as:

$TOP\_SOURCE  
${TOP\_SOURCE}  
$UPRJ\_ROOT

may need to be resolved according to the existing precheck conventions.

# **3\. info.yaml pin specification**

The participant-facing YAML must remain simple.

Example:

project:  
  title: "Example Project"  
  team: "Example Team"  
  description: \>  
    Example project.  
  lvs\_config: "lvs\_config.json"

pins:  
  \- name: reset\_n  
    io\_type: input\_cmos

  \- name: clock  
    io\_type: input\_schmitt

  \- name: gpio0  
    io\_type: bidirectional

  \- name: high\_drive\_gpio  
    io\_type: bidirectional\_24ma

  \- name: "sensor\[0\]"  
    io\_type: analog  
    secondary\_esd: true

Each pins: entry represents exactly one physical I/O cell.

The order of entries in pins: is significant.

pins:  
  \- name: first\_pin  
    io\_type: bidirectional

  \- name: second\_pin  
    io\_type: bidirectional

This means first\_pin is assigned to the first available physical project pad slot and second\_pin to the next one.

# **4\. Pin-name quoting**

Simple pin names do not require quotes:

\- name: reset\_n  
  io\_type: input\_cmos

Pin names containing punctuation should preferably be quoted:

\- name: "data\[7\]"  
  io\_type: bidirectional

This is especially important when YAML flow syntax is used:

\- { name: "data\[7\]", io\_type: bidirectional }

because this is invalid or ambiguous:

\- { name: data\[7\], io\_type: bidirectional }

Block-style YAML is preferred.

# **5\. Supported io\_type values**

The integration system maintains the mapping from user-facing io\_type to GF180 I/O cell.

Initial mapping:

| io\_type | GF180 cell |
| :---- | :---- |
| input\_cmos | gf180mcu\_fd\_io\_\_in\_c |
| input\_schmitt | gf180mcu\_fd\_io\_\_in\_s |
| bidirectional | gf180mcu\_fd\_io\_\_bi\_t |
| bidirectional\_24ma | gf180mcu\_fd\_io\_\_bi\_24t |
| analog | gf180mcu\_fd\_io\_\_asig\_5p0 |
| power | gf180mcu\_fd\_io\_\_dvdd |
| ground | gf180mcu\_fd\_io\_\_dvss |

The mapping must be maintained in the integration code rather than duplicated in every user's YAML.

# **6\. Output-only signals**

A separate output-only io\_type is not required unless a distinct physical GF180 I/O cell is later selected.

Normal digital outputs may use:

gf180mcu\_fd\_io\_\_bi\_t  
gf180mcu\_fd\_io\_\_bi\_24t

with the project itself driving the I/O-cell control terminals appropriately.

The integration system must not synthesize output-enable logic on behalf of the project.

# **7\. Pad control signals belong to the project**

All functional and control inputs of an I/O cell are the responsibility of the project.

Examples include, where applicable:

OE  
IE  
PU  
PD  
CS  
SL  
PDRV0  
PDRV1

and similar I/O-cell control terminals.

The integration layer must not automatically generate:

* pull-up control logic;  
* pull-down control logic;  
* output-enable control;  
* input-enable control;  
* slew-rate control;  
* drive-strength control;  
* POR control;  
* startup logic.

The generated project DEF must expose the necessary project-side connections for the chosen physical I/O cell.

The exact terminal list must come from the authoritative GF180 cell definitions.

# **8\. Analog secondary\_esd**

For io\_type: analog, the YAML must explicitly contain secondary\_esd: true or secondary\_esd: false.

\- name: ain  
  io\_type: analog  
  secondary\_esd: true

secondary\_esd is prohibited for non-analog pad types.

The value does not change the perimeter I/O cell:

gf180mcu\_fd\_io\_\_asig\_5p0

It is metadata used later to determine whether additional internal ESD protection is required.

# **9\. Power architecture**

The intended system architecture is:

* common chip-wide VSS/ground;  
* independent positive supply domains for individual projects or project blocks.

The purpose of separate positive supplies is to prevent a failed or shorted project from disturbing the other projects on the die.

Do not assume a common VDD or VDDIO across all projects.

Shared digital inputs across independently powered project domains are therefore not part of the baseline architecture.

# **10\. Physical die padframe**

The die has 88 physical I/O positions, with 22 pads per side.

Use immutable physical slot names.

N01 ... N22  
E01 ... E22  
S01 ... S22  
W01 ... W22

For the left and right sides, numbering is explicitly defined from bottom to top:

W01 \= bottom-most left pad  
W22 \= top-most left pad

E01 \= bottom-most right pad  
E22 \= top-most right pad

The top/bottom numbering direction should likewise be explicitly documented in the physical template rather than inferred from clockwise/counter-clockwise terminology.

Physical slot names should remain constant even if the cell occupying the slot changes.

For example, W13 always means the same physical pad location.

# **11\. Reserved middle power/ground pads**

The middle two pads on the left and right edges are reserved for power and ground.

With 22 pads per side, these are positions 11 and 12 on each vertical side.

W11  
W12  
E11  
E12

These are not general project signal pad slots.

All four reserved cells are VSS pads:

* W11 \= VSS
* W12 \= VSS
* E11 \= VSS
* E12 \= VSS

These cells are owned by the integration template and must not be replaced when translating user pins.

The fixed middle ground regions use gf180mcu\_fd\_io\_\_brk5 cells at
these two boundaries:

* between W11 and W12;
* between E11 and E12.

These two invariant break cells belong in the physical padring template because
their positions do not depend on participant data.

Each electrically continuous project power region may contain at most one
project power pad and one project ground pad. A second power pad or a second
ground pad starts a new region and requires a break immediately before that
pad. This groups an ordered power/ground sequence into pairs: for example,
power, ground, power, ground produces a break before the second power pad.
Every project also ends with a break. DVDD pads inherently divide the VDD/DVDD
rails into distinct electrical segments.

Additional gf180mcu\_fd\_io\_\_brk5 cells are generated dynamically:

* immediately after the final I/O pad allocated to each project;
* immediately before a power pad when the current region already contains a
  project power pad;
* immediately before a ground pad when the current region already contains a
  project ground pad.

Dynamic break placement belongs in the template-transformation logic because
project length and participant power-pad count come from info.yaml. A break cell
is auxiliary physical geometry: it is not one of the 88 immutable I/O slots, it
does not consume a participant pin, and it must not appear in the pad-center CSV.

At every fixed or dynamic break boundary, `brk5` replaces all `fill5` filler
cells in that gap; it is not added alongside them. The padring configuration
language provides separate default filler families and a parameterless break
directive. The resulting sequence is conceptually:

```text
FILLER gf180mcu_fd_io__fill5 ;
BREAKFILLER gf180mcu_fd_io__brk5 ;

PAD <preceding-io> ... ;
BREAK ;
PAD <following-io> ... ;
```

`BREAK ;` preserves the ordinary automatically calculated gap width but fills
the complete gap using only the `BREAKFILLER` family. It must not introduce an
additional cell or fixed space, and no default `FILLER` cell may occur in that
gap. For example, a 25-micron gap uses five `brk5` cells.

# **12\. Quadrant placement**

Projects are placed in die quadrants.

Each block type has a canonical floorplan.

A participant implements against the canonical floorplan. A final project placement elsewhere on the die is a geometric transformation of that canonical placement.

This allows the same project layout to be placed in multiple legal locations while preserving alignment between:

* project-side interface;  
* I/O cells;  
* final padframe.

The canonical user DEF should be generated as though the project occupies the designated canonical position, currently the upper-left valid location.

# **13\. Project block types**

Current planned block configurations are:

| Block | Area | Physical pad/interface sites | Possible locations |
| :---- | :---- | :---- | :---- |
| A | 1/4 die | 22 | 4 |
| B | 1/8 die | 16 | 4 |
| C | 1/8 die | 6 | 8 |
| D | 1/16 die | 10 | 4 |
| E | 1/16 die | 6 | 8 |

The distinction between physical pad/interface sites and available user signal pins must be maintained.

For example, an A block can have 22 physical positions associated with it while only 21 are available as ordinary user I/O if one position is dedicated to ground or power.

The exact allocation for each block type should be encoded explicitly rather than inferred mathematically.

# **14\. Canonical A-block pin sequence**

The definitive A variant has 22 physical interface positions. W12 is a fixed
VSS position owned by the integration template, leaving these 21 ordered
participant-configurable positions:

```text
A_SLOTS = [
    "W13", "W14", "W15", "W16", "W17",
    "W18", "W19", "W20", "W21", "W22",
    "N01", "N02", "N03", "N04", "N05", "N06",
    "N07", "N08", "N09", "N10", "N11",
]
```

The exact edge numbering direction is fixed by the production 88-pad template.
The corresponding configurable lists for every other definitive variant are
derived from section 24.1 by preserving its order and removing its fixed VSS
positions. These ordered lists are authoritative for padring generation.

# **15\. YosysHQ padring configuration**

Use the existing padring .cfg itself as the physical template.

Do not create a redundant YAML representation of:

* chip AREA;  
* GRID;  
* corners;  
* pad side;  
* pad ordering;  
* FLIP;  
* spacing;  
* fillers.

The template already contains this information.

Example:

DESIGN workshop\_padring;

AREA 2935 2935;

GRID 0.005;

CORNER CORNER\_1 SE gf180mcu\_fd\_io\_\_cor ;  
CORNER CORNER\_2 SW gf180mcu\_fd\_io\_\_cor ;  
CORNER CORNER\_3 NE gf180mcu\_fd\_io\_\_cor ;  
CORNER CORNER\_4 NW gf180mcu\_fd\_io\_\_cor ;

FILLER gf180mcu\_fd\_io\_\_fill5 ;

PAD N01 N gf180mcu\_fd\_io\_\_asig\_5p0 ;  
PAD N02 N gf180mcu\_fd\_io\_\_asig\_5p0 ;  
...

The template is the physical source of truth.

The production template must contain exactly 88 ordinary PAD entries: N01...N22,
E01...E22, S01...S22, and W01...W22. Legacy PAD entries must not be retained in
addition to these slots. YosysHQ padring does not support LOC directives; the
side is specified directly on each PAD line.

# **16\. Template transformation**

The converter should:

1\. Read the original padring .cfg.

2\. Preserve all comments and physical directives whenever possible.

3\. Locate physical slots belonging to the selected project block.

4\. Assign info.yaml pins to those slots using the predefined ordered slot sequence.

5\. Replace the cell type at those positions.

6\. Keep the pad instance name equal to its canonical physical slot name.

7\. Leave all unrelated padframe cells untouched.

8\. Convert unused project signal slots into analog placeholder pads.

The converter should preserve:

AREA  
GRID  
CORNER  
FILLER  
SPACE  
FLIP

and all fixed PAD entries.

For a production template, "unrelated" fixed PAD entries means the immutable
slots outside the selected project block. Unexpected legacy PAD instance names
are an error because they add physical pads beyond the canonical 88 positions.

# **17\. Canonical padring names and project names**

The physical slot identity is also the canonical padring PAD instance name.

Example:

physical slot: W13  
user pin:      reset\_n  
cell:          gf180mcu\_fd\_io\_\_in\_s

The generated padring directive is:

PAD W13 W gf180mcu\_fd\_io\_\_in\_s ;

while the integration metadata records:

slot: W13  
instance: W13
pin\_name: reset\_n
cell: gf180mcu\_fd\_io\_\_in\_s

The padring DEF, GDS, and Verilog use canonical names. Team-code prefixes and
participant pad names are applied only when the padring and projects are
instantiated in the future top-level design. The pad-center CSV reports the
intended top-level project pin name, including its team-code prefix, as mapping
metadata; this does not rename objects inside the padring layout.

# **18\. User-area-facing pin names**

Each project-facing I/O-cell terminal in the padring DEF and Verilog is named
`<canonical-pad>_<cell-terminal>`, for example `W01_A` or `W01_Y`. The DEF PINS
geometry is derived from the corresponding transformed LEF pin rectangles so
that the same named terminals exist in the generated layout.

The corresponding pin in a user project DEF is based on the participant pin
name and I/O-cell terminal, for example `RST_A`. A scalar name may be sanitized
as required for a DEF/Verilog identifier, and collisions after sanitization are
errors. A valid bus suffix must not be flattened or replaced with underscores.
Terminal qualifiers are inserted before the bus suffix. For example, the
control terminals for participant pin `DATA[0]` are `DATA_PU[0]`, `DATA_PD[0]`,
and so on, not `DATA_0_PU` or `DATA_0__PU`. The generated DEF declares
`BUSBITCHARS "[]"` and retains the bracketed form.

# **19\. Unused project slots**

If a project uses fewer signal pins than its block permits, the remaining allocated I/O positions should use:

gf180mcu\_fd\_io\_\_asig\_5p0

Example:

PAD W18 W gf180mcu\_fd\_io\_\_asig\_5p0 ;

These placeholder analog cells:

* maintain the physical padframe geometry;  
* are not project-visible signals;  
* do not require secondary\_esd;  
* do not appear as user pins.

They are physical placeholders only.

# **20\. Power and ground cells are not unused placeholders**

Reserved VDD/VSS positions must remain proper power cells such as:

gf180mcu\_fd\_io\_\_dvdd  
gf180mcu\_fd\_io\_\_dvss

They must not be replaced with analog placeholders merely because they are absent from the user's ordinary signal list.

The project-block template determines which physical locations are power and ground.

# **21\. Padring LEF files**

The Makefile invoking padring must provide LEFs for every pad cell the generator may emit.

At minimum, based on the current pin types:

gf180mcu\_fd\_io\_\_cor.lef  
gf180mcu\_fd\_io\_\_fill5.lef
gf180mcu\_fd\_io\_\_brk5.lef
gf180mcu\_fd\_io\_\_bi\_t.lef  
gf180mcu\_fd\_io\_\_bi\_24t.lef  
gf180mcu\_fd\_io\_\_in\_c.lef  
gf180mcu\_fd\_io\_\_in\_s.lef  
gf180mcu\_fd\_io\_\_asig\_5p0.lef  
gf180mcu\_fd\_io\_\_dvdd.lef  
gf180mcu\_fd\_io\_\_dvss.lef

A Makefile invocation therefore needs entries such as:

\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_cor.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_fill5.lef \\
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_brk5.lef \\
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_bi\_t.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_bi\_24t.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_in\_c.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_in\_s.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_asig\_5p0.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_dvdd.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_dvss.lef

# **22\. Typical padring invocation**

Current style:

$(BIN\_DIR)/padring \-v \\  
    \--lef .../gf180mcu\_fd\_io\_\_cor.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_fill5.lef \\
    \--lef .../gf180mcu\_fd\_io\_\_brk5.lef \\
    \--lef .../gf180mcu\_fd\_io\_\_bi\_t.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_asig\_5p0.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_dvdd.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_dvss.lef \\  
    \--svg $(PADRING\_DIR)/outputs/workshop\_padring.svg \\  
    \--def $(DEF) \\  
    \--ver $(PADRING\_DIR)/outputs/workshop\_padring.v \\
    $(PADRING\_DIR)/workshop\_padring.cfg \\  
    | tee $(PADRING\_DIR)/workshop\_padring.log

Add additional LEFs whenever additional io\_type mappings can emit those cells.

# **23\. Generated pad mapping metadata**

In addition to the .cfg, generate a machine-readable mapping.

Example:

pads:  
  \- pin\_index: 0  
    pin\_name: reset\_n  
    slot: W13  
    instance: W13
    io\_type: input\_schmitt  
    cell: gf180mcu\_fd\_io\_\_in\_s

  \- pin\_index: 1  
    pin\_name: "data\[7\]"  
    slot: W14  
    instance: W14
    io\_type: bidirectional  
    cell: gf180mcu\_fd\_io\_\_bi\_t

  \- slot: W20  
    instance: W20
    generated: true  
    cell: gf180mcu\_fd\_io\_\_asig\_5p0

This mapping becomes the connection between:

info.yaml  
      ↓  
physical pad slots  
      ↓  
padring configuration  
      ↓  
padring-generated DEF  
      ↓  
project virtual-padframe DEF  
      ↓  
final chip integration

Both YAML and JSON serializations may be generated. The JSON form is used by
the KLayout conversion stage without requiring a YAML package in KLayout's
embedded Python environment.
The mapping records the team code supplied by the project-ID Make target so
downstream outputs can construct globally unique project pin names.

# **24\. Generated project DEF / virtual padframe**

The project DEF is not merely documentation.

It is an input physical constraint to the participant's implementation flow.

It defines the project-side connection locations associated with its I/O cells.

The participant places and routes the project against those locations.

Therefore, when the completed block is inserted into the final chip:

* project-side interfaces already align;  
* no project I/O rerouting should be necessary;  
* placement transformation is deterministic.

Project DEF pins use the participant's pin name followed by one underscore and
the I/O-cell terminal name, such as `RST_A`. The mapping metadata for every
such pin also records its canonical padring slot.

Analog project pins are the exception: the project DEF pin uses the user pad
name from info.yaml without an `_ASIG5V` suffix and uses only the inward-facing
Metal2 ASIG5V geometry. Analog pads requesting secondary ESD will be handled by
a later, separately specified integration stage.

Mapped power and ground pads also use their user names from info.yaml. Their
project DEF pins use the inward-facing Metal2 geometry of the corresponding
DVDD or DVSS padring pin.

The canonical DEF represents the project in its canonical upper-left
placement. Its local lower-left coordinate is always `(0, 0)`. Only this
canonical placement is generated in the current task; transforms to other
legal top-level locations remain future work.

The generator inputs are:

* the padring-generated top-level DEF;
* pad mapping metadata;
* one selected block type;
* the canonical block lower-left origin in top-level coordinates;
* block width and height;
* GF180 I/O LEFs used to associate named terminals with pin geometry and layers.

Origin, width, and height CLI values are specified in microns. The generated
DEF inherits the padring DEF `UNITS DISTANCE MICRONS` value. Every micron input
must convert exactly to an integer number of inherited DEF database units;
non-grid-aligned values are rejected rather than rounded.

The generated DIEAREA is exactly:

```text
DIEAREA ( 0 0 ) ( <block-width-dbu> <block-height-dbu> ) ;
```

For every mapped user pad, the generator emits every project-facing I/O-cell
terminal. Input-pad `Y` terminals use the bare user pad name, such as `RST` or
`DATA[0]`, rather than `RST_Y` or `DATA_Y[0]`. For bidirectional pads, `Y` uses
`<user-pad-name>_IN` and `A` uses `<user-pad-name>_OUT`. For a bus pin, these
qualifiers precede the index: `DATA_IN[0]` and `DATA_OUT[0]`. Other digital
terminals retain `<user-pad-name>_<cell-terminal>`, such as `RST_PU`,
`DATA_PU[0]`, `DATA_PD[0]`, or `DATA_OE[0]`. Directions are inverted relative
to the padring-facing terminal, while DEF `USE` and other applicable pin
properties are preserved.

More generally, a participant name is separated into its scalar base and its
trailing bracketed bus suffix. The terminal qualifier is appended to the base,
then the unchanged suffix is restored. This applies to every trailing index in
a multidimensional name: `DATA[3][0]` with terminal `PU` becomes
`DATA_PU[3][0]`. Malformed or non-trailing bracket syntax is rejected rather
than silently flattened.

## **24.0.1 Project-layout text case resolution**

The default spelling of a generated project-interface signal uses the
participant pin-name case from info.yaml and the authoritative I/O-cell
terminal case. For example, pad `DATA` with terminals `OE` and `IE` defaults to
`DATA_OE` and `DATA_IE`. The same rule applies before a bus suffix, producing
names such as `DATA_OE[0]`.

Before finalizing project-interface names, the generator examines text objects
placed directly in the top cell of the project GDS selected by `LAYOUT_FILE`.
Text in referenced lower-level cells is not a top-level signal declaration and
is ignored. Direct top-cell text may be considered on any GDS layer because a
candidate is relevant only when its complete logical name matches an expected
generated signal case-insensitively.

For each expected signal:

* if no top-cell text matches case-insensitively, use the default spelling;
* if one exact spelling matches, use that complete layout spelling in the
  generated project DEF and every corresponding generated Verilog interface;
* repeated text objects with the same exact spelling are permitted;
* two or more distinct spellings that compare equal case-insensitively are a
  conflict and generation must fail.

Thus, top-cell text `DATA_oe` overrides default `DATA_OE`, and `DATA_ie`
overrides `DATA_IE`. The generated DEF and corresponding Verilog pins must then
use `DATA_oe` and `DATA_ie` exactly. If both `DATA_OE` and `DATA_oe` occur in
the top cell, generation fails rather than choosing one. Bus spelling is
handled identically: layout text `DATA_oe[0]` overrides default `DATA_OE[0]`
without flattening or moving the index.

Case-insensitive collisions between two different expected generated signals
are also errors, even if the layout contains no matching text. Interface
mapping metadata records both the default generated name and the final
layout-resolved spelling so that DEF, Verilog, and layout-name audits use the
same decision.

Pin rectangles come from the actual named PINS geometry in the generated
padring DEF. They must not be positioned again from I/O-cell placement or LEF
macro dimensions. LEF terminal definitions identify which padring geometry is
project-facing and which routing layer belongs to the terminal. All qualifying
rectangles remain separate and stay on their original routing layers. Their
span parallel to the DIEAREA boundary is preserved; their span normal to the
boundary is replaced by the inward stub described below.

All innermost rectangles for a selected terminal must share the same inward
boundary coordinate: X for west/east pads and Y for north/south pads. That
coordinate must equal the corresponding user-block DIEAREA boundary. A missing,
non-unique, or mismatched boundary is an error. The project DEF omits the
portion of the original terminal outside the user DIEAREA and emits a 1.0
micron stub beginning at the boundary and extending into the user block:

* west-side pads: boundary X to boundary X + 1 micron;
* east-side pads: boundary X - 1 micron to boundary X;
* north-side pads: boundary Y - 1 micron to boundary Y;
* south-side pads: boundary Y to boundary Y + 1 micron.

The extension is converted to inherited DEF database units. For example, each
W13 DVDD project rectangle begins at local X 0 and ends at local X 1.0 micron,
while retaining its original Y interval.

Extended top-level coordinates are translated to project-local coordinates:

```text
user_x = top_x - block_origin_x
user_y = top_y - block_origin_y
```

The mapping output preserves, for each generated rectangle:

* user pin name and I/O-cell terminal;
* padring instance;
* canonical physical pad slot;
* routing layer and inherited DEF properties;
* original top-level rectangle;
* extended and translated user rectangle.

Generation fails if a mapped padring instance or required named pin is absent,
the routing layer is unknown, the project-facing boundary is ambiguous, a
micron input is not exactly representable in inherited DBU, or any translated
or extended rectangle lies outside the local DIEAREA.

## **24.1 Canonical user-block slot allocations**

User-block pins advance in the exact order shown below. Within a range, pad
numbers ascend unless the range explicitly descends. Comma-separated ranges
are concatenated from left to right.

All origins, dimensions, and blockage coordinates are in microns. `Area` is
the authoritative usable-area metric for configuration selection; in
particular, ACE2 removes two 1/16 blocks and their spacing from the enclosing
square.

| Code | Pin order | Origin | Pin count | X | Y | Area | VSS fixed | Block |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| A | W12-W22, N01-N11 | 350, 1475 | 22 | 1110 | 1110 | 1,232,100 | W12 | — |
| BV | W12-W22, N01-N05 | 350, 1475 | 16 | 550 | 1110 | 610,500 | W12 | — |
| BH | W18-W22, N01-N11 | 350, 2035 | 16 | 1110 | 550 | 610,500 | — | — |
| CH | W12-W17 | 350, 1475 | 6 | 1110 | 550 | 610,500 | W12 | — |
| CV | N06-N11 | 910, 1475 | 6 | 550 | 1110 | 610,500 | — | — |
| D | W18-W22, N01-N05 | 350, 2035 | 10 | 550 | 550 | 302,500 | — | — |
| EV | N06-N11 | 910, 2035 | 6 | 550 | 550 | 302,500 | — | — |
| EH | W12-W17 | 350, 1475 | 6 | 550 | 550 | 302,500 | W12 | — |
| ACV | W12-W22, N01-N16 | 350, 1475 | 27 | 1675 | 1110 | 1,859,250 | W12 | — |
| ACH | W07-W22, N01-N11 | 350, 910 | 27 | 1110 | 1675 | 1,859,250 | W11, W12 | — |
| ACE | W07-W22, N01-N16 | 350, 910 | 32 | 1675 | 1675 | 2,805,625 | W11, W12 | — |
| ACE2 | W07-W22, N01-N16, E16-E01, S22-S07 | 350, 350 | 64 | 2235 | 2235 | 5,308,750 | W11, W12, E11, E12 | (0,0)-(560,560) and (1675,1675)-(2235,2235) |

For each rectangle in the `Block` column, the generated user DEF emits both a
placement blockage and routing blockages covering every routing layer. These
coordinates are local project coordinates. A dash means no blocked rectangle.

Configuration selection considers project width, height, and required pin
count. Generate every qualifying non-dominated minimum-area configuration.
Do not emit a larger-area configuration when a smaller-area configuration
fits (for example, do not generate ACV when A fits). Preserve distinct
equal-area placements such as EV and EH when both qualify. Project dimensions
must fit the usable geometry described by the selected variant, and required
pins must not exceed its pin count.

The implemented CLI command is `generate-project-def`. It accepts
`--project-width` and `--project-height` in microns, plus the padring DEF,
mapping metadata, and I/O LEFs. Without `--variant`, it writes one DEF and one
interface-mapping YAML for every minimum-area fitting variant into
`--output-dir`. With `--variant CODE`, it writes only that requested variant
after verifying that it fits. The default GF180 routing-blockage layer list is
Metal1 through Metal5 and can be overridden by repeating `--routing-layer`.

The normal Makefile flow derives project width and height from the project's
GDS rather than requiring manual dimensions. The GDS must have exactly one top
cell and exactly one rectangle, with no other shapes, directly in that top cell
on the configured outline layer/datatype (default `0/0`). Rectangle width and
height are converted to microns using the GDS layout DBU. Those dimensions and
the participant pin count from info.yaml select every minimum-area fitting
variant before its variant-specific padring and project DEF are generated.
The GDS filename must be selected from the expanded `LAYOUT_FILE` in the
project's retained lvs_config.json; selecting the first file in a directory is
prohibited. The downloader stores that config as
`<INFO_DIR>/<team-code>_lvs_config.json`. `PROJECT_GDS`, `PROJECT_LVS_CONFIG`,
`PROJECT_GDS_DIR`, `PROJECT_OUTLINE_LAYER`, and `PROJECT_OUTLINE_DATATYPE` are
Makefile-overridable.

Mapped slots must be an ordered subsequence of the variant's authoritative pin
order. This permits fixed VSS slots to remain owned by the integration template
without forcing them to appear as participant pad mappings.

# **25\. Transforming projects to other quadrants**

Final integration may place the project in another legal quadrant.

This should be implemented as a known geometric transformation of the canonical block.

Potential transformations include:

translation  
rotation

and reflection only if the physical/library rules explicitly allow it.

A transformation must consistently apply to:

* project GDS;  
* project DEF geometry;  
* interface locations;  
* pad-slot mapping.

Do not independently recompute pin ordering after placement.

Instead, derive each legal block placement from the canonical ordered slot map.

# **26\. Package bonding**

The die contains 88 pad positions while the target package has 64 pins.

Two bonding configurations are planned using diagonally opposite portions of the die.

The concepts discussed are:

top-left \+ bottom-right  
bottom-left \+ top-right

Package pin numbers must be kept separate from physical die pad numbers.

Do not overload names such as L13 to mean a package pin.

Maintain separate data such as:

die\_slot: W13  
package\_pin: 27

when package mapping is added.

# **27\. Download script behavior**

The project download flow currently retrieves:

info.yaml  
    ↓  
project.lvs\_config  
    ↓  
lvs\_config.json  
    ↓  
LAYOUT\_FILE  
    ↓  
GDS

When saving downloaded metadata such as info.yaml, stale files should not silently be reused.

The current command style is:

./download\_chipathon\_gds\_v2.py \\  
    \--info-dir info \\  
    \--gds-dir gds \\  
    \--overwrite \\  
    repo.list 2\>&1 | tee download.report

Because Python may buffer stdout when piping through tee, use:

sys.stdout.reconfigure(line\_buffering=True)

# **28\. Validation requirements**

The converter should reject:

* missing pins;  
* malformed YAML;  
* unsupported io\_type;  
* duplicate user pin names;  
* analog pins missing secondary\_esd;  
* secondary\_esd on non-analog pins;  
* more project pins than available block slots;  
* duplicate generated padring instance names;  
* collisions after pin-name sanitization;  
* missing physical slots in the padring template;  
* unexpected legacy PAD instances in a production template;
* missing or misplaced fixed brk5 cells around W11/W12 and E11/E12;
* missing required cell mappings.

It should also verify that every physical project slot is accounted for as one of:

user I/O  
reserved power  
reserved ground  
unused analog placeholder

# **29\. Important implementation principle**

There should be a single source of truth for physical geometry.

The production YosysHQ padring template should define:

* pad positions;  
* sides;  
* ordering;  
* corner cells;  
* filler cells;  
* power/ground positions;  
* orientation;  
* FLIP;  
* area;  
* grid.

Python configuration should define only higher-level semantic relationships such as:

A block uses slots:  
W13, W14, ..., N11

Do not duplicate all physical padring geometry in another YAML file.

# **30\. Items still to finalize**

The next implementation work should explicitly define:

1\. transformations from canonical placement to each legal non-canonical physical location;

2\. secondary-ESD cell layout, abstract, connectivity, and placement policy for analog pads;

3\. any additional block variants beyond the explicit allocations in section 24.1;

4\. package-bond mappings from 88 die pads to the two 64-pin package configurations.

# **31\. Project-ID padframe build and generated artifacts**

The repository provides chipathon2026-system/Makefile.padframe. From the
repository root, a project padframe is built by project ID:

make \-f chipathon2026-system/Makefile.padframe A01

The default input is:

info/A01\_info.yaml

INFO\_DIR and all build/tool/PDK paths must remain overrideable Make variables.
DEF\_DBU defaults to 0.005 microns and must remain overrideable. The generated
DEF therefore uses UNITS DISTANCE MICRONS 200, and the KLayout import/output DBU
must be set to the same value.
PAD\_MARKER\_LAYER and PAD\_MARKER\_DATATYPE must also be overrideable Make
variables. Their GF180 defaults are 37 and 0 respectively; other processes may
identify the physical pad-center marker on a different GDS layer/datatype pair.
When the repository-local padring executable is selected, the Makefile must
rebuild it with CMake whenever its C++ source or header files change. This
prevents newly added command-line options from being passed to a stale binary.
The project-ID target performs these stages in order:

1\. generate-padring;

2\. run-padring;

3\. KLayout GDS assembly using Workshop\_CASS/def2stream.py.

The default project output directory is build/padframes/A01 and contains:

```text
A01_padring.cfg
A01_pad_map.yaml
A01_pad_map.json
A01_padring.def
A01_padring.svg
A01_padring.v
A01_padring.gds
A01_pads.csv
```

The generated padring top-cell name and structural Verilog module name are
`<team-code>_padring`. For example, project A01 generates `A01_padring` in the
CFG, DEF, GDS, and Verilog. The Makefile passes the same derived design name to
KLayout; `DESIGN_NAME` remains overrideable when required.

The Verilog output is a structural padring module whose I/O-cell instances use
canonical physical-slot names. It exposes the project-facing cell terminals as
module ports named `<canonical-pad>_<cell-terminal>`. Break, filler, corner,
and unused placeholder cells do not create module ports.

The structural padring Verilog also exposes every physical pad using its bare
canonical slot name, such as `W01`, `W11`, or `W12`. A digital I/O cell's `PAD`
terminal connects to that canonical port. Analog pad connectivity is aliased to
the canonical port with a continuous `assign` statement where a separate
canonical-prefixed project-facing terminal is also exposed. Canonical DVSS pad
ports are likewise shorted with continuous assignments rather than Verilog
`tran` primitives.

The padring DEF must expose the same bare canonical physical-pad ports. Every
canonical slot, including unused placeholders, has an `INOUT` pin rectangle on
Metal5 at the transformed physical pad location. The common GF180 Metal5 `PAD`
rectangle defines this pad-location geometry for cell variants whose LEF does
not separately name the physical pad metal.

A canonical DVDD or DVSS pad pin additionally includes all transformed Metal2
rectangles from that cell's corresponding `DVDD` or `DVSS` LEF terminal. These
Metal2 shapes face the user area and allow top-level routing to the project.
DVDD canonical pins use `USE POWER`; DVSS canonical pins use `USE GROUND`.
Their Metal5 and Metal2 shapes belong to the same canonical DEF pin/net.

The structural Verilog must instantiate every component emitted in the
padring DEF, not only the 88 canonical I/O cells. GF180 filler and corner cells
contain devices and therefore cannot be omitted from LVS. Each `fill5` and
corner instance connects its available `VSS`/`DVSS` terminals to the common
canonical ground network and its `VDD`/`DVDD` terminals to the local canonical
power segment. Each `brk5` instance connects its available `VSS` terminal but
does not reconnect the broken VDD/DVDD rails. Generated DEF and Verilog
component counts must match.

Generated filler instance names encode their physical gap and a one-based
suffix. The gap before the first pad on a side is index 00; the gap after pad
01 is index 01, and so on. Default fillers use `FILL_<side><gap>_<n>` and break
fillers use `BRK_<side><gap>_<n>`, for example `FILL_E00_1` and `BRK_E10_1`.
The same instance names appear in DEF and structural Verilog.

E11 and W12 remain shorted as the global ground network, but individual cell
connections retain geographic ownership for LVS debugging. All west-edge
cells, N01-N11, and S01-S11 connect their `VSS` and `DVSS` terminals to W12.
All east-edge cells, N12-N22, and S12-S22 connect them to E11. Filler and
corner cells follow the region of their nearest canonical pad. `VDD` and
`DVDD` are likewise connected to the same net
within an individual continuity segment. Every DVDD pad inherently breaks the
VDD/DVDD rails, so two DVDD pads cannot electrically belong to the same
segment. `BREAK ;` supplies the separately required `brk5` physical isolation;
it is not the mechanism that separates DVDD-pad power domains. A powered
segment uses the bare canonical name of its DVDD pad as its supply port and
net. Any I/O or filler region that has no DVDD source uses an explicitly
declared, unique floating net named `FLOAT_VDD_<n>`. Floating regions must not
reuse a physical pad name or silently connect to another power segment.

The pad CSV format is:

canonical_pin_name,project_pin_name,type,x,y

canonical_pin_name is the canonical slot such as W01. For an allocated
participant pad, project_pin_name is the original project pin name prefixed by
the team code, for example A01_RST. It is empty for pads not allocated to that
project. type is the I/O macro name. x and y are micron
coordinates at the center of the single square on the configured GDS marker
layer/datatype pair (37/0 by default for GF180), within that I/O macro after
applying the DEF instance placement and orientation. The CSV coordinates must be derived from the source I/O GDS
geometry, not from the LEF macro bounding box. Break, filler, and corner instances are
excluded. The configured marker layer/datatype must be searched recursively through the complete I/O
macro hierarchy. The search must virtually flatten and merge the recursive
geometry in macro-local coordinates before selecting the square and applying
the top-level DEF transform. DEF orientation transforms must include the
normalization translation implied by the macro's declared LEF SIZE; applying
only a rotation/reflection matrix is incorrect for every orientation except N.
Missing LEF SIZE data or ambiguous square marker geometry is a deterministic
error.

***Key rule:** Physical slot order must always be represented explicitly. Do not derive it from words such as clockwise, counter-clockwise, left-to-right, or package orientation when an ordered list can be provided instead.*
