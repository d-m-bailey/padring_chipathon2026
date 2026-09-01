"""KLayout batch helper for full-chip project inspection and GDS assembly."""

import csv
import json
import os

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


def project_transform(quadrant, ox, oy, chip_diearea):
    x1, y1, x2, y2 = chip_diearea
    if quadrant == "NW":
        return pya.DCplxTrans(1.0, 0.0, False, ox, oy)
    if quadrant == "NE":
        return pya.DCplxTrans(1.0, 180.0, True, x1 + x2 - ox, oy)
    if quadrant == "SE":
        return pya.DCplxTrans(1.0, 180.0, False, x1 + x2 - ox, y1 + y2 - oy)
    if quadrant == "SW":
        return pya.DCplxTrans(1.0, 0.0, True, ox, y1 + y2 - oy)
    raise RuntimeError("unsupported quadrant %s" % quadrant)


def build_gds(manifest, output):
    target = pya.Layout()
    target.dbu = float(manifest["dbu_microns"])
    target.read(manifest["padring_gds"])
    ring_tops = [cell for cell in target.top_cells() if cell.name == manifest["padring_top"]]
    if len(ring_tops) != 1:
        raise RuntimeError("padring GDS must contain top cell %s" % manifest["padring_top"])
    ring = ring_tops[0]
    top = target.create_cell(manifest["chip_name"])
    top.insert(pya.DCellInstArray(ring.cell_index(), pya.DTrans()))

    libraries = []
    name_map = []
    for project in manifest["projects"]:
        library = pya.Library()
        library.description = "Chipathon project %s" % project["team"]
        library.layout().read(project["gds_path"])
        source = single_top(library.layout(), project["gds_path"])
        library.register(project["team"])
        libraries.append(library)
        proxy = target.create_cell(source.name, project["team"])
        if proxy is None:
            raise RuntimeError("cannot create library proxy for %s" % project["team"])
        wrapper = target.create_cell(project["integrated_top"])
        wrapper.insert(pya.DCellInstArray(proxy.cell_index(), pya.DTrans()))
        transform = project_transform(
            project["quadrant"], float(project["origin_microns"][0]),
            float(project["origin_microns"][1]),
            [float(value) for value in manifest["chip_diearea_microns"]],
        )
        top.insert(pya.DCellInstArray(wrapper.cell_index(), transform))
        name_map.append({
            "team": project["team"], "source_top": source.name,
            "integrated_top": wrapper.name, "proxy_name": proxy.name,
        })

    label_layer = target.layer(
        pya.LayerInfo(int(manifest["pin_text_layer"]), int(manifest["pin_text_datatype"]))
    )
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
    write_json(manifest["cell_name_map"], {"projects": name_map, "exported_cells": names})


mode_value = required("mode")
manifest_value = read_json(required("manifest"))
output_value = required("output")
if mode_value == "inspect":
    inspect_projects(manifest_value, output_value)
elif mode_value == "build":
    build_gds(manifest_value, output_value)
else:
    raise RuntimeError("mode must be inspect or build")
