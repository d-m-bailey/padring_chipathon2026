from pathlib import Path
from types import SimpleNamespace

import pytest

from chipathon2026_integration.errors import ConfigError
from chipathon2026_integration.fullchip import (
    BaseChipDefinition,
    BaseVariantGeometry,
    ChipRequest,
    Placement,
    ProjectRequest,
    generate_chip_padring,
    load_chip_request,
    prefix_name,
    transform_box,
    transform_slot,
    write_top_verilog,
)
from chipathon2026_integration.constants import IO_CELLS
from chipathon2026_integration.virtual_def import BLOCK_VARIANTS


def _base_chip(tmp_path: Path) -> BaseChipDefinition:
    return BaseChipDefinition(
        tmp_path / "base_chip.yaml", "chipathon2026_2935_v1",
        (0, 0, 2935, 2935), dict(IO_CELLS),
        {
            code: BaseVariantGeometry(variant.origin, variant.width, variant.height)
            for code, variant in BLOCK_VARIANTS.items()
        },
    )


def _write_base_chip(path: Path) -> None:
    variants = "\n".join(
        f"  {code}:\n    origin_um: [{variant.origin[0]}, {variant.origin[1]}]\n"
        f"    size_um: [{variant.width}, {variant.height}]"
        for code, variant in BLOCK_VARIANTS.items()
    )
    cells = "\n".join(f"  {key}: {value}" for key, value in IO_CELLS.items())
    path.write_text(
        "schema_version: 1\nchip:\n  name: chipathon2026_2935_v1\n"
        "  diearea_um: [0, 0, 2935, 2935]\nio_cells:\n"
        + cells + "\nblock_variants:\n" + variants + "\n",
        encoding="utf-8",
    )


def test_load_chip_request_strict_schema(tmp_path: Path):
    _write_base_chip(tmp_path / "base.yaml")
    path = tmp_path / "chip.yaml"
    path.write_text(
        """schema_version: 2
base_chip: base.yaml
chip:
  name: demo_chip
  minimum_project_gap_um: 10
projects:
  - team: A01
    variant: A
    quadrant: NE
""",
        encoding="utf-8",
    )
    request = load_chip_request(path)
    assert request.name == "demo_chip"
    assert request.base_chip.path == (tmp_path / "base.yaml").resolve()
    assert request.projects == (ProjectRequest("A01", "A", "NE"),)


def test_base_chip_rejects_duplicate_io_type(tmp_path: Path):
    base = tmp_path / "base.yaml"
    _write_base_chip(base)
    text = base.read_text(encoding="utf-8")
    base.write_text(
        text.replace(
            "  input_cmos: gf180mcu_fd_io__in_c\n",
            "  input_cmos: gf180mcu_fd_io__in_c\n  input_cmos: duplicate_cell\n",
        ),
        encoding="utf-8",
    )
    integration = tmp_path / "integration.yaml"
    integration.write_text(
        "schema_version: 2\nbase_chip: base.yaml\nchip:\n  name: demo\n"
        "  minimum_project_gap_um: 10\nprojects:\n"
        "  - team: A01\n    variant: A\n    quadrant: NW\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate key"):
        load_chip_request(integration)


def test_quadrant_slot_derivation_matches_a_examples():
    canonical = [f"W{i:02d}" for i in range(12, 23)] + [f"N{i:02d}" for i in range(1, 12)]
    assert [transform_slot(slot, "NE") for slot in canonical] == (
        [f"E{i:02d}" for i in range(12, 23)] + [f"N{i:02d}" for i in range(22, 11, -1)]
    )
    assert [transform_slot(slot, "SE") for slot in canonical] == (
        [f"E{i:02d}" for i in range(11, 0, -1)] + [f"S{i:02d}" for i in range(22, 11, -1)]
    )
    assert [transform_slot(slot, "SW") for slot in canonical] == (
        [f"W{i:02d}" for i in range(11, 0, -1)] + [f"S{i:02d}" for i in range(1, 12)]
    )


def test_transform_box_normalizes_reflections():
    diearea = (0, 0, 2935, 2935)
    assert transform_box((350, 1475, 1460, 2585), "NE", diearea) == (1475, 1475, 2585, 2585)
    assert transform_box((350, 1475, 1460, 2585), "SE", diearea) == (1475, 350, 2585, 1460)


def test_prefix_is_case_insensitive():
    assert prefix_name("A01", "DATA") == "A01_DATA"
    assert prefix_name("A01", "a01_DATA") == "a01_DATA"


def test_chip_padring_merges_project_and_keeps_boundaries(tmp_path: Path):
    template = Path(__file__).parents[1] / "padring_template.cfg"
    request = ProjectRequest("A01", "D", "SE")
    pins = (
        {"name": "vss", "io_type": "ground"},
        {"name": "sig", "io_type": "input_cmos"},
        {"name": "vdd", "io_type": "power"},
    )
    artifacts = SimpleNamespace(request=request, pins=pins)
    placement = SimpleNamespace(
        artifacts=artifacts,
        transformed_slots=("E05", "E04", "E03"),
    )
    chip = ChipRequest("demo", _base_chip(tmp_path), 10, (request,))
    cfg, mapping = generate_chip_padring(chip, [placement], template)
    assert "PAD E03 E gf180mcu_fd_io__dvdd ;" in cfg
    assert "PAD E04 E gf180mcu_fd_io__in_c ;" in cfg
    assert "PAD E05 E gf180mcu_fd_io__dvss ;" in cfg
    assert cfg.count("BREAK ;") == 2
    assert [pad["slot"] for pad in mapping["pads"] if not pad.get("generated")] == ["E03", "E04", "E05"]


def test_chip_padring_uses_base_chip_io_cell_mapping(tmp_path: Path):
    template = Path(__file__).parents[1] / "padring_template.cfg"
    request = ProjectRequest("A01", "D", "NW")
    pins = (
        {"name": "vss", "io_type": "ground"},
        {"name": "sig", "io_type": "input_cmos"},
        {"name": "vdd", "io_type": "power"},
    )
    placement = SimpleNamespace(
        artifacts=SimpleNamespace(request=request, pins=pins),
        transformed_slots=("W18", "W19", "W20"),
    )
    base = _base_chip(tmp_path)
    base.io_cells["input_cmos"] = "custom_input_cell"
    chip = ChipRequest("demo", base, 10, (request,))
    cfg, _ = generate_chip_padring(chip, [placement], template)
    assert "PAD W19 W custom_input_cell ;" in cfg


def test_top_verilog_separates_input_pad_and_core_net(tmp_path: Path):
    request = ProjectRequest("A01", "A", "NW")
    artifacts = SimpleNamespace(
        request=request,
        pins=(
            {"name": "RST", "io_type": "input_cmos"},
            {"name": "VDD", "io_type": "power"},
        ),
        interface={
            "pins": [
                {"physical_pad_slot": "W12", "project_pin": "RST", "cell_terminal": "Y"},
                {"physical_pad_slot": "W13", "project_pin": "VDD", "cell_terminal": "DVDD"},
            ]
        },
        interface_path=tmp_path / "interface.yaml",
    )
    placement = SimpleNamespace(
        artifacts=artifacts, integrated_top="A01_user_top",
        transformed_slots=("W12", "W13"),
    )
    chip = ChipRequest("demo", _base_chip(tmp_path), 10, (request,))
    output = tmp_path / "demo.v"
    write_top_verilog(output, chip, [placement])
    text = output.read_text(encoding="utf-8")
    assert ".W12(A01_RST)" in text
    assert ".W12_Y(A01_RST__CORE)" in text
    assert ".RST(A01_RST__CORE)" in text
    assert ".W13(A01_VDD)" in text
    assert "W13_DVDD" not in text
