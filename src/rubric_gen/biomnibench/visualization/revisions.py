"""Revision score-history plots."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .backend import pyplot


def write_revision_score_plot(
    scores: Sequence[int],
    path: Path,
    *,
    task_id: str,
    feedback_policy: str,
) -> None:
    """Atomically write one revision experiment's score history as a PNG."""
    if not scores:
        raise ValueError("revision score plot requires at least one score")

    plt = pyplot()
    turns = list(range(len(scores)))
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.plot(
        turns,
        scores,
        color="#2b6cb0",
        marker="o",
        markersize=6,
        linewidth=2,
    )
    for turn, score in zip(turns, scores, strict=True):
        ax.annotate(
            str(score),
            (turn, score),
            xytext=(0, 7 if score < 96 else -14),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color="#2d3748",
        )
    ax.set_xticks(turns)
    ax.set_xlim(-0.35, max(0.35, turns[-1] + 0.35))
    ax.set_ylim(0, 100)
    ax.set_xlabel("Revision turn (0 = initial submission)")
    ax.set_ylabel("Validated score")
    ax.set_title(f"Score improvement: {task_id} ({feedback_policy.replace('_', ' ')})")
    ax.grid(True, color="#e2e8f0", linewidth=0.8)
    fig.tight_layout()

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
    try:
        fig.savefig(temporary_path, format="png", dpi=180)
        os.replace(temporary_path, path)
    finally:
        plt.close(fig)
        temporary_path.unlink(missing_ok=True)
