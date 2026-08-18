"""Constants taken from the live ChatGPT_spec.md and pinned GF180 sources."""

SPEC_REPOSITORY = "d-m-bailey/padring_chipathon2026"
SPEC_BRANCH = "chipathon2026"
SPEC_PATH = "ChatGPT_spec.md"
SPEC_BLOB_SHA = "7398a4da36e4d6ad9f9b76c06813b073c9c0ed2f"

GF180_IO_REPOSITORY = "google/globalfoundries-pdk-libs-gf180mcu_fd_io"
GF180_IO_COMMIT = "2aeec51ea2824b6cc0b396acfc39f4535f40b23a"

IO_CELLS = {
    "input_cmos": "gf180mcu_fd_io__in_c",
    "input_schmitt": "gf180mcu_fd_io__in_s",
    "bidirectional": "gf180mcu_fd_io__bi_t",
    "bidirectional_24ma": "gf180mcu_fd_io__bi_24t",
    "analog": "gf180mcu_fd_io__asig_5p0",
    "power": "gf180mcu_fd_io__dvdd",
    "ground": "gf180mcu_fd_io__dvss",
}

ANALOG_PLACEHOLDER_CELL = "gf180mcu_fd_io__asig_5p0"
POWER_CELL = "gf180mcu_fd_io__dvdd"
GROUND_CELL = "gf180mcu_fd_io__dvss"

# The explicit list in section 14 is authoritative.  The prose sentence that
# still says L13 is intentionally not used.
A_SLOTS = (
    "W13", "W14", "W15", "W16", "W17", "W18", "W19", "W20", "W21", "W22",
    "N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09", "N10", "N11",
)

BLOCK_SLOTS = {
    "A": A_SLOTS,
}

UNFINALIZED_BLOCKS = {"B", "C", "D", "E"}

ALL_PHYSICAL_SLOTS = tuple(
    f"{side}{number:02d}"
    for side in ("N", "E", "S", "W")
    for number in range(1, 23)
)

RESERVED_VERTICAL_POWER_GROUND_SLOTS = ("W11", "W12", "E11", "E12")

REQUIRED_PADRING_LEF_CELLS = (
    "gf180mcu_fd_io__cor",
    "gf180mcu_fd_io__fill5",
    "gf180mcu_fd_io__brk5",
    "gf180mcu_fd_io__bi_t",
    "gf180mcu_fd_io__bi_24t",
    "gf180mcu_fd_io__in_c",
    "gf180mcu_fd_io__in_s",
    "gf180mcu_fd_io__asig_5p0",
    "gf180mcu_fd_io__dvdd",
    "gf180mcu_fd_io__dvss",
)

# Exact module ports from the pinned upstream GF180 I/O Verilog sources.
CELL_PORTS = {
    "gf180mcu_fd_io__in_c": ("PU", "PD", "PAD", "Y", "DVDD", "DVSS", "VDD", "VSS"),
    "gf180mcu_fd_io__in_s": ("PU", "PD", "PAD", "Y", "DVDD", "DVSS", "VDD", "VSS"),
    "gf180mcu_fd_io__bi_t": (
        "CS", "SL", "IE", "OE", "PU", "PD", "A", "PDRV0", "PDRV1", "PAD", "Y",
        "DVDD", "DVSS", "VDD", "VSS",
    ),
    "gf180mcu_fd_io__bi_24t": (
        "CS", "SL", "IE", "OE", "PU", "PD", "A", "PAD", "Y", "DVDD", "DVSS", "VDD", "VSS",
    ),
    "gf180mcu_fd_io__asig_5p0": ("ASIG5V", "DVDD", "DVSS", "VDD", "VSS"),
    "gf180mcu_fd_io__dvdd": ("DVDD", "DVSS", "VSS"),
    "gf180mcu_fd_io__dvss": ("DVDD", "DVSS", "VDD"),
}

# Project-facing terminals are derived from the upstream module ports by
# removing the physical pad terminal and supply rails.  This is an integration
# policy, kept centralized so it can be replaced when section 30.6 is finalized.
CELL_PROJECT_TERMINALS = {
    "gf180mcu_fd_io__in_c": ("PU", "PD", "Y"),
    "gf180mcu_fd_io__in_s": ("PU", "PD", "Y"),
    "gf180mcu_fd_io__bi_t": ("CS", "SL", "IE", "OE", "PU", "PD", "A", "PDRV0", "PDRV1", "Y"),
    "gf180mcu_fd_io__bi_24t": ("CS", "SL", "IE", "OE", "PU", "PD", "A", "Y"),
    "gf180mcu_fd_io__asig_5p0": ("ASIG5V",),
}
