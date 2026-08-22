from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ConfigError

VARIABLE_RE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")


def load_lvs_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: malformed JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a JSON object")
    return data


def resolve_json_variables(config: dict[str, Any], *, uprj_root: str | None = None) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    resolving: list[str] = []

    def resolve_key(key: str) -> Any:
        if key in resolved:
            return resolved[key]
        if key in resolving:
            cycle = resolving[resolving.index(key):] + [key]
            raise ConfigError("cyclic variable reference in lvs_config.json: " + " -> ".join(cycle))
        if key not in config:
            raise KeyError(key)
        resolving.append(key)
        try:
            value = resolve_value(config[key])
        finally:
            resolving.pop()
        resolved[key] = value
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")
        if name == "UPRJ_ROOT":
            return uprj_root if uprj_root is not None else match.group(0)
        if name not in config:
            return match.group(0)
        value = resolve_key(name)
        if isinstance(value, (dict, list)):
            raise ConfigError(f"${name} refers to a non-scalar JSON value")
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def resolve_string(value: str) -> str:
        current = value
        for _ in range(100):
            updated = VARIABLE_RE.sub(replace, current)
            if updated == current:
                return current
            current = updated
        raise ConfigError(f"too many levels of variable substitution while resolving {value!r}")

    def resolve_value(value: Any) -> Any:
        if isinstance(value, str):
            return resolve_string(value)
        if isinstance(value, list):
            return [resolve_value(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve_value(item) for key, item in value.items()}
        return value

    for key in config:
        resolve_key(key)
    return resolved


def get_layout_file(config: dict[str, Any], *, uprj_root: str | None = None) -> str:
    resolved = resolve_json_variables(config, uprj_root=uprj_root)
    value = resolved.get("LAYOUT_FILE")
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("lvs_config.json does not contain a valid LAYOUT_FILE string")
    unresolved = [
        (m.group("braced") or m.group("plain"))
        for m in VARIABLE_RE.finditer(value)
        if (m.group("braced") or m.group("plain")) != "UPRJ_ROOT"
    ]
    if unresolved:
        raise ConfigError("unresolved variable(s) in LAYOUT_FILE: " + ", ".join(sorted(set(unresolved))))
    return value.strip()


def get_top_layout(config: dict[str, Any], *, uprj_root: str | None = None) -> str | None:
    resolved = resolve_json_variables(config, uprj_root=uprj_root)
    value = resolved.get("TOP_LAYOUT")
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_repo_path(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\$\{UPRJ_ROOT\}/?", "", value)
    value = re.sub(r"^\$UPRJ_ROOT/?", "", value)
    value = value.lstrip("/")
    while value.startswith("./"):
        value = value[2:]
    if not value:
        raise ConfigError("empty repository-relative path")
    return value


def resolve_downloaded_gds(config: dict[str, Any], *, team: str, gds_dir: Path) -> Path:
    """Resolve LAYOUT_FILE to the downloader's local <gds-dir>/<team>/<basename>."""
    layout_path = normalize_repo_path(get_layout_file(config))
    candidate = gds_dir / team / Path(layout_path).name
    if not candidate.is_file():
        raise ConfigError(
            f"GDS selected by LAYOUT_FILE ({layout_path}) was not found at {candidate}"
        )
    return candidate
