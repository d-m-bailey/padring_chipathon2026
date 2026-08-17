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

Their exact VSS/VDD assignment should be specified by the physical padframe template.

Example conceptually:

W11 \= VDDIO  
W12 \= VSS

but the final polarity/order must be explicitly defined in the padframe template rather than inferred.

These cells are owned by the integration template and must not be replaced when translating user pins.

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

For the canonical upper-left quadrant, the first user pin from info.yaml starts at L13, where the left side is numbered from bottom to top.

pins\[0\] \-\> L13

The pin sequence then proceeds around the project perimeter.

The intended initial left-side sequence is:

W13  
W14  
W15  
W16  
W17  
W18  
W19  
W20  
W21  
W22

followed by the appropriate top-edge pads.

For an A block with 21 user I/O positions, an example explicit sequence is:

A\_SLOTS \= \[  
    "W13",  
    "W14",  
    "W15",  
    "W16",  
    "W17",  
    "W18",  
    "W19",  
    "W20",  
    "W21",  
    "W22",

    "N01",  
    "N02",  
    "N03",  
    "N04",  
    "N05",  
    "N06",  
    "N07",  
    "N08",  
    "N09",  
    "N10",  
    "N11",  
\]

The exact top-edge numbering direction must be fixed when the production 88-pad template is finalized.

The legal slot sequence must be explicitly represented as an ordered list such as A\_SLOTS. That ordered list is authoritative.

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

FILLER gf180mcu\_fd\_io\_\_fill1 ;

LOC N ;

PAD N01 N gf180mcu\_fd\_io\_\_asig\_5p0 ;  
PAD N02 N gf180mcu\_fd\_io\_\_asig\_5p0 ;  
...

The template is the physical source of truth.

# **16\. Template transformation**

The converter should:

1\. Read the original padring .cfg.

2\. Preserve all comments and physical directives whenever possible.

3\. Locate physical slots belonging to the selected project block.

4\. Assign info.yaml pins to those slots using the predefined ordered slot sequence.

5\. Replace the cell type at those positions.

6\. Replace the pad instance name with a name based on the user's pin.

7\. Leave all unrelated padframe cells untouched.

8\. Convert unused project signal slots into analog placeholder pads.

The converter should preserve:

AREA  
GRID  
CORNER  
FILLER  
LOC  
SPACE  
FLIP

and all fixed PAD entries.

# **17\. Physical slots versus pad instance names**

The physical slot identity and the generated PAD instance name are different concepts.

Example:

physical slot: W13  
user pin:      reset\_n  
cell:          gf180mcu\_fd\_io\_\_in\_s

The generated padring directive may be:

PAD reset\_n W gf180mcu\_fd\_io\_\_in\_s ;

while the integration metadata records:

slot: W13  
pin: reset\_n  
cell: gf180mcu\_fd\_io\_\_in\_s

This mapping should be retained because the padring file itself does not preserve the original physical-slot identifier after the instance is renamed.

# **18\. Pin-name conversion for padring instances**

User HDL-style names may contain characters unsuitable or inconvenient for padring instance names.

Example:

name: "data\[7\]"

The physical PAD instance may therefore be sanitized:

data\_7

while metadata retains:

pin\_name: "data\[7\]"  
instance: data\_7

The generator must detect collisions caused by sanitization.

For example, data\[7\] and data\_7 must not silently become two instances named data\_7.

# **19\. Unused project slots**

If a project uses fewer signal pins than its block permits, the remaining allocated I/O positions should use:

gf180mcu\_fd\_io\_\_asig\_5p0

Example:

PAD unused\_L18 W gf180mcu\_fd\_io\_\_asig\_5p0 ;

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
gf180mcu\_fd\_io\_\_fill1.lef  
gf180mcu\_fd\_io\_\_bi\_t.lef  
gf180mcu\_fd\_io\_\_bi\_24t.lef  
gf180mcu\_fd\_io\_\_in\_c.lef  
gf180mcu\_fd\_io\_\_in\_s.lef  
gf180mcu\_fd\_io\_\_asig\_5p0.lef  
gf180mcu\_fd\_io\_\_dvdd.lef  
gf180mcu\_fd\_io\_\_dvss.lef

A Makefile invocation therefore needs entries such as:

\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_cor.lef \\  
\--lef $(TECH\_PDK)/libs.ref/gf180mcu\_fd\_io/lef/gf180mcu\_fd\_io\_\_fill1.lef \\  
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
    \--lef .../gf180mcu\_fd\_io\_\_fill1.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_bi\_t.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_asig\_5p0.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_dvdd.lef \\  
    \--lef .../gf180mcu\_fd\_io\_\_dvss.lef \\  
    \--svg $(PADRING\_DIR)/outputs/workshop\_padring.svg \\  
    \--def $(DEF) \\  
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
    instance: reset\_n  
    io\_type: input\_schmitt  
    cell: gf180mcu\_fd\_io\_\_in\_s

  \- pin\_index: 1  
    pin\_name: "data\[7\]"  
    slot: W14  
    instance: data\_7  
    io\_type: bidirectional  
    cell: gf180mcu\_fd\_io\_\_bi\_t

  \- slot: W20  
    instance: unused\_W20  
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

# **24\. Generated project DEF / virtual padframe**

The project DEF is not merely documentation.

It is an input physical constraint to the participant's implementation flow.

It defines the project-side connection locations associated with its I/O cells.

The participant places and routes the project against those locations.

Therefore, when the completed block is inserted into the final chip:

* project-side interfaces already align;  
* no project I/O rerouting should be necessary;  
* placement transformation is deterministic.

The canonical DEF should initially represent the project as if it were placed in the canonical upper-left location.

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

1\. the complete 88-slot physical naming/order;

2\. exact N01...N22 and S01...S22 numbering direction;

3\. exact left/right VSS versus project-VDD assignment at positions 11/12;

4\. explicit ordered slot lists for A, B, C, D, and E block types;

5\. transformations from canonical placement to each legal physical location;

6\. exact project-facing terminals for each GF180 I/O cell, taken from authoritative LEF/CDL/Verilog definitions;

7\. whether power and ground should remain participant io\_type entries or be entirely integration-managed;

8\. package-bond mappings from 88 die pads to the two 64-pin package configurations.

***Key rule:** Physical slot order must always be represented explicitly. Do not derive it from words such as clockwise, counter-clockwise, left-to-right, or package orientation when an ordered list can be provided instead.*