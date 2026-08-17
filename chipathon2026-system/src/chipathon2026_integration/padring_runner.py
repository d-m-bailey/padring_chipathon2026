from __future__ import annotations

import subprocess
from pathlib import Path

from .constants import REQUIRED_PADRING_LEF_CELLS
from .errors import ConfigError


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
    verbose: bool = True,
) -> list[str]:
    cmd = [str(padring_exe)]
    if verbose:
        cmd.append("-v")
    for lef in required_lef_paths(tech_pdk):
        cmd.extend(["--lef", str(lef)])
    if output_svg is not None:
        cmd.extend(["--svg", str(output_svg)])
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
    cmd = build_padring_command(**kwargs)
    return subprocess.run(cmd, text=True, check=True, capture_output=False)
