from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

from .errors import ConfigError
from .info import get_lvs_config_reference
from .lvs import get_layout_file, get_top_layout, normalize_repo_path

API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"


def github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "chipathon-2026-integration"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def repo_default_branch(session: requests.Session, repo: str) -> str:
    r = session.get(f"{API_ROOT}/repos/{repo}", timeout=60)
    r.raise_for_status()
    value = r.json().get("default_branch")
    if not isinstance(value, str) or not value:
        raise ConfigError(f"cannot determine default branch for {repo}")
    return value


def get_raw_repo_file(session: requests.Session, repo: str, path: str, ref: str) -> bytes:
    encoded = "/".join(quote(part, safe="") for part in path.lstrip("/").split("/"))
    encoded_ref = quote(ref, safe="")
    r = session.get(f"{RAW_ROOT}/{repo}/{encoded_ref}/{encoded}", timeout=60)
    if r.status_code == 404:
        raise FileNotFoundError(f"{path} not found in {repo}@{ref}")
    r.raise_for_status()
    return r.content


def get_ref_and_info(session: requests.Session, repo: str) -> tuple[str, bytes]:
    try:
        return "main", get_raw_repo_file(session, repo, "info.yaml", "main")
    except FileNotFoundError:
        ref = repo_default_branch(session, repo)
        return ref, get_raw_repo_file(session, repo, "info.yaml", ref)


def parse_info_bytes(data: bytes) -> tuple[dict, str]:
    try:
        info = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise ConfigError(f"malformed info.yaml: {exc}") from exc
    if not isinstance(info, dict):
        raise ConfigError("info.yaml top level must be a mapping")
    return info, normalize_repo_path(get_lvs_config_reference(info))


def parse_lvs_bytes(data: bytes) -> tuple[str, str]:
    try:
        config = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"malformed lvs_config.json: {exc}") from exc
    if not isinstance(config, dict):
        raise ConfigError("lvs_config.json top level must be an object")
    top_layout = get_top_layout(config)
    if top_layout is None:
        raise ConfigError("lvs_config.json does not contain a valid TOP_LAYOUT string")
    return top_layout, normalize_repo_path(get_layout_file(config))


def process_team(
    session: requests.Session,
    team: str,
    repo: str,
    info_dir: Path,
    gds_dir: Path,
    overwrite: bool,
) -> bool:
    print(f"{team}: {repo}")
    if repo == "???":
        print(f"ERROR: Unknown repo for {team}", file=sys.stderr)
        return False
    try:
        ref, info_data = get_ref_and_info(session, repo)
        print(f"  ref:          {ref}")
        info, lvs_path = parse_info_bytes(info_data)
        info_file = info_dir / f"{team}_info.yaml"
        if overwrite or not info_file.exists():
            info_file.write_bytes(info_data)
        else:
            print(f"  info exists:  {info_file} (remote copy was still fetched and parsed)")
        print(f"  info.yaml:    {info_file}")
        print(f"  lvs_config:   {lvs_path}")

        lvs_data = get_raw_repo_file(session, repo, lvs_path, ref)
        top_layout, layout_path = parse_lvs_bytes(lvs_data)
        print(f"  TOP_LAYOUT:   {top_layout}")
        print(f"  LAYOUT_FILE:  {layout_path}")

        gds_data = get_raw_repo_file(session, repo, layout_path, ref)
        team_dir = gds_dir / team
        team_dir.mkdir(parents=True, exist_ok=True)
        gds_file = team_dir / Path(layout_path).name
        if gds_file.exists() and not overwrite:
            print(f"  GDS exists:   {gds_file}")
        else:
            gds_file.write_bytes(gds_data)
            print(f"  GDS saved:    {gds_file}")
        return True
    except (requests.RequestException, FileNotFoundError, ConfigError) as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download Chipathon info.yaml, lvs_config.json target, and GDS files.")
    p.add_argument("input_file", type=Path, help="File containing '<team_code> <owner/repository>' per line")
    p.add_argument("--info-dir", type=Path, default=Path("info"))
    p.add_argument("--gds-dir", type=Path, default=Path("gds"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    args.info_dir.mkdir(parents=True, exist_ok=True)
    args.gds_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(github_headers())
    ok = failed = 0
    for lineno, raw in enumerate(args.input_file.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 2:
            print(f"Line {lineno}: bad format: {line}", file=sys.stderr)
            failed += 1
            continue
        team, repo = fields
        if process_team(session, team, repo, args.info_dir, args.gds_dir, args.overwrite):
            ok += 1
        else:
            failed += 1
    print(f"Successful: {ok}")
    print(f"Failed:     {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
