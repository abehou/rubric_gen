"""Build exact public interaction history for simulated-user feedback."""

from __future__ import annotations

import json
from difflib import unified_diff
from pathlib import Path

from rubric_gen.benchmarks import SubmissionBenchmark
from rubric_gen.submission_revision.artifacts import read_json_object


def build_simulated_user_history(
    experiment_dir: Path,
    benchmark: SubmissionBenchmark,
    checkpoint: int,
) -> tuple[dict[str, object], ...]:
    """Return feedback, visible replies, and public changes before a checkpoint."""

    if type(checkpoint) is not int or checkpoint < 0:
        raise ValueError("simulated-user checkpoint must be non-negative")
    history: list[dict[str, object]] = []
    for index in range(checkpoint):
        before_id = f"s{index:03d}"
        after_id = f"s{index + 1:03d}"
        before_workspace = experiment_dir / "submissions" / before_id / "workspace"
        after_workspace = experiment_dir / "submissions" / after_id / "workspace"
        before = benchmark.render_user_review(before_workspace)
        after = benchmark.render_user_review(after_workspace)
        feedback = read_json_object(
            experiment_dir / "feedback" / f"{before_id}.json",
            "simulated-user feedback history",
        )
        history.append(
            {
                "feedback_checkpoint": before_id,
                "user_feedback": {
                    "decision": feedback.get("decision"),
                    "concerns": feedback.get("concerns"),
                },
                "solver_visible_replies": _solver_visible_replies(
                    experiment_dir / "turns" / f"turn-{index + 1:03d}"
                    / "trajectory.stream.jsonl"
                ),
                "revision": {
                    "from_submission": before_id,
                    "to_submission": after_id,
                    "unified_diff": "".join(
                        unified_diff(
                            before.splitlines(keepends=True),
                            after.splitlines(keepends=True),
                            fromfile=before_id,
                            tofile=after_id,
                        )
                    ),
                },
            }
        )
    return tuple(history)


def _solver_visible_replies(path: Path) -> list[str]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"solver trajectory is missing: {path}")
    replies: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
            and item["text"].strip()
        ):
            replies.append(item["text"].strip())
            continue
        if (
            event.get("role") == "assistant"
            and isinstance(event.get("content"), str)
            and event["content"].strip()
        ):
            replies.append(event["content"].strip())
    return replies
