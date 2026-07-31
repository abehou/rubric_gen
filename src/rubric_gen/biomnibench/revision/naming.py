"""Canonical directory identities for revision batches and experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.prompts import PromptProfile
from rubric_gen.biomnibench.judging.models import DEFAULT_JUDGE_MODEL
from rubric_gen.biomnibench.utils.paths import (
    PROJECT_ROOT,
    directory_component,
    resolve_project_path,
)

from .evolution import RubricEvolution
from .feedback import FeedbackPolicy


def _rubric_identity(args: argparse.Namespace, rubric_set: Path | None = None) -> str:
    selected = rubric_set if rubric_set is not None else getattr(args, "rubric_set", None)
    if selected is not None:
        return f"set-{directory_component(selected)}"
    return directory_component(args.rubric or "rubric.txt")


def _proposer_identity(args: argparse.Namespace) -> tuple[str, ...]:
    if args.rubric_evolution != RubricEvolution.AGENT.value:
        return ()
    digest = hashlib.sha256(args.rubric_proposer_model.encode()).hexdigest()[:8]
    return (f"rp-{digest}-q{args.rubric_proposer_step_limit}",)


def revision_runs_root() -> Path:
    return PROJECT_ROOT / "runs" / "biomnibench-revisions"


def revision_batch_name(args: argparse.Namespace, stamp: str) -> str:
    feedback = (
        "full-v-score"
        if args.full_v_score
        else FeedbackPolicy(args.feedback_policy).value.replace("_", "-")
    )
    selection = (
        f"top-{'all' if args.top == -1 else args.top}"
        if args.top is not None
        else "tasks-1"
    )
    components = (
        selection,
        f"fb-{feedback}",
        f"pr-{directory_component(args.prompt)}",
        f"sd-{directory_component(Path(args.seed_run_dir).name)}",
        f"re-{directory_component(args.rubric_evolution)}",
        *_proposer_identity(args),
        f"n-{args.revision_rounds}",
        f"p-{directory_component(args.provider)}",
        f"m-{directory_component(args.model)}",
        f"j-{directory_component(args.judge_model or DEFAULT_JUDGE_MODEL)}",
        f"rb-{_rubric_identity(args)}",
        f"v-{directory_component(args.review)}",
        f"sb-{int(args.sandbox)}",
        f"st-{int(args.skip_trust)}",
        f"web-{int(args.allow_web)}",
        f"net-{int(args.allow_network)}",
        f"ap-{directory_component(args.approval_mode)}",
        f"mc-{args.max_review_chars if args.max_review_chars is not None else 'all'}",
        f"c-{args.max_concurrency}",
        f"x-{directory_component(args.executable)}",
        f"raw-{int(args.raw)}",
    )
    name = "--".join((f"revision-{stamp}", *components))
    if len(name) > 240:
        raise ValueError("derived revision batch directory name is too long")
    return name


def timestamped_revision_batch_dir(args: argparse.Namespace) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return revision_runs_root() / revision_batch_name(args, stamp)


def latest_revision_batch_dir(args: argparse.Namespace, task_ids: list[str]) -> Path:
    root = revision_runs_root()
    suffix = revision_batch_name(args, "TIMESTAMP").split("--", 1)[1]
    candidates: list[Path] = []
    for path in root.glob(f"revision-*--{suffix}"):
        try:
            manifest = json.loads((path / "batch.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("task_ids") == task_ids:
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(
            "no previous revision batch matches the current arguments and tasks"
        )
    return sorted(candidates)[-1]


def revision_experiment_dir(
    args: argparse.Namespace,
    task_dir: Path,
    feedback_policy: FeedbackPolicy,
    rubric_set: Path | None,
    agent: AgentRunConfig,
    prompt_profile: PromptProfile = PromptProfile.BASE,
) -> Path:
    """Derive an identity-bearing experiment directory for one configuration."""

    experiment_dir = resolve_project_path(args.experiment_dir)
    if (
        getattr(args, "revision_batch_layout", False)
        or getattr(args, "top", None) is not None
        or getattr(args, "full_v_score", False)
    ):
        task_root = experiment_dir / directory_component(task_dir.name)
        if getattr(args, "full_v_score", False):
            return task_root / feedback_policy.value.replace("_", "-")
        return task_root
    if (
        (args.resume or getattr(args, "restart", False))
        and os.path.lexists(experiment_dir)
    ):
        return experiment_dir
    components = (
        f"t-{directory_component(task_dir.name)}",
        f"fb-{directory_component(feedback_policy.value.replace('_', '-'))}",
        f"pr-{directory_component(prompt_profile.value)}",
        f"sd-{directory_component(Path(args.seed_run_dir).name)}",
        f"re-{directory_component(args.rubric_evolution)}",
        *_proposer_identity(args),
        f"n-{args.revision_rounds}",
        f"p-{directory_component(agent.provider)}",
        f"m-{directory_component(agent.model)}",
        f"j-{directory_component(args.judge_model or DEFAULT_JUDGE_MODEL)}",
        f"rb-{_rubric_identity(args, rubric_set)}",
        f"v-{directory_component(args.review)}",
        f"sb-{int(agent.sandbox)}",
        f"st-{int(agent.skip_trust)}",
        f"web-{int(agent.allow_web)}",
        f"net-{int(agent.allow_network)}",
        f"ap-{directory_component(agent.approval_mode)}",
        f"mc-{args.max_review_chars if args.max_review_chars is not None else 'all'}",
        f"x-{directory_component(agent.executable)}",
        f"raw-{int(agent.raw)}",
    )
    name = "--".join((experiment_dir.name, *components))
    if len(name) > 240:
        raise ValueError(
            "derived experiment directory name is too long; choose a shorter "
            "--experiment-dir base name"
        )
    return experiment_dir.with_name(name)
