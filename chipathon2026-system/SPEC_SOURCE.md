# Specification source

This implementation was recreated from the live GitHub specification:

- Repository: `d-m-bailey/padring_chipathon2026`
- Branch: `chipathon2026`
- File: `ChatGPT_spec.md`
- Blob SHA read while recreating this implementation: `7398a4da36e4d6ad9f9b76c06813b073c9c0ed2f`

The code intentionally pins the SHA in generated mapping metadata so it is
possible to tell which specification revision produced an artifact.

The GF180 project-terminal list was checked against the upstream I/O-library
commit referenced by the current GF180MCU PDK checkout at recreation time:

- Repository: `google/globalfoundries-pdk-libs-gf180mcu_fd_io`
- Commit: `2aeec51ea2824b6cc0b396acfc39f4535f40b23a`

The upstream Verilog is used only as authoritative evidence for cell ports. The
integration policy selecting project-facing terminals is centralized in
`constants.py` because section 30.6 of the Chipathon specification still marks
that policy as a finalization item.
