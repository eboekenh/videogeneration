#!/usr/bin/env python3
"""Convenience wrapper for `python mythology_video.py align ...`."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from mythology_video.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["align", *sys.argv[1:]]))
