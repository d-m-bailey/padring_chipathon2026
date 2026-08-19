"""
Copied from OpenROAD-flow-scripts
"""

import pya
import re
import json
import copy
import csv
import sys
import os
errors = 0


def read_def_components(path):
    units = 1.0
    current = None
    components = []
    component_re = re.compile(r"^\s*-\s+(\S+)\s+(\S+)\s*$")
    placed_re = re.compile(
        r"^\s*\+\s+PLACED\s+\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)\s+(\S+)\s*;"
    )
    units_re = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+([-+0-9.eE]+)\s*;")

    with open(path, "r") as stream:
        for line in stream:
            match = units_re.match(line)
            if match:
                units = float(match.group(1))
                continue
            match = component_re.match(line)
            if match:
                current = (match.group(1), match.group(2))
                continue
            match = placed_re.match(line)
            if match and current:
                components.append(
                    (
                        current[0],
                        current[1],
                        float(match.group(1)) / units,
                        float(match.group(2)) / units,
                        match.group(3),
                    )
                )
                current = None
    return components


def read_lef_sizes(paths):
    sizes = {}
    macro = None
    macro_re = re.compile(r"^\s*MACRO\s+(\S+)")
    size_re = re.compile(r"^\s*SIZE\s+([-+0-9.eE]+)\s+BY\s+([-+0-9.eE]+)\s*;")
    end_re = re.compile(r"^\s*END\s+(\S+)")

    for path in paths:
        with open(path, "r") as stream:
            for line in stream:
                match = macro_re.match(line)
                if match:
                    macro = match.group(1)
                    continue
                match = size_re.match(line)
                if match and macro:
                    sizes[macro] = (float(match.group(1)), float(match.group(2)))
                    continue
                match = end_re.match(line)
                if match and match.group(1) == macro:
                    macro = None
    return sizes


def transform_point(x, y, width, height, orientation):
    transforms = {
        "N": lambda u, v: (u, v),
        "S": lambda u, v: (width - u, height - v),
        "W": lambda u, v: (height - v, u),
        "E": lambda u, v: (v, width - u),
        "FN": lambda u, v: (width - u, v),
        "FS": lambda u, v: (u, height - v),
        "FE": lambda u, v: (height - v, width - u),
        "FW": lambda u, v: (v, u),
    }
    if orientation not in transforms:
        raise ValueError("unsupported DEF orientation %s" % orientation)
    return transforms[orientation](x, y)


def write_pad_centers(layout, def_path, lef_paths, output_path, layer, datatype, mapping_path=None):
    global errors
    layer_index = layout.find_layer(pya.LayerInfo(layer, datatype))
    if layer_index is None or layer_index < 0:
        print("[ERROR] GDS layer %d/%d was not found" % (layer, datatype))
        errors += 1
        return

    centers = {}
    project_names = {}
    team_code = ""
    if mapping_path:
        with open(mapping_path, "r") as stream:
            mapping = json.load(stream)
        project_names = {
            pad["slot"]: pad["pin_name"]
            for pad in mapping.get("pads", [])
            if isinstance(pad, dict) and not pad.get("generated")
        }
        team_code = mapping.get("team_code", "")
        if project_names and not team_code:
            raise ValueError("pad mapping is missing team_code")
    sizes = read_lef_sizes(lef_paths)
    components = read_def_components(def_path)
    with open(output_path, "w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("canonical_pin_name", "project_pin_name", "type", "x", "y"))
        for name, cell_name, place_x, place_y, orientation in components:
            if name.startswith(("FILLER_", "FILL_", "BRK_")) or cell_name.endswith(("__cor", "__fill5", "__brk5")):
                continue

            if cell_name not in centers:
                cell = layout.cell(cell_name)
                marker_region = (
                    pya.Region() if cell is None else pya.Region(cell.begin_shapes_rec(layer_index))
                )
                marker_region.merge()
                squares = [
                    polygon.bbox()
                    for polygon in marker_region.each()
                    if polygon.bbox().width() == polygon.bbox().height()
                ]
                if len(squares) != 1:
                    print(
                        "[ERROR] Cell '%s' must contain exactly one recursively flattened square on GDS layer %d/%d"
                        % (cell_name, layer, datatype)
                    )
                    errors += 1
                    centers[cell_name] = None
                else:
                    box = squares[0]
                    centers[cell_name] = (
                        (box.left + box.right) * layout.dbu / 2.0,
                        (box.bottom + box.top) * layout.dbu / 2.0,
                    )

            center = centers[cell_name]
            if center is None:
                continue
            if cell_name not in sizes:
                print("[ERROR] LEF SIZE was not found for cell '%s'" % cell_name)
                errors += 1
                continue
            width, height = sizes[cell_name]
            offset_x, offset_y = transform_point(
                center[0], center[1], width, height, orientation
            )
            project_name = project_names.get(name)
            qualified_name = "%s_%s" % (team_code, project_name) if project_name else ""
            writer.writerow((name, qualified_name, cell_name, place_x + offset_x, place_y + offset_y))

# Load technology file
tech = pya.Technology()
tech.load(tech_file)
layoutOptions = tech.load_layout_options
if len(layer_map) > 0:
    layoutOptions.lefdef_config.map_file = layer_map

if len(lef_files) > 0:
    layoutOptions.lefdef_config.read_lef_with_def = False
    layoutOptions.lefdef_config.lef_files = lef_files.split(" ")

# Load def file
main_layout = pya.Layout()
main_layout.dbu = float(output_dbu) if "output_dbu" in globals() else 0.005
print("[INFO] Reporting cells prior to loading DEF ...")
for i in main_layout.each_cell():
    print("[INFO] '{0}'".format(i.name))

print("[INFO] Reading DEF %s ..." % in_def)
main_layout.read(in_def, layoutOptions)

# Clear cells
top_cell_index = main_layout.cell(design_name).cell_index()

# remove orphan cell BUT preserve cell with VIA_
#  - KLayout is prepending VIA_ when reading DEF that instantiates LEF's via
print("[INFO] Clearing cells...")
for i in main_layout.each_cell():
    if i.cell_index() != top_cell_index:
        if not i.name.startswith("VIA_") and not i.name.endswith("_DEF_FILL"):
            i.clear()

# Load in the gds to merge
print("[INFO] Merging GDS/OAS files...")
for fil in in_files.split():
    print("\t{0}".format(fil))
    main_layout.read(fil)

if "csv_file" in globals() and csv_file:
    write_pad_centers(
        main_layout,
        in_def,
        lef_files.split(),
        csv_file,
        int(marker_layer) if "marker_layer" in globals() else 37,
        int(marker_datatype) if "marker_datatype" in globals() else 0,
        mapping_file if "mapping_file" in globals() and mapping_file else None,
    )

# Copy the top level only to a new layout
print("[INFO] Copying toplevel cell '{0}'".format(design_name))
top_only_layout = pya.Layout()
top_only_layout.dbu = main_layout.dbu
top = top_only_layout.create_cell(design_name)
top.copy_tree(main_layout.cell(design_name))

print("[INFO] Checking for missing cell from GDS/OAS...")
missing_cell = False
regex = None
if "GDS_ALLOW_EMPTY" in os.environ:
    print("[INFO] Found GDS_ALLOW_EMPTY variable.")
    regex = os.getenv("GDS_ALLOW_EMPTY")
for i in top_only_layout.each_cell():
    if i.is_empty():
        missing_cell = True
        if regex is not None and re.match(regex, i.name):
            print(
                "[WARNING] LEF Cell '{0}' ignored. Matches GDS_ALLOW_EMPTY.".format(
                    i.name
                )
            )
        else:
            print(
                "[ERROR] LEF Cell '{0}' has no matching GDS/OAS cell."
                " Cell will be empty.".format(i.name)
            )
            errors += 1

if not missing_cell:
    print("[INFO] All LEF cells have matching GDS/OAS cells")

print("[INFO] Checking for orphan cell in the final layout...")
orphan_cell = False
for i in top_only_layout.each_cell():
    if i.name != design_name and i.parent_cells() == 0:
        orphan_cell = True
        print("[ERROR] Found orphan cell '{0}'".format(i.name))
        errors += 1

if not orphan_cell:
    print("[INFO] No orphan cells")


if seal_file:
    top_cell = top_only_layout.top_cell()

    print("[INFO] Reading seal GDS/OAS file...")
    print("\t{0}".format(seal_file))
    top_only_layout.read(seal_file)

    for cell in top_only_layout.top_cells():
        if cell != top_cell:
            print(
                "[INFO] Merging '{0}' as child of '{1}'".format(
                    cell.name, top_cell.name
                )
            )
            top.insert(pya.CellInstArray(cell.cell_index(), pya.Trans()))

# Write out the GDS
print("[INFO] Writing out GDS/OAS '{0}'".format(out_file))
top_only_layout.write(out_file)

sys.exit(errors)
