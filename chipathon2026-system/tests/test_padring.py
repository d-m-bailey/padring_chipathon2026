from pathlib import Path

import pytest

from chipathon2026_integration.constants import A_SLOTS
from chipathon2026_integration.errors import ConfigError, NotFinalizedError
from chipathon2026_integration.padring_cfg import audit_physical_template, generate_padring_config, safe_identifier


def test_a_slots_are_new_cardinal_names():
    assert A_SLOTS[0] == "W13"
    assert A_SLOTS[9] == "W22"
    assert A_SLOTS[10] == "N01"
    assert A_SLOTS[-1] == "N11"
    assert len(A_SLOTS) == 21


def test_safe_identifier():
    assert safe_identifier("data[7]") == "data_7"
    assert safe_identifier("12V!") == "_12V"


def test_audit_valid_full_template(full_template):
    audit = audit_physical_template(full_template)
    assert audit["valid_for_production"]
    assert audit["pad_count"] == 88
    assert audit["immutable_slot_count"] == 88
    assert audit["legacy_instance_names"] == []


def test_generate_a_mapping_preserves_flip_and_comment(full_template, minimal_info, tmp_path):
    cfg, mapping = generate_padring_config(
        info=minimal_info,
        info_path=tmp_path / "info.yaml",
        template_path=full_template,
        team_code="A01",
    )
    assert mapping["pads"][0]["slot"] == "W13"
    assert mapping["team_code"] == "A01"
    assert mapping["pads"][0]["instance"] == "W13"
    assert mapping["pads"][1]["slot"] == "W14"
    assert "PAD W14 W FLIP gf180mcu_fd_io__bi_t ;" in cfg
    assert "PAD W15 W gf180mcu_fd_io__asig_5p0 ; # keep me" in cfg
    assert "PAD W16 W gf180mcu_fd_io__asig_5p0 ;" in cfg
    assert "PAD W15 W gf180mcu_fd_io__asig_5p0 ; # keep me\nBREAK ;" in cfg
    assert "PAD W11 W gf180mcu_fd_io__dvdd ;" in cfg
    assert "PAD W12 W gf180mcu_fd_io__dvss ;" in cfg


def test_production_template_uses_supported_padring_directives(minimal_info, tmp_path):
    template = Path(__file__).parents[1] / "padring_template.cfg"
    cfg, _mapping = generate_padring_config(
        info=minimal_info,
        info_path=tmp_path / "info.yaml",
        template_path=template,
        team_code="A01",
    )

    assert not any(line.lstrip().startswith("LOC ") for line in cfg.splitlines())


def test_project_names_do_not_replace_canonical_instances(full_template, minimal_info, tmp_path):
    minimal_info["pins"] = [
        {"name": "data[7]", "io_type": "bidirectional"},
        {"name": "data_7", "io_type": "bidirectional"},
    ]
    _cfg, mapping = generate_padring_config(
        info=minimal_info, info_path=tmp_path/"i.yaml", template_path=full_template
    )
    assert [pad["instance"] for pad in mapping["pads"][:2]] == ["W13", "W14"]
    assert [pad["pin_name"] for pad in mapping["pads"][:2]] == ["data[7]", "data_7"]


def test_break_inserted_before_second_power_pad(full_template, minimal_info, tmp_path):
    minimal_info["pins"] = [
        {"name": "vdd1", "io_type": "power"},
        {"name": "sig", "io_type": "input_cmos"},
        {"name": "vdd2", "io_type": "power"},
    ]
    cfg, mapping = generate_padring_config(
        info=minimal_info, info_path=tmp_path/"i.yaml", template_path=full_template
    )
    assert "BREAK ;\nPAD W15 W gf180mcu_fd_io__dvdd ; # keep me" in cfg
    assert any(item["reason"] == "repeated_power" for item in mapping["breaks"])


def test_too_many_a_pins(full_template, minimal_info, tmp_path):
    minimal_info["pins"] = [{"name": f"p{i}", "io_type": "input_cmos"} for i in range(22)]
    with pytest.raises(ConfigError, match="only 21"):
        generate_padring_config(info=minimal_info, info_path=tmp_path/"i.yaml", template_path=full_template)


def test_b_block_is_not_finalized(full_template, minimal_info, tmp_path):
    with pytest.raises(NotFinalizedError):
        generate_padring_config(info=minimal_info, info_path=tmp_path/"i.yaml", template_path=full_template, block="B")


def test_legacy_template_rejected(tmp_path, minimal_info):
    path = tmp_path / "legacy.cfg"
    path.write_text("DESIGN d;\nLOC W;\nPAD config1 W gf180mcu_fd_io__bi_t ;\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not a production immutable-slot template"):
        generate_padring_config(info=minimal_info, info_path=tmp_path/"i.yaml", template_path=path)


def test_complete_template_rejects_extra_legacy_pad(full_template, minimal_info, tmp_path):
    text = full_template.read_text(encoding="utf-8")
    full_template.write_text(text + "PAD legacy S gf180mcu_fd_io__asig_5p0 ;\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="unexpected PAD instances"):
        generate_padring_config(info=minimal_info, info_path=tmp_path / "i.yaml", template_path=full_template)
