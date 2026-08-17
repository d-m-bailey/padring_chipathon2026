import pytest

from chipathon2026_integration.errors import ConfigError
from chipathon2026_integration.info import get_lvs_config_reference, validate_pins


def test_project_lvs_config_only(minimal_info):
    assert get_lvs_config_reference(minimal_info) == "lvs_config.json"
    with pytest.raises(ConfigError):
        get_lvs_config_reference({"lvs_config": "legacy.json", "pins": []})


def test_validate_pin_types_and_analog(minimal_info):
    pins = validate_pins(minimal_info)
    assert [p["io_type"] for p in pins] == ["input_schmitt", "bidirectional", "analog"]
    assert pins[-1]["secondary_esd"] is True


def test_duplicate_pin_rejected(minimal_info):
    minimal_info["pins"].append({"name": "reset_n", "io_type": "input_cmos"})
    with pytest.raises(ConfigError, match="duplicate"):
        validate_pins(minimal_info)


def test_analog_requires_secondary_esd():
    with pytest.raises(ConfigError, match="secondary_esd"):
        validate_pins({"pins": [{"name": "a", "io_type": "analog"}]})


def test_nonanalog_forbids_secondary_esd():
    with pytest.raises(ConfigError, match="prohibited"):
        validate_pins({"pins": [{"name": "d", "io_type": "input_cmos", "secondary_esd": False}]})


def test_empty_pins_rejected():
    with pytest.raises(ConfigError, match="non-empty"):
        validate_pins({"pins": []})
