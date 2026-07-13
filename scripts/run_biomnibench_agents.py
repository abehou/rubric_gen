#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Run terminal-agent BiomniBench experiments from a uv script."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rubric_gen.biomnibench.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
