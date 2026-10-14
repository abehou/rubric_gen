"""Run the Result50 extension through the validated Result40 owner."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
RESULT40 = ROOT / "experiments/trace-v21-execution-verified-provenance-result40/run.py"
spec = importlib.util.spec_from_file_location("result50_shared_owner", RESULT40)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load the validated Result40 owner")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


if __name__ == "__main__":
    module.main()
