"""KLayout batch script: measure the single top-cell outline rectangle."""

import json
import pya


def required_variable(name):
    value = globals().get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"missing required -rd {name}=... value")
    return str(value)


input_manifest = globals().get("input_manifest")
if input_manifest is not None and str(input_manifest).strip():
    with open(str(input_manifest), "r", encoding="utf-8") as stream:
        input_path = str(json.load(stream)["project_gds"])
else:
    input_path = required_variable("input_gds")
output_path = required_variable("output_json")
layer_number = int(globals().get("outline_layer", 0))
datatype_number = int(globals().get("outline_datatype", 0))

layout = pya.Layout()
layout.read(input_path)
top_cells = list(layout.top_cells())
if len(top_cells) != 1:
    names = [cell.name for cell in top_cells]
    raise RuntimeError(f"project GDS must contain exactly one top cell; found {names}")

top = top_cells[0]
layer_index = layout.find_layer(layer_number, datatype_number)
if layer_index is None:
    raise RuntimeError(f"top cell {top.name!r} has no layer {layer_number}/{datatype_number}")

rectangles = []
non_rectangles = 0
for shape in top.shapes(layer_index).each():
    if shape.is_box():
        rectangles.append(shape.box)
    elif shape.is_polygon() and shape.polygon.is_box():
        rectangles.append(shape.polygon.bbox())
    else:
        non_rectangles += 1

if len(rectangles) != 1 or non_rectangles:
    raise RuntimeError(
        f"top cell {top.name!r} layer {layer_number}/{datatype_number} must contain "
        f"exactly one rectangle and no other shapes; found {len(rectangles)} rectangles "
        f"and {non_rectangles} other shapes"
    )

outline = rectangles[0]
if outline.width() <= 0 or outline.height() <= 0:
    raise RuntimeError("project outline rectangle must have positive width and height")

result = {
    "source_gds": input_path,
    "top_cell": top.name,
    "layer": layer_number,
    "datatype": datatype_number,
    "layout_dbu_microns": layout.dbu,
    "rectangle_dbu": [outline.left, outline.bottom, outline.right, outline.top],
    "width_microns": format(outline.width() * layout.dbu, ".12g"),
    "height_microns": format(outline.height() * layout.dbu, ".12g"),
    "top_cell_text": [],
}
for layer_index in layout.layer_indexes():
    layer_info = layout.get_info(layer_index)
    for shape in top.shapes(layer_index).each():
        if shape.is_text():
            result["top_cell_text"].append({
                "text": shape.text.string,
                "layer": layer_info.layer,
                "datatype": layer_info.datatype,
            })
with open(output_path, "w", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
    stream.write("\n")

print(
    f"Measured {top.name} layer {layer_number}/{datatype_number}: "
    f"{result['width_microns']} x {result['height_microns']} um"
)
