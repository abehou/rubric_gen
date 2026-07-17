"""Visualize paired judge score comparisons."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backend import pyplot


@dataclass(frozen=True)
class JudgeComparisonConfig:
    run_dir: Path
    trace_scores: Path | None = None
    trajectory_scores: Path | None = None
    left_scores: Path | None = None
    right_scores: Path | None = None
    left_label: str = "Summary/trace judge"
    right_label: str = "Trajectory judge"
    out_dir: Path | None = None
    label_top_n: int = 8

    @classmethod
    def from_namespace(cls, args: Any) -> "JudgeComparisonConfig":
        trace_scores = getattr(args, "trace_scores", None)
        trajectory_scores = getattr(args, "trajectory_scores", None)
        left_scores = getattr(args, "left_scores", None)
        right_scores = getattr(args, "right_scores", None)
        left_label = getattr(args, "left_label", None)
        right_label = getattr(args, "right_label", None)
        return cls(
            run_dir=Path(args.run_dir).expanduser().resolve(),
            trace_scores=Path(trace_scores).expanduser().resolve()
            if trace_scores
            else None,
            trajectory_scores=Path(trajectory_scores).expanduser().resolve()
            if trajectory_scores
            else None,
            left_scores=Path(left_scores).expanduser().resolve()
            if left_scores
            else None,
            right_scores=Path(right_scores).expanduser().resolve()
            if right_scores
            else None,
            left_label=left_label or "Summary/trace judge",
            right_label=right_label or "Trajectory judge",
            out_dir=Path(args.out_dir).expanduser().resolve() if args.out_dir else None,
            label_top_n=max(0, args.label_top_n),
        )


@dataclass(frozen=True)
class TaskJudgeComparison:
    task: str
    left_mean: float
    right_mean: float
    left_stddev: float
    right_stddev: float
    left_scores: tuple[int, ...]
    right_scores: tuple[int, ...]

    @property
    def delta(self) -> float:
        return self.right_mean - self.left_mean


class JudgeComparisonPlotter:
    def __init__(self, config: JudgeComparisonConfig) -> None:
        self.config = config

    @property
    def left_scores_path(self) -> Path:
        return (
            self.config.left_scores
            or self.config.trace_scores
            or self.config.run_dir / "judge-trace-scores.json"
        )

    @property
    def right_scores_path(self) -> Path:
        return (
            self.config.right_scores
            or self.config.trajectory_scores
            or self.config.run_dir / "judge-trajectory-scores.json"
        )

    @property
    def out_dir(self) -> Path:
        return self.config.out_dir or self.config.run_dir / "judge-comparison-plots"

    def run(self) -> int:
        comparisons = self.load_comparisons()
        if not comparisons:
            raise SystemExit("No overlapping scored tasks found in judge score files.")

        self.out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.out_dir / "judge_comparison.csv"
        scatter_path = self.out_dir / "score_scatter.png"
        delta_path = self.out_dir / "task_delta_sorted.png"

        self.write_csv(comparisons, csv_path)
        self.plot_score_scatter(comparisons, scatter_path)
        self.plot_delta_bars(comparisons, delta_path)

        print(f"Wrote comparison CSV: {csv_path}")
        print(f"Wrote paired scatter: {scatter_path}")
        print(f"Wrote sorted delta bars: {delta_path}")
        return 0

    def load_comparisons(self) -> list[TaskJudgeComparison]:
        left = self._task_scores(self.left_scores_path)
        right = self._task_scores(self.right_scores_path)
        comparisons = []
        for task in sorted(set(left) & set(right)):
            left_task = left[task]
            right_task = right[task]
            if left_task["mean_score"] is None or right_task["mean_score"] is None:
                continue
            comparisons.append(
                TaskJudgeComparison(
                    task=task,
                    left_mean=float(left_task["mean_score"]),
                    right_mean=float(right_task["mean_score"]),
                    left_stddev=float(left_task.get("score_stddev") or 0.0),
                    right_stddev=float(right_task.get("score_stddev") or 0.0),
                    left_scores=tuple(
                        int(score) for score in left_task.get("scores", [])
                    ),
                    right_scores=tuple(
                        int(score) for score in right_task.get("scores", [])
                    ),
                )
            )
        return comparisons

    def write_csv(self, comparisons: list[TaskJudgeComparison], path: Path) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "task",
                    "left_mean",
                    "right_mean",
                    "delta",
                    "left_stddev",
                    "right_stddev",
                    "left_scores",
                    "right_scores",
                ],
            )
            writer.writeheader()
            for item in sorted(comparisons, key=lambda row: row.delta):
                writer.writerow(
                    {
                        "task": item.task,
                        "left_mean": item.left_mean,
                        "right_mean": item.right_mean,
                        "delta": round(item.delta, 4),
                        "left_stddev": item.left_stddev,
                        "right_stddev": item.right_stddev,
                        "left_scores": ",".join(
                            str(score) for score in item.left_scores
                        ),
                        "right_scores": ",".join(
                            str(score) for score in item.right_scores
                        ),
                    }
                )

    def plot_score_scatter(
        self, comparisons: list[TaskJudgeComparison], path: Path
    ) -> None:
        plt = self._pyplot()
        fig, ax = plt.subplots(figsize=(7, 7))
        x = [item.left_mean for item in comparisons]
        y = [item.right_mean for item in comparisons]
        deltas = [item.delta for item in comparisons]
        colors = ["#2b6cb0" if delta >= 0 else "#c53030" for delta in deltas]

        ax.errorbar(
            x,
            y,
            xerr=[item.left_stddev for item in comparisons],
            yerr=[item.right_stddev for item in comparisons],
            fmt="none",
            ecolor="#a0aec0",
            elinewidth=0.8,
            alpha=0.55,
            zorder=1,
        )
        ax.scatter(
            x, y, c=colors, s=48, alpha=0.9, edgecolor="white", linewidth=0.7, zorder=2
        )
        ax.plot([0, 100], [0, 100], color="#4a5568", linestyle="--", linewidth=1.0)
        ax.set_xlim(-2, 102)
        ax.set_ylim(-2, 102)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(f"{self.config.left_label} mean score")
        ax.set_ylabel(f"{self.config.right_label} mean score")
        ax.set_title(f"{self.config.right_label} vs {self.config.left_label}")
        ax.grid(True, color="#edf2f7", linewidth=0.8)

        for item in self._top_delta_items(comparisons):
            ax.annotate(
                item.task,
                (item.left_mean, item.right_mean),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=8,
                color="#2d3748",
            )

        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)

    def plot_delta_bars(
        self, comparisons: list[TaskJudgeComparison], path: Path
    ) -> None:
        plt = self._pyplot()
        ordered = sorted(comparisons, key=lambda item: item.delta)
        tasks = [item.task for item in ordered]
        deltas = [item.delta for item in ordered]
        colors = ["#c53030" if delta < 0 else "#2b6cb0" for delta in deltas]
        height = max(7, 0.23 * len(ordered))

        fig, ax = plt.subplots(figsize=(9, height))
        ax.barh(tasks, deltas, color=colors, alpha=0.88)
        ax.axvline(0, color="#2d3748", linewidth=1.0)
        ax.set_xlabel(f"{self.config.right_label} mean - {self.config.left_label} mean")
        ax.set_ylabel("Task")
        ax.set_title("Task-Level Judge Score Delta")
        ax.grid(axis="x", color="#edf2f7", linewidth=0.8)

        for index, item in enumerate(ordered):
            if abs(item.delta) < 0.05:
                continue
            x_pos = item.delta + (0.35 if item.delta >= 0 else -0.35)
            ha = "left" if item.delta >= 0 else "right"
            ax.text(x_pos, index, f"{item.delta:+.1f}", va="center", ha=ha, fontsize=7)

        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)

    def _top_delta_items(
        self, comparisons: list[TaskJudgeComparison]
    ) -> list[TaskJudgeComparison]:
        return sorted(comparisons, key=lambda item: abs(item.delta), reverse=True)[
            : self.config.label_top_n
        ]

    def _task_scores(self, path: Path) -> dict[str, dict[str, Any]]:
        if not path.is_file():
            raise SystemExit(f"Missing judge score file: {path}")
        data = json.loads(path.read_text())
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            raise SystemExit(f"Judge score file has no task list: {path}")
        return {
            str(task["task"]): task
            for task in tasks
            if isinstance(task, dict) and "task" in task
        }

    def _pyplot(self) -> Any:
        return pyplot()
