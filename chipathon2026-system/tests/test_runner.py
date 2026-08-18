from pathlib import Path

from chipathon2026_integration.padring_runner import build_padring_command, required_lef_paths


def test_required_lefs_include_all_current_cells(tmp_path):
    paths = required_lef_paths(tmp_path)
    names = {p.name for p in paths}
    assert "gf180mcu_fd_io__bi_24t.lef" in names
    assert "gf180mcu_fd_io__in_c.lef" in names
    assert "gf180mcu_fd_io__in_s.lef" in names
    assert "gf180mcu_fd_io__dvdd.lef" in names
    assert "gf180mcu_fd_io__dvss.lef" in names
    assert len(paths) == 10


def test_command_shape(tmp_path):
    cmd = build_padring_command(
        padring_exe=Path("/bin/padring"), tech_pdk=tmp_path, cfg=Path("ring.cfg"),
        output_def=Path("ring.def"), output_svg=Path("ring.svg"),
        output_verilog=Path("ring.v"),
    )
    assert cmd[0] == "/bin/padring"
    assert cmd.count("--lef") == 10
    assert str(tmp_path / "libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__fill5.lef") in cmd
    assert "--ver" not in cmd
    assert cmd[cmd.index("--dbu") + 1] == "0.005"
    assert cmd[-1] == "ring.cfg"
