"""KLayout batch helper for full-chip project inspection and GDS assembly."""

import csv
import json
import os
import re

import pya


def required(name):
    value = globals().get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError("missing required -rd %s=... value" % name)
    return str(value)


def read_json(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def single_top(layout, source):
    tops = list(layout.top_cells())
    if len(tops) != 1:
        raise RuntimeError("%s must contain exactly one top cell; found %s" % (source, [c.name for c in tops]))
    return tops[0]


def inspect_projects(manifest, output):
    layer_number = int(globals().get("outline_layer", 0))
    datatype_number = int(globals().get("outline_datatype", 0))
    result = {}
    for project in manifest["projects"]:
        layout = pya.Layout()
        layout.read(project["gds_path"])
        top = single_top(layout, project["gds_path"])
        layer_index = layout.find_layer(layer_number, datatype_number)
        if layer_index is None:
            raise RuntimeError("%s has no PR-boundary layer %d/%d" % (project["team"], layer_number, datatype_number))
        rectangles = []
        other = 0
        for shape in top.shapes(layer_index).each():
            if shape.is_box():
                rectangles.append(shape.box)
            elif shape.is_polygon() and shape.polygon.is_box():
                rectangles.append(shape.polygon.bbox())
            else:
                other += 1
        if len(rectangles) != 1 or other:
            raise RuntimeError(
                "%s top cell must contain exactly one PR-boundary rectangle and no other %d/%d shapes"
                % (project["team"], layer_number, datatype_number)
            )
        box = rectangles[0]
        dbu = layout.dbu
        result[project["team"]] = {
            "source_gds": project["gds_path"],
            "top_cell": top.name,
            "layout_dbu_microns": dbu,
            "prboundary_dbu": [box.left, box.bottom, box.right, box.top],
            "prboundary_microns": [
                format(box.left * dbu, ".12g"), format(box.bottom * dbu, ".12g"),
                format(box.right * dbu, ".12g"), format(box.top * dbu, ".12g"),
            ],
        }
    write_json(output, result)


def box_microns(box):
    return [box.left, box.bottom, box.right, box.top]


def boxes_match(left, right, tolerance=1e-9):
    return all(abs(a - b) <= tolerance for a, b in zip(left, right))


def direct_instance_count(parent, child_index):
    return sum(1 for instance in parent.each_inst() if instance.cell_index == child_index)


def read_def_units(path):
    pattern = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;")
    with open(path, "r", encoding="utf-8") as stream:
        matches = [int(match.group(1)) for line in stream for match in [pattern.match(line)] if match]
    if matches != [200]:
        raise RuntimeError("integrated DEF must contain exactly one UNITS DISTANCE MICRONS 200")


def require_unique_cell_names(layout, context):
    names = [cell.name for cell in layout.each_cell()]
    if len(names) != len(set(names)):
        raise RuntimeError("%s introduced a destination cell-name collision" % context)


def namespace_source_cells(layout, top, prefix):
    renamed = []
    prefix_text = prefix + "__"
    for cell in layout.each_cell():
        if cell.cell_index() == top.cell_index():
            continue
        original = cell.name
        final = original if original.casefold().startswith(prefix_text.casefold()) else prefix_text + original
        cell.name = final
        renamed.append({"source_name": original, "destination_name": final})
    return renamed


def read_source_tree(filename, expected_top=None, namespace=None):
    source_layout = pya.Layout()
    source_layout.read(filename)
    source_top = single_top(source_layout, filename)
    if expected_top is not None and source_top.name != expected_top:
        raise RuntimeError(
            "%s top cell is %s, expected %s" % (filename, source_top.name, expected_top)
        )
    source_bbox = box_microns(source_top.dbbox())
    renamed = [] if namespace is None else namespace_source_cells(source_layout, source_top, namespace)
    return source_layout, source_top, source_bbox, renamed


def copy_source_tree(destination, source_top, source_bbox, context):
    if not destination.is_empty():
        raise RuntimeError("DEF-created destination cell %s is not empty" % destination.name)
    destination.copy_tree(source_top)
    copied_bbox = box_microns(destination.dbbox())
    if not boxes_match(source_bbox, copied_bbox):
        raise RuntimeError(
            "%s physical bounding box changed during DBU conversion: %s -> %s"
            % (context, source_bbox, copied_bbox)
        )
    return copied_bbox


def build_gds(manifest, output):
    canonical_dbu = 0.005
    if abs(float(manifest["dbu_microns"]) - canonical_dbu) > 1e-12:
        raise RuntimeError("integrated destination DBU must be 0.005 microns")
    read_def_units(manifest["integrated_def"])

    technology = pya.Technology()
    technology.load(manifest["tech_file"])
    load_options = technology.load_layout_options
    load_options.lefdef_config.dbu = canonical_dbu
    load_options.lefdef_config.read_lef_with_def = False
    load_options.lefdef_config.lef_files = manifest["lef_files"]
    # This read establishes only the DEF hierarchy, placements and
    # orientations.  All mask geometry comes from the separately imported GDS
    # trees, so do not ask the DEF reader to manufacture GDS layers for
    # implementation constraints, pins, routing or labels.
    if manifest.get("layer_map"):
        load_options.lefdef_config.map_file = manifest["layer_map"]
    load_options.lefdef_config.produce_cell_outlines = False
    load_options.lefdef_config.produce_blockages = False
    load_options.lefdef_config.produce_placement_blockages = False
    load_options.lefdef_config.produce_pins = False
    load_options.lefdef_config.produce_labels = False
    load_options.lefdef_config.produce_routing = False
    load_options.lefdef_config.produce_special_routing = False
    load_options.lefdef_config.produce_fills = False
    load_options.lefdef_config.produce_regions = False
    load_options.lefdef_config.produce_via_geometry = False

    target = pya.Layout()
    target.dbu = canonical_dbu
    target.read(manifest["integrated_def"], load_options)
    if abs(target.dbu - canonical_dbu) > 1e-12:
        raise RuntimeError(
            "integrated DEF created destination DBU %.12g, expected 0.005" % target.dbu
        )
    top = target.cell(manifest["chip_name"])
    if top is None or list(target.top_cells()) != [top]:
        raise RuntimeError("integrated DEF must create the sole top cell %s" % manifest["chip_name"])

    ring_destination = target.cell(manifest["padring_top"])
    if ring_destination is None:
        raise RuntimeError("integrated DEF is missing padring component cell %s" % manifest["padring_top"])
    if direct_instance_count(top, ring_destination.cell_index()) != 1:
        raise RuntimeError("integrated DEF must contain exactly one padring instance")
    ring_layout, ring_source, ring_bbox, ring_renames = read_source_tree(
        manifest["padring_gds"], expected_top=manifest["padring_top"]
    )
    ring_copied_bbox = copy_source_tree(
        ring_destination, ring_source, ring_bbox, "padring"
    )
    require_unique_cell_names(target, "padring import")

    name_map = []
    dbu_report = {
        "destination_dbu_microns": target.dbu,
        "padring": {
            "source_dbu_microns": ring_layout.dbu,
            "source_bbox_microns": ring_bbox,
            "copied_bbox_microns": ring_copied_bbox,
            "renamed_cells": ring_renames,
        },
        "projects": [],
    }
    for project in manifest["projects"]:
        source_layout, source_top, source_bbox, renamed = read_source_tree(
            project["gds_path"], expected_top=project["source_top"], namespace=project["team"]
        )
        destination = target.cell(project["integrated_top"])
        if destination is None:
            raise RuntimeError(
                "integrated DEF is missing project component cell %s" % project["integrated_top"]
            )
        if direct_instance_count(top, destination.cell_index()) != 1:
            raise RuntimeError(
                "integrated DEF must contain exactly one instance of %s" % project["integrated_top"]
            )
        copied_bbox = copy_source_tree(
            destination, source_top, source_bbox, project["team"]
        )
        require_unique_cell_names(target, "%s import" % project["team"])
        name_map.append({
            "team": project["team"], "source_top": source_top.name,
            "integrated_top": destination.name, "renamed_cells": renamed,
        })
        dbu_report["projects"].append({
            "team": project["team"], "source_dbu_microns": source_layout.dbu,
            "source_bbox_microns": source_bbox,
            "copied_bbox_microns": copied_bbox,
        })

    label_layer = target.layer(
        pya.LayerInfo(int(manifest["pin_text_layer"]), int(manifest["pin_text_datatype"]))
    )
    # Some KLayout versions still materialize DEF PIN labels despite the
    # reader option.  Remove only top-level text on the selected label layer;
    # keep all polygons and all labels inside imported hierarchies.
    for shape in list(top.shapes(label_layer).each()):
        if shape.is_text():
            shape.delete()
    with open(manifest["pin_csv"], newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            top.shapes(label_layer).insert(
                pya.DText(row["project_pin_name"], float(row["x"]), float(row["y"]))
            )

    options = pya.SaveLayoutOptions()
    options.write_context_info = False
    target.write(output, options)

    check = pya.Layout()
    check.read(output)
    if abs(check.dbu - canonical_dbu) > 1e-12:
        raise RuntimeError("exported GDS DBU %.12g is not 0.005 microns" % check.dbu)
    tops = [cell.name for cell in check.top_cells()]
    if tops != [manifest["chip_name"]]:
        raise RuntimeError("exported GDS top cells are %s, expected only %s" % (tops, manifest["chip_name"]))
    names = [cell.name for cell in check.each_cell()]
    if len(names) != len(set(names)):
        raise RuntimeError("exported GDS contains duplicate cell names")
    if any("KLAYOUTCONTEXT" in name for name in names):
        raise RuntimeError("exported GDS contains KLayout context helper cells")
    check_top = check.cell(manifest["chip_name"])
    check_layer = check.find_layer(int(manifest["pin_text_layer"]), int(manifest["pin_text_datatype"]))
    exported_labels = []
    if check_top is not None and check_layer is not None:
        exported_labels = sorted(
            shape.text.string for shape in check_top.shapes(check_layer).each() if shape.is_text()
        )
    with open(manifest["pin_csv"], newline="", encoding="utf-8") as stream:
        expected_labels = sorted(row["project_pin_name"] for row in csv.DictReader(stream))
    if exported_labels != expected_labels:
        raise RuntimeError("exported GDS project-pin text does not match pin CSV")
    write_json(manifest["cell_name_map"], {
        "destination_dbu_microns": target.dbu,
        "dbu_conversion": dbu_report,
        "projects": name_map,
        "exported_cells": names,
    })


mode_value = required("mode")
manifest_value = read_json(required("manifest"))
output_value = required("output")
if mode_value == "inspect":
    inspect_projects(manifest_value, output_value)
elif mode_value == "build":
    build_gds(manifest_value, output_value)
else:
    raise RuntimeError("mode must be inspect or build")
