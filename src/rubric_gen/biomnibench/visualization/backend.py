"""Headless matplotlib initialization."""

from __future__ import annotations

import os
import tempfile
from typing import Any


def pyplot() -> Any:
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="biomnibench-mpl-"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt
