"""Revision score-history plots."""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path

from .backend import pyplot


# Matplotlib and pyplot keep process-global state and are not thread-safe. Revision
# batches call this function from a ThreadPoolExecutor, so the entire pyplot
# lifecycle (including lazy import/backend initialization) must be serialized.
_PLOT_LOCK = threading.RLock()


def write_revision_score_plot(
    on_policy_scores: Sequence[int],
    fixed_original_scores: Sequence[int],
    path: Path,
    *,
    task_id: str,
    feedback_policy: str,
) -> None:
    """Write on-policy and fixed-original score histories as one PNG."""
    if not on_policy_scores:
        raise ValueError("revision score plot requires at least one score")
    if len(on_policy_scores) != len(fixed_original_scores):
        raise ValueError("revision score series must have equal lengths")

    with _PLOT_LOCK:
        plt = pyplot()
        turns = list(range(len(on_policy_scores)))
        fig, ax = plt.subplots(figsize=(8, 4.8))
        ax.plot(
            turns,
            on_policy_scores,
            color="#2b6cb0",
            marker="o",
            markersize=6,
            linewidth=2,
            label="On-policy rubric",
        )
        ax.plot(
            turns,
            fixed_original_scores,
            color="#c05621",
            marker="s",
            markersize=5,
            linewidth=2,
            linestyle="--",
            label="Fixed original rubric",
        )
        for turn, score in zip(turns, on_policy_scores, strict=True):
            ax.annotate(
                str(score),
                (turn, score),
                xytext=(0, 7 if score < 96 else -14),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                color="#2d3748",
            )
        for turn, score in zip(turns, fixed_original_scores, strict=True):
            if score == on_policy_scores[turn]:
                continue
            ax.annotate(
                str(score),
                (turn, score),
                xytext=(0, -14 if score > 4 else 7),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                color="#7b341e",
            )
        ax.set_xticks(turns)
        ax.set_xlim(-0.35, max(0.35, turns[-1] + 0.35))
        ax.set_ylim(0, 100)
        ax.set_xlabel("Revision turn (0 = initial submission)")
        ax.set_ylabel("Validated score")
        ax.set_title(
            f"Score improvement: {task_id} "
            f"({feedback_policy.replace('_', ' ')})"
        )
        ax.grid(True, color="#e2e8f0", linewidth=0.8)
        ax.legend()
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
