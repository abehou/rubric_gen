"""Optional terminal progress rendering."""

from __future__ import annotations

import sys
from typing import Any

try:
    from tqdm.auto import tqdm
except ImportError:  # pragma: no cover - exercised only without the dependency.
    tqdm = None


PROGRESS_BAR_FORMAT = (
    "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
    "[{elapsed} elapsed, {remaining} remaining, {rate_fmt}]{postfix}"
)


class TerminalProgress:
    """Context-managed wrapper around the optional terminal progress bar."""

    def __init__(
        self,
        *,
        total: int,
        description: str,
        unit: str,
        position: int | None = None,
        leave: bool = True,
    ) -> None:
        self.total = total
        self.description = description
        self.unit = unit
        self.position = position
        self.leave = leave
        self._bar: Any = None

    def __enter__(self) -> "TerminalProgress":
        if tqdm is not None:
            self._bar = tqdm(
                total=self.total,
                desc=self.description,
                unit=self.unit,
                dynamic_ncols=True,
                bar_format=PROGRESS_BAR_FORMAT,
                file=sys.stderr,
                position=self.position,
                leave=self.leave,
            )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._bar is not None:
            self._bar.close()

    def set_status(self, status: str) -> None:
        if self._bar is not None:
            self._bar.set_postfix_str(status)

    def update(self) -> None:
        if self._bar is not None:
            self._bar.update(1)
