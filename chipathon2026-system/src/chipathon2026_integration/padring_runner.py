from __future__ import annotations

import subprocess
from pathlib import Path

from .constants import REQUIRED_PADRING_LEF_CELLS
from .errors import ConfigError
from .padring_outputs import add_canonical_pins_to_def, write_canonical_verilog


def required_lef_paths(tech_pdk: Path) -> list[Path]:
    root = tech_pdk / "libs.ref" / "gf180mcu_fd_io" / "lef"
    return [root / f"{cell}.lef" for cell in REQUIRED_PADRING_LEF_CELLS]


def build_padring_command(
    *,
    padring_exe: Path,
    tech_pdk: Path,
    cfg: Path,
    output_def: Path,
    output_svg: Path | None = None,
    output_verilog: Path | None = None,
    mapping_path: Path | None = None,
    def_dbu: float = 0.005,
    verbose: bool = True,
) -> list[str]:
    cmd = [str(padring_exe)]
    if verbose:
        cmd.append("-v")
    for lef in required_lef_paths(tech_pdk):
        cmd.extend(["--lef", str(lef)])
    if output_svg is not None:
        cmd.extend(["--svg", str(output_svg)])
    cmd.extend(["--dbu", str(def_dbu)])
    cmd.extend(["--def", str(output_def), str(cfg)])
    return cmd


def run_padring(**kwargs) -> subprocess.CompletedProcess[str]:
    padring_exe: Path = kwargs["padring_exe"]
    tech_pdk: Path = kwargs["tech_pdk"]
    cfg: Path = kwargs["cfg"]
    if not padring_exe.exists():
        raise ConfigError(f"padring executable not found: {padring_exe}")
    if not cfg.exists():
        raise ConfigError(f"padring config not found: {cfg}")
    missing = [path for path in required_lef_paths(tech_pdk) if not path.exists()]
    if missing:
        raise ConfigError("missing required GF180 I/O LEF files: " + ", ".join(map(str, missing)))
    kwargs["output_def"].parent.mkdir(parents=True, exist_ok=True)
    if kwargs.get("output_svg") is not None:
        kwargs["output_svg"].parent.mkdir(parents=True, exist_ok=True)
    if kwargs.get("output_verilog") is not None:
        kwargs["output_verilog"].parent.mkdir(parents=True, exist_ok=True)
    mapping_path = kwargs.pop("mapping_path", None)
    output_verilog = kwargs.pop("output_verilog", None)
    if mapping_path is None:
        raise ConfigError("run-padring requires --mapping to generate the canonical padring interface")
    if not mapping_path.exists():
        raise ConfigError(f"pad mapping not found: {mapping_path}")
    cmd = build_padring_command(**kwargs)
    result = subprocess.run(cmd, text=True, check=True, capture_output=False)
    lef_paths = required_lef_paths(tech_pdk)
    add_canonical_pins_to_def(kwargs["output_def"], mapping_path, lef_paths)
    if output_verilog is not None:
        write_canonical_verilog(output_verilog, kwargs["output_def"], mapping_path, cfg, lef_paths)
    return result
