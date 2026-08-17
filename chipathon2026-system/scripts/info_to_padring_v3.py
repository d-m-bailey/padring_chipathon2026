#!/usr/bin/env python3
import sys
from chipathon2026_integration.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["generate-padring", *sys.argv[1:]]))
