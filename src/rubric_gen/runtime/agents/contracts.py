"""Small runtime contracts supplied by benchmark integrations."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SessionContract(Protocol):
    """Recovery and output rules for a persistent solver session."""

    recovery_prompt: str
    output_recovery_prompt: str

    def output_errors(self, workspace: Path) -> list[str]: ...


class OutputValidator(Protocol):
    """Validate the completed outputs in one agent workspace."""

    def __call__(self, workspace: Path) -> list[str]: ...


@dataclass(frozen=True)
class RegularFileOutputs:
    """Require a fixed set of regular, non-empty output files."""

    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.names or any(
            not name or Path(name).name != name for name in self.names
        ):
            raise ValueError("required output files must have safe names")

    def __call__(self, workspace: Path) -> list[str]:
        errors: list[str] = []
        for name in self.names:
            try:
                value = os.lstat(workspace / name)
            except OSError:
                errors.append(f"missing_or_empty: {name}")
                continue
            if not stat.S_ISREG(value.st_mode) or value.st_size == 0:
                errors.append(f"missing_or_empty: {name}")
        return errors
