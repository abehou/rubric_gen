"""Consistent environment for Python-capable subprocesses."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path


NUMERICAL_THREAD_LIMITS = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


def controlled_python_prefix() -> Path:
    """Return the checkout virtual environment when this is a source checkout."""

    project_root = Path(__file__).resolve().parents[3]
    checkout_prefix = project_root / ".venv"
    checkout_python = checkout_prefix / "bin" / "python"
    if (checkout_prefix / "pyvenv.cfg").is_file() and checkout_python.exists():
        return checkout_prefix
    return Path(sys.prefix)


def controlled_process_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Pin subprocesses to this interpreter and one numerical-library thread."""

    environment = dict(os.environ if source is None else source)
    environment.update(NUMERICAL_THREAD_LIMITS)
    environment["PYTHONNOUSERSITE"] = "1"

    python_prefix = controlled_python_prefix()
    python_bin = str(python_prefix / "bin")
    path_entries = [
        entry
        for entry in environment.get("PATH", "").split(os.pathsep)
        if entry and entry != python_bin
    ]
    environment["PATH"] = os.pathsep.join((python_bin, *path_entries))
    if (python_prefix / "pyvenv.cfg").is_file():
        environment["VIRTUAL_ENV"] = str(python_prefix)
    else:
        environment.pop("VIRTUAL_ENV", None)
    return environment


def install_controlled_process_environment() -> None:
    """Apply the controlled defaults to this process and future children."""

    os.environ.update(controlled_process_environment())
