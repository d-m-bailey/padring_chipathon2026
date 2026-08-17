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
    assert audit["immutable_slot_count"] == 88


def test_generate_a_mapping_preserves_flip_and_comment(full_template, minimal_info, tmp_path):
    cfg, mapping = generate_padring_config(
        info=minimal_info,
        info_path=tmp_path / "info.yaml",
        template_path=full_template,
    )
    assert mapping["pads"][0]["slot"] == "W13"
    assert mapping["pads"][0]["instance"] == "reset_n"
    assert mapping["pads"][1]["slot"] == "W14"
    assert "PAD data_7 W FLIP gf180mcu_fd_io__bi_t ;" in cfg
    assert "PAD ain W gf180mcu_fd_io__asig_5p0 ; # keep me" in cfg
    assert "PAD unused_W16 W gf180mcu_fd_io__asig_5p0 ;" in cfg
    assert "PAD W11 W gf180mcu_fd_io__dvdd ;" in cfg
    assert "PAD W12 W gf180mcu_fd_io__dvss ;" in cfg


def test_sanitization_collision(full_template, minimal_info, tmp_path):
    minimal_info["pins"] = [
        {"name": "data[7]", "io_type": "bidirectional"},
        {"name": "data_7", "io_type": "bidirectional"},
    ]
    with pytest.raises(ConfigError, match="collides after sanitization"):
        generate_padring_config(info=minimal_info, info_path=tmp_path/"i.yaml", template_path=full_template)


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
