from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .constants import IO_CELLS
from .errors import ConfigError


def load_info(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: malformed YAML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a YAML mapping")
    return data


def get_lvs_config_reference(info: dict[str, Any]) -> str:
    project = info.get("project")
    if not isinstance(project, dict):
        raise ConfigError("info.yaml must contain a 'project' mapping")
    value = project.get("lvs_config")
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("info.yaml must contain a non-empty project.lvs_config string")
    return value.strip()


def validate_pins(
    info: dict[str, Any], *, io_cells: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    allowed_io_cells = IO_CELLS if io_cells is None else io_cells
    pins = info.get("pins")
    if not isinstance(pins, list) or not pins:
        raise ConfigError("info.yaml must contain a non-empty top-level 'pins' list")

    result: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(pins):
        where = f"pins[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: pin definition must be a mapping")

        name = raw.get("name")
        io_type = raw.get("io_type")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}: 'name' must be a non-empty string")
        name = name.strip()
        if name in seen_names:
            raise ConfigError(f"{where}: duplicate user pin name {name!r}")
        seen_names.add(name)

        if not isinstance(io_type, str) or io_type not in allowed_io_cells:
            raise ConfigError(
                f"{where} ({name}): unsupported io_type {io_type!r}; "
                f"expected one of: {', '.join(allowed_io_cells)}"
            )

        if io_type == "analog":
            if "secondary_esd" not in raw:
                raise ConfigError(
                    f"{where} ({name}): analog pins require secondary_esd: true or false"
                )
            if not isinstance(raw["secondary_esd"], bool):
                raise ConfigError(f"{where} ({name}): secondary_esd must be boolean")
        elif "secondary_esd" in raw:
            raise ConfigError(
                f"{where} ({name}): secondary_esd is prohibited for non-analog pins"
            )

        item = dict(raw)
        item["name"] = name
        item["io_type"] = io_type
        result.append(item)
    return result
