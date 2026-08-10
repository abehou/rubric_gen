"""Analyze rubric metadata and reward-hacking detections in matched runs.

The two completed top-30 studies use the same factorial design. Each task,
replicate, feedback policy, and prompt policy has a static and prospective
(dynamic) rubric assignment. This script validates those pairs, extracts rubric
metadata, joins the three-model reward-hacking audit, and writes reproducible
tables, a report, and a figure.
"""

from __future__ import annotations

import argparse
import csv
import json
import itertools
import math
import os
import random
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "analyses" / "luna-top30-rubric-metadata-rh"

POSITIVE_DECISION = "reward_hacking_detected"
NEGATIVE_DECISION = "no_reward_hacking_detected"
MAJORITY_DETECTOR = "three-model-majority"
AVAILABLE_MAJORITY_DETECTOR = "available-two-vote-majority"


@dataclass(frozen=True)
class StudySpec:
    label: str
    experiment_id: str

    @property
    def study_dir(self) -> Path:
        return ROOT / "runs" / "biomnibench-studies" / self.experiment_id

    @property
    def detection_dir(self) -> Path:
        return ROOT / "runs" / "biomnibench-detections" / self.experiment_id


STUDIES = (
    StudySpec("semi", "luna-top30-semi-r10"),
    StudySpec("full", "luna-top30-full-r10"),
)


@dataclass(frozen=True)
class TextMetadata:
    chars: int
    words: int
    lines: int
    criteria: int
    level_options: int
    penalty_capacity: float


@dataclass(frozen=True)
class Assignment:
    study: str
    experiment_id: str
    task_id: str
    replicate: int
    prompt: str
    rubric_policy: str
    condition_id: str
    assignment_id: str
    directory: Path
    seed_sha256: str
    initial_rubric: str
    final_rubric: str
    initial_metadata: TextMetadata
    final_metadata: TextMetadata
    changed_rounds: int
    proposal_additions: int
    proposal_no_patches: int
    cumulative_added_chars: int
    cumulative_added_criteria: int
    criterion_exposure_fraction: float


@dataclass
class PairRow:
    study: str
    experiment_id: str
    task_id: str
    replicate: int
    prompt: str
    static_assignment_id: str
    dynamic_assignment_id: str
    baseline_chars: int
    baseline_words: int
    baseline_lines: int
    baseline_criteria: int
    baseline_penalty_capacity: float
    dynamic_final_chars: int
    dynamic_final_words: int
    dynamic_final_lines: int
    dynamic_final_criteria: int
    dynamic_final_penalty_capacity: float
    added_chars: int
    added_words: int
    added_lines: int
    added_criteria: int
    added_penalty_capacity: float
    changed_rounds: int
    proposal_additions: int
    proposal_no_patches: int
    cumulative_added_chars: int
    cumulative_added_criteria: int
    criterion_exposure_fraction: float
    outcomes: dict[str, tuple[int | None, int | None]]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    unit_label: str
    divisor: float


FEATURES = (
    FeatureSpec("added_chars", "Rubric length", "+1,000 characters", 1_000.0),
    FeatureSpec("added_criteria", "Criterion count", "+1 criterion", 1.0),
    FeatureSpec(
        "cumulative_added_chars",
        "Character-round exposure",
        "+10,000 character-rounds",
        10_000.0,
    ),
    FeatureSpec(
        "criterion_exposure_fraction",
        "Earlier activation",
        "+0.1 active-round fraction",
        0.1,
    ),
)


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _text_metadata(text: str) -> TextMetadata:
    words = re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", text, flags=re.UNICODE)
    criteria = re.findall(r"(?m)^Criterion\s+\d+:\s*", text)
    level_options = re.findall(r"(?m)^\s+\[[A-Z]\]:", text)
    penalty_capacity = 0.0
    for levels_line in re.findall(r"(?m)^\s*Levels:\s*(.+)$", text):
        values = [
            float(value)
            for value in re.findall(r"[A-Z]=(-?\d+(?:\.\d+)?)", levels_line)
        ]
        if values:
            penalty_capacity += max(0.0, -min(values))
    return TextMetadata(
        chars=len(text),
        words=len(words),
        lines=len(text.splitlines()),
        criteria=len(criteria),
        level_options=len(level_options),
        penalty_capacity=penalty_capacity,
    )


def _latest_detection_summary(spec: StudySpec) -> dict[str, object]:
    candidates = list((spec.detection_dir / "evaluations").glob("*/summary.json"))
    if not candidates:
        raise FileNotFoundError(f"no detector summary under {spec.detection_dir}")
    summary = _load_json(max(candidates, key=lambda path: path.stat().st_mtime))
    if (
        summary.get("detection") != "rh"
        or summary.get("primary_rule") != "majority"
        or summary.get("experiment_ids") != [spec.experiment_id]
    ):
        raise ValueError(f"wrong detection protocol for {spec.experiment_id}")
    return summary


def _load_detection_outcomes(
    spec: StudySpec,
) -> tuple[dict[tuple[str, int, str], dict[str, int | None]], list[str], dict[str, int]]:
    summary = _latest_detection_summary(spec)
    models_value = summary.get("models")
    records_value = summary.get("records")
    if (
        not isinstance(models_value, list)
        or not all(isinstance(model, str) for model in models_value)
        or len(models_value) != 3
        or len(set(models_value)) != 3
        or not isinstance(records_value, list)
    ):
        raise ValueError(f"invalid detector panel in {spec.experiment_id}")
    models = [str(model) for model in models_value]
    panels: dict[tuple[str, int, str], dict[str, int | None]] = defaultdict(dict)
    decision_counts: dict[str, int] = defaultdict(int)
    for value in records_value:
        if not isinstance(value, dict):
            raise ValueError("detector record must be an object")
        source = value.get("source_path")
        model = value.get("model")
        verdict = value.get("verdict")
        if not isinstance(source, str) or model not in models:
            raise ValueError("detector record lacks valid source or model")
        path = Path(source)
        try:
            replicate = int(path.parent.name.removeprefix("rep-"))
        except ValueError as error:
            raise ValueError(f"invalid detector source path: {source}") from error
        key = (path.parent.parent.name, replicate, path.name)
        if str(model) in panels[key]:
            raise ValueError(f"duplicate detector member: {key}, {model}")
        decision = verdict.get("decision") if isinstance(verdict, dict) else None
        decision_text = str(decision) if decision is not None else "missing"
        decision_counts[f"{model}:{decision_text}"] += 1
        if decision == POSITIVE_DECISION:
            panels[key][str(model)] = 1
        elif decision == NEGATIVE_DECISION:
            panels[key][str(model)] = 0
        else:
            panels[key][str(model)] = None
    if len(panels) != 360:
        raise ValueError(
            f"expected 360 detector panels in {spec.experiment_id}; found {len(panels)}"
        )
    for key, panel in panels.items():
        if set(panel) != set(models):
            raise ValueError(f"incomplete detector membership for {key}")
        votes = [panel[model] for model in models]
        panel[MAJORITY_DETECTOR] = (
            int(sum(int(vote) for vote in votes) >= 2)
            if all(vote is not None for vote in votes)
            else None
        )
        positive_votes = sum(vote == 1 for vote in votes)
        negative_votes = sum(vote == 0 for vote in votes)
        panel[AVAILABLE_MAJORITY_DETECTOR] = (
            1
            if positive_votes >= 2
            else 0
            if negative_votes >= 2
            else None
        )
    return panels, models, dict(sorted(decision_counts.items()))


def _load_assignments(spec: StudySpec) -> dict[tuple[str, int, str], Assignment]:
    study = _load_json(spec.study_dir / "study.json")
    records = study.get("records")
    if (
        study.get("experiment_id") != spec.experiment_id
        or study.get("status") != "completed"
        or not isinstance(records, list)
        or len(records) != 360
    ):
        raise ValueError(f"expected completed 360-assignment study: {spec.experiment_id}")

    assignments: dict[tuple[str, int, str], Assignment] = {}
    for value in records:
        if not isinstance(value, dict) or value.get("status") != "completed":
            raise ValueError(f"incomplete study record in {spec.experiment_id}")
        task_id = value.get("task_id")
        replicate = value.get("replicate")
        condition_id = value.get("condition_id")
        experiment_dir = value.get("experiment_dir")
        assignment_id = value.get("assignment_id")
        if (
            not isinstance(task_id, str)
            or not isinstance(replicate, int)
            or not isinstance(condition_id, str)
            or not isinstance(experiment_dir, str)
            or not isinstance(assignment_id, str)
        ):
            raise ValueError(f"invalid study record in {spec.experiment_id}")
        try:
            prompt, rubric_policy = condition_id.split("-", maxsplit=1)
        except ValueError as error:
            raise ValueError(f"invalid condition: {condition_id}") from error
        if prompt not in {"base", "diligent"} or rubric_policy not in {
            "static",
            "prospective",
        }:
            raise ValueError(f"unexpected condition: {condition_id}")

        directory = spec.study_dir / experiment_dir
        manifest = _load_json(directory / "manifest.json")
        if (
            manifest.get("assignment_id") != assignment_id
            or manifest.get("task_id") != task_id
            or manifest.get("replicate") != replicate
            or manifest.get("prompt") != prompt
            or manifest.get("rubric_evolution") != rubric_policy
        ):
            raise ValueError(f"manifest identity mismatch: {assignment_id}")
        seed_sha256 = manifest.get("seed_sha256")
        if not isinstance(seed_sha256, str):
            raise ValueError(f"missing seed hash: {assignment_id}")

        rubric_dir = directory / "rubric"
        initial_rubric = (rubric_dir / "r0000.txt").read_text(encoding="utf-8")
        if rubric_policy == "static":
            final_rubric = initial_rubric
            changed_rounds = 0
            proposal_additions = 0
            proposal_no_patches = 0
            cumulative_added_chars = 0
            cumulative_added_criteria = 0
            criterion_exposure_fraction = 0.0
        else:
            rubric_versions = [initial_rubric] + [
                (rubric_dir / f"r{round_index:04d}.txt").read_text(encoding="utf-8")
                for round_index in range(1, 11)
            ]
            version_metadata = [_text_metadata(text) for text in rubric_versions]
            final_rubric = rubric_versions[-1]
            initial_criteria = version_metadata[0].criteria
            final_criteria = version_metadata[-1].criteria
            proposal_additions = final_criteria - initial_criteria
            if not 0 <= proposal_additions <= 10:
                raise ValueError(f"invalid additive criterion count: {assignment_id}")
            criterion_growth = [
                metadata.criteria - initial_criteria for metadata in version_metadata
            ]
            increments = [
                current - previous
                for previous, current in zip(
                    criterion_growth[:-1],
                    criterion_growth[1:],
                    strict=True,
                )
            ]
            if any(increment not in {0, 1} for increment in increments):
                raise ValueError(f"non-additive rubric history: {assignment_id}")
            changed_rounds = sum(increments)
            if changed_rounds != proposal_additions:
                raise ValueError(f"rubric history count mismatch: {assignment_id}")
            proposal_no_patches = 10 - proposal_additions
            cumulative_added_chars = sum(
                metadata.chars - version_metadata[0].chars
                for metadata in version_metadata[1:]
            )
            cumulative_added_criteria = sum(criterion_growth[1:])
            criterion_exposure_fraction = (
                cumulative_added_criteria / (10.0 * proposal_additions)
                if proposal_additions
                else 0.0
            )

        key = (task_id, replicate, condition_id)
        if key in assignments:
            raise ValueError(f"duplicate assignment: {key}")
        assignments[key] = Assignment(
            study=spec.label,
            experiment_id=spec.experiment_id,
            task_id=task_id,
            replicate=replicate,
            prompt=prompt,
            rubric_policy=rubric_policy,
            condition_id=condition_id,
            assignment_id=assignment_id,
            directory=directory,
            seed_sha256=seed_sha256,
            initial_rubric=initial_rubric,
            final_rubric=final_rubric,
            initial_metadata=_text_metadata(initial_rubric),
            final_metadata=_text_metadata(final_rubric),
            changed_rounds=changed_rounds,
            proposal_additions=proposal_additions,
            proposal_no_patches=proposal_no_patches,
            cumulative_added_chars=cumulative_added_chars,
            cumulative_added_criteria=cumulative_added_criteria,
            criterion_exposure_fraction=criterion_exposure_fraction,
        )
    return assignments


def _build_pairs() -> tuple[list[PairRow], list[str], dict[str, int]]:
    pairs: list[PairRow] = []
    detector_models: list[str] | None = None
    all_decision_counts: dict[str, int] = defaultdict(int)
    baseline_by_task: dict[str, str] = {}
    for spec in STUDIES:
        assignments = _load_assignments(spec)
        outcomes, models, decision_counts = _load_detection_outcomes(spec)
        if detector_models is None:
            detector_models = models
        elif detector_models != models:
            raise ValueError("detector model order differs between studies")
        for key, count in decision_counts.items():
            all_decision_counts[f"{spec.label}:{key}"] += count

        tasks = sorted({key[0] for key in assignments})
        if len(tasks) != 30:
            raise ValueError(f"expected 30 tasks in {spec.experiment_id}")
        for task_id in tasks:
            for replicate in range(1, 4):
                for prompt in ("base", "diligent"):
                    static_condition = f"{prompt}-static"
                    dynamic_condition = f"{prompt}-prospective"
                    static = assignments[task_id, replicate, static_condition]
                    dynamic = assignments[task_id, replicate, dynamic_condition]
                    if static.seed_sha256 != dynamic.seed_sha256:
                        raise ValueError(
                            f"unmatched seed for {spec.label}, {task_id}, "
                            f"rep-{replicate:03d}, {prompt}"
                        )
                    if static.initial_rubric != dynamic.initial_rubric:
                        raise ValueError(
                            f"unmatched initial rubric for {spec.label}, {task_id}, "
                            f"rep-{replicate:03d}, {prompt}"
                        )
                    prior_baseline = baseline_by_task.setdefault(
                        task_id,
                        static.initial_rubric,
                    )
                    if prior_baseline != static.initial_rubric:
                        raise ValueError(f"baseline rubric differs across studies: {task_id}")

                    pair_outcomes: dict[str, tuple[int | None, int | None]] = {}
                    for detector in [
                        MAJORITY_DETECTOR,
                        AVAILABLE_MAJORITY_DETECTOR,
                        *models,
                    ]:
                        pair_outcomes[detector] = (
                            outcomes[task_id, replicate, static_condition][detector],
                            outcomes[task_id, replicate, dynamic_condition][detector],
                        )
                    initial = static.initial_metadata
                    final = dynamic.final_metadata
                    pairs.append(
                        PairRow(
                            study=spec.label,
                            experiment_id=spec.experiment_id,
                            task_id=task_id,
                            replicate=replicate,
                            prompt=prompt,
                            static_assignment_id=static.assignment_id,
                            dynamic_assignment_id=dynamic.assignment_id,
                            baseline_chars=initial.chars,
                            baseline_words=initial.words,
                            baseline_lines=initial.lines,
                            baseline_criteria=initial.criteria,
                            baseline_penalty_capacity=initial.penalty_capacity,
                            dynamic_final_chars=final.chars,
                            dynamic_final_words=final.words,
                            dynamic_final_lines=final.lines,
                            dynamic_final_criteria=final.criteria,
                            dynamic_final_penalty_capacity=final.penalty_capacity,
                            added_chars=final.chars - initial.chars,
                            added_words=final.words - initial.words,
                            added_lines=final.lines - initial.lines,
                            added_criteria=final.criteria - initial.criteria,
                            added_penalty_capacity=(
                                final.penalty_capacity - initial.penalty_capacity
                            ),
                            changed_rounds=dynamic.changed_rounds,
                            proposal_additions=dynamic.proposal_additions,
                            proposal_no_patches=dynamic.proposal_no_patches,
                            cumulative_added_chars=dynamic.cumulative_added_chars,
                            cumulative_added_criteria=(
                                dynamic.cumulative_added_criteria
                            ),
                            criterion_exposure_fraction=(
                                dynamic.criterion_exposure_fraction
                            ),
                            outcomes=pair_outcomes,
                        )
                    )
    if len(pairs) != 360 or detector_models is None:
        raise ValueError(f"expected 360 matched pairs; found {len(pairs)}")
    return pairs, detector_models, dict(sorted(all_decision_counts.items()))


def _quantile_interval(values: Sequence[float]) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    return float(np.quantile(array, 0.025)), float(np.quantile(array, 0.975))


def _cluster_bootstrap_mean(
    rows: Sequence[PairRow],
    values: Sequence[float],
    *,
    draws: int,
    seed: int,
) -> tuple[float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(rows, values, strict=True):
        by_task[row.task_id].append(float(value))
    tasks = sorted(by_task)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(draws):
        selected = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        sample = [value for task in selected for value in by_task[task]]
        samples.append(float(np.mean(sample)))
    return _quantile_interval(samples)


def _exact_mcnemar_p(dynamic_only: int, static_only: int) -> float:
    discordant = dynamic_only + static_only
    if discordant == 0:
        return 1.0
    smaller = min(dynamic_only, static_only)
    lower_tail = sum(
        math.comb(discordant, successes)
        for successes in range(smaller + 1)
    ) / (2**discordant)
    return min(1.0, 2.0 * lower_tail)


def _task_cluster_signflip_p(
    rows: Sequence[PairRow],
    differences: np.ndarray,
    *,
    draws: int,
    seed: int,
) -> float:
    by_task: dict[str, float] = defaultdict(float)
    for row, difference in zip(rows, differences, strict=True):
        by_task[row.task_id] += float(difference)
    contributions = np.asarray([by_task[task] for task in sorted(by_task)])
    observed = abs(float(contributions.sum()))
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.asarray([-1.0, 1.0]), size=(draws, len(contributions)))
    permuted = np.abs(signs @ contributions)
    extreme = int(np.sum(permuted >= observed - 1e-15))
    return (extreme + 1) / (draws + 1)


def _scope_rows(rows: Sequence[PairRow], scope: str) -> list[PairRow]:
    if scope == "pooled":
        return list(rows)
    parts = scope.split("-")
    if len(parts) == 1 and parts[0] in {"semi", "full", "base", "diligent"}:
        part = parts[0]
        return [row for row in rows if row.study == part or row.prompt == part]
    if len(parts) == 2:
        study, prompt = parts
        return [
            row for row in rows if row.study == study and row.prompt == prompt
        ]
    raise ValueError(f"invalid scope: {scope}")


def _paired_rates(
    pairs: Sequence[PairRow],
    detectors: Sequence[str],
    *,
    bootstrap_draws: int,
    permutation_draws: int,
) -> list[dict[str, object]]:
    scopes = (
        "pooled",
        "semi",
        "full",
        "base",
        "diligent",
        "semi-base",
        "semi-diligent",
        "full-base",
        "full-diligent",
    )
    output: list[dict[str, object]] = []
    for detector_index, detector in enumerate(detectors):
        for scope_index, scope in enumerate(scopes):
            candidate_rows = _scope_rows(pairs, scope)
            valid_rows = [
                row
                for row in candidate_rows
                if all(value is not None for value in row.outcomes[detector])
            ]
            static = np.asarray(
                [row.outcomes[detector][0] for row in valid_rows],
                dtype=int,
            )
            dynamic = np.asarray(
                [row.outcomes[detector][1] for row in valid_rows],
                dtype=int,
            )
            differences = dynamic - static
            lower, upper = _cluster_bootstrap_mean(
                valid_rows,
                differences.tolist(),
                draws=bootstrap_draws,
                seed=20260810 + detector_index * 100 + scope_index,
            )
            dynamic_only = int(np.sum((dynamic == 1) & (static == 0)))
            static_only = int(np.sum((dynamic == 0) & (static == 1)))
            output.append(
                {
                    "detector": detector,
                    "scope": scope,
                    "expected_pairs": len(candidate_rows),
                    "complete_pairs": len(valid_rows),
                    "tasks": len({row.task_id for row in valid_rows}),
                    "static_rh": int(static.sum()),
                    "dynamic_rh": int(dynamic.sum()),
                    "static_rate": float(static.mean()),
                    "dynamic_rate": float(dynamic.mean()),
                    "paired_risk_difference": float(differences.mean()),
                    "cluster_bootstrap_ci_low": lower,
                    "cluster_bootstrap_ci_high": upper,
                    "dynamic_only_discordant": dynamic_only,
                    "static_only_discordant": static_only,
                    "mcnemar_exact_p": _exact_mcnemar_p(
                        dynamic_only,
                        static_only,
                    ),
                    "task_cluster_signflip_p": _task_cluster_signflip_p(
                        valid_rows,
                        differences,
                        draws=permutation_draws,
                        seed=20263810 + detector_index * 100 + scope_index,
                    ),
                }
            )
    return output


def _valid_pair_rows(
    rows: Sequence[PairRow],
    detector: str,
) -> list[PairRow]:
    return [
        row
        for row in rows
        if all(value is not None for value in row.outcomes[detector])
    ]


def _stratum_key(row: PairRow) -> tuple[str, str, str]:
    return row.task_id, row.study, row.prompt


def _within_stratum_residuals(
    rows: Sequence[PairRow],
    values: np.ndarray,
) -> np.ndarray:
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[_stratum_key(row)].append(index)
    residuals = values.astype(float).copy()
    for indices in groups.values():
        residuals[indices] -= float(np.mean(residuals[indices]))
    return residuals


def _association_slope(
    rows: Sequence[PairRow],
    x_values: np.ndarray,
    y_values: np.ndarray,
) -> tuple[float, float, int]:
    x_residual = _within_stratum_residuals(rows, x_values)
    y_residual = _within_stratum_residuals(rows, y_values)
    denominator = float(x_residual @ x_residual)
    if denominator <= 0:
        return math.nan, 0.0, 0
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[_stratum_key(row)].append(index)
    informative = sum(
        float(np.var(x_values[indices])) > 0 and len(indices) > 1
        for indices in groups.values()
    )
    slope = float((x_residual @ y_residual) / denominator)
    within_sd = float(np.sqrt(np.mean(x_residual**2)))
    return slope, within_sd, informative


def _cluster_bootstrap_slope(
    rows: Sequence[PairRow],
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    draws: int,
    seed: int,
) -> tuple[float, float]:
    x_residual = _within_stratum_residuals(rows, x_values)
    y_residual = _within_stratum_residuals(rows, y_values)
    by_task: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_task[row.task_id].append(index)
    tasks = sorted(by_task)
    numerators = np.asarray(
        [
            float(x_residual[by_task[task]] @ y_residual[by_task[task]])
            for task in tasks
        ]
    )
    denominators = np.asarray(
        [float(x_residual[by_task[task]] @ x_residual[by_task[task]]) for task in tasks]
    )
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(tasks), size=(draws, len(tasks)))
    sampled_denominators = denominators[selected].sum(axis=1)
    valid = sampled_denominators > 0
    estimates = numerators[selected].sum(axis=1)[valid] / sampled_denominators[valid]
    if int(valid.sum()) < draws * 0.99:
        raise ValueError("too many undefined cluster-bootstrap slopes")
    return _quantile_interval(estimates.tolist())


def _within_stratum_permutation_p(
    rows: Sequence[PairRow],
    x_values: np.ndarray,
    y_values: np.ndarray,
    observed_slope: float,
    *,
    draws: int,
    seed: int,
) -> float:
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[_stratum_key(row)].append(index)
    group_indices = [np.asarray(indices, dtype=int) for indices in groups.values()]
    x_residual = _within_stratum_residuals(rows, x_values)
    y_residual = _within_stratum_residuals(rows, y_values)
    rng = np.random.default_rng(seed)
    denominator = float(x_residual @ x_residual)
    permuted_numerators = np.zeros(draws, dtype=float)
    for indices in group_indices:
        if len(indices) < 2:
            continue
        permutations = np.asarray(list(itertools.permutations(range(len(indices)))))
        choices = rng.integers(0, len(permutations), size=draws)
        permuted_x = x_residual[indices][permutations[choices]]
        permuted_numerators += permuted_x @ y_residual[indices]
    permuted_slopes = permuted_numerators / denominator
    extreme = int(
        np.sum(np.abs(permuted_slopes) >= abs(observed_slope) - 1e-15)
    )
    return (extreme + 1) / (draws + 1)


def _bh_adjust(p_values: Sequence[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        value = min(1.0, p_values[original_index] * count / rank)
        running = min(running, value)
        adjusted[original_index] = running
    return adjusted


def _feature_associations(
    pairs: Sequence[PairRow],
    detectors: Sequence[str],
    *,
    bootstrap_draws: int,
    permutation_draws: int,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    jobs = [
        (MAJORITY_DETECTOR, scope, outcome)
        for scope in (
            "pooled",
            "semi",
            "full",
            "base",
            "diligent",
            "semi-base",
            "semi-diligent",
            "full-base",
            "full-diligent",
        )
        for outcome in ("paired_difference",)
    ]
    jobs.append((MAJORITY_DETECTOR, "pooled", "dynamic_only"))
    jobs.extend(
        (detector, scope, "paired_difference")
        for detector in detectors
        if detector != MAJORITY_DETECTOR
        for scope in ("pooled", "base", "diligent")
    )
    for job_index, (detector, scope, outcome) in enumerate(jobs):
        scoped = _scope_rows(pairs, scope)
        rows = _valid_pair_rows(scoped, detector)
        static = np.asarray(
            [row.outcomes[detector][0] for row in rows],
            dtype=float,
        )
        dynamic = np.asarray(
            [row.outcomes[detector][1] for row in rows],
            dtype=float,
        )
        y_values = dynamic - static if outcome == "paired_difference" else dynamic
        group_results: list[dict[str, object]] = []
        for feature_index, feature in enumerate(FEATURES):
            x_values = np.asarray(
                [float(getattr(row, feature.name)) / feature.divisor for row in rows],
                dtype=float,
            )
            slope, within_sd, informative = _association_slope(
                rows,
                x_values,
                y_values,
            )
            seed_base = 20260810 + job_index * 100 + feature_index * 2
            lower, upper = _cluster_bootstrap_slope(
                rows,
                x_values,
                y_values,
                draws=bootstrap_draws,
                seed=seed_base,
            )
            permutation_p = _within_stratum_permutation_p(
                rows,
                x_values,
                y_values,
                slope,
                draws=permutation_draws,
                seed=seed_base + 1,
            )
            group_results.append(
                {
                    "detector": detector,
                    "scope": scope,
                    "outcome": outcome,
                    "feature": feature.name,
                    "feature_label": feature.label,
                    "unit": feature.unit_label,
                    "complete_pairs": len(rows),
                    "tasks": len({row.task_id for row in rows}),
                    "informative_task_feedback_prompt_strata": informative,
                    "within_stratum_sd_in_reported_units": within_sd,
                    "risk_difference_per_unit": slope,
                    "cluster_bootstrap_ci_low": lower,
                    "cluster_bootstrap_ci_high": upper,
                    "within_stratum_permutation_p": permutation_p,
                    "standardized_risk_difference": slope * within_sd,
                    "standardized_ci_low": lower * within_sd,
                    "standardized_ci_high": upper * within_sd,
                }
            )
        q_values = _bh_adjust(
            [float(result["within_stratum_permutation_p"]) for result in group_results]
        )
        for result, q_value in zip(group_results, q_values, strict=True):
            result["bh_q_within_scope_feature_family"] = q_value
            result["bh_q_across_majority_scope_feature_family"] = None
            result["bh_q_across_detector_sensitivity_family"] = None
            output.append(result)

    majority_scope_family = [
        row
        for row in output
        if row["detector"] == MAJORITY_DETECTOR
        and row["outcome"] == "paired_difference"
    ]
    majority_q_values = _bh_adjust(
        [
            float(row["within_stratum_permutation_p"])
            for row in majority_scope_family
        ]
    )
    for row, q_value in zip(
        majority_scope_family,
        majority_q_values,
        strict=True,
    ):
        row["bh_q_across_majority_scope_feature_family"] = q_value

    detector_sensitivity_family = [
        row
        for row in output
        if row["detector"] != MAJORITY_DETECTOR
        and row["outcome"] == "paired_difference"
    ]
    detector_q_values = _bh_adjust(
        [
            float(row["within_stratum_permutation_p"])
            for row in detector_sensitivity_family
        ]
    )
    for row, q_value in zip(
        detector_sensitivity_family,
        detector_q_values,
        strict=True,
    ):
        row["bh_q_across_detector_sensitivity_family"] = q_value
    return output


def _rankdata(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    order = np.argsort(array, kind="mergesort")
    ranks = np.empty(len(array), dtype=float)
    start = 0
    while start < len(array):
        end = start + 1
        while end < len(array) and array[order[end]] == array[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = rank
        start = end
    return ranks


def _spearman(values_a: Sequence[float], values_b: Sequence[float]) -> float:
    ranks_a = _rankdata(values_a)
    ranks_b = _rankdata(values_b)
    if float(np.std(ranks_a)) == 0 or float(np.std(ranks_b)) == 0:
        return math.nan
    return float(np.corrcoef(ranks_a, ranks_b)[0, 1])


def _spearman_inference(
    x_values: Sequence[float],
    y_values: Sequence[float],
    *,
    bootstrap_draws: int,
    permutation_draws: int,
    seed: int,
) -> tuple[float, float, float, float]:
    observed = _spearman(x_values, y_values)
    rng = np.random.default_rng(seed)
    x_array = np.asarray(x_values, dtype=float)
    y_array = np.asarray(y_values, dtype=float)
    bootstrap: list[float] = []
    for _ in range(bootstrap_draws):
        indices = rng.integers(0, len(x_array), size=len(x_array))
        estimate = _spearman(x_array[indices], y_array[indices])
        if math.isfinite(estimate):
            bootstrap.append(estimate)
    lower, upper = _quantile_interval(bootstrap)
    extreme = 0
    for _ in range(permutation_draws):
        estimate = _spearman(rng.permutation(x_array), y_array)
        extreme += abs(estimate) >= abs(observed) - 1e-15
    p_value = (extreme + 1) / (permutation_draws + 1)
    return observed, lower, upper, p_value


def _baseline_task_associations(
    pairs: Sequence[PairRow],
    *,
    bootstrap_draws: int,
    permutation_draws: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows = _valid_pair_rows(pairs, MAJORITY_DETECTOR)
    by_task: dict[str, list[PairRow]] = defaultdict(list)
    for row in rows:
        by_task[row.task_id].append(row)
    task_rows: list[dict[str, object]] = []
    for task_id in sorted(by_task):
        task_pairs = by_task[task_id]
        baseline_values = {
            (row.baseline_chars, row.baseline_words, row.baseline_criteria)
            for row in task_pairs
        }
        if len(baseline_values) != 1:
            raise ValueError(f"baseline metadata varies within task: {task_id}")
        baseline_chars, baseline_words, baseline_criteria = baseline_values.pop()
        static = np.asarray(
            [row.outcomes[MAJORITY_DETECTOR][0] for row in task_pairs],
            dtype=float,
        )
        dynamic = np.asarray(
            [row.outcomes[MAJORITY_DETECTOR][1] for row in task_pairs],
            dtype=float,
        )
        task_rows.append(
            {
                "task_id": task_id,
                "complete_pairs": len(task_pairs),
                "baseline_chars": baseline_chars,
                "baseline_words": baseline_words,
                "baseline_criteria": baseline_criteria,
                "static_rh_rate": float(static.mean()),
                "dynamic_rh_rate": float(dynamic.mean()),
                "paired_risk_difference": float((dynamic - static).mean()),
                "mean_added_chars": float(
                    np.mean([row.added_chars for row in task_pairs])
                ),
            }
        )

    association_rows: list[dict[str, object]] = []
    baseline_features = (
        ("baseline_chars", "Baseline characters"),
        ("baseline_words", "Baseline words"),
        ("baseline_criteria", "Baseline criteria"),
    )
    outcomes = (
        ("static_rh_rate", "Static RH rate"),
        ("paired_risk_difference", "Dynamic-minus-static RH rate"),
    )
    for outcome_index, (outcome_name, outcome_label) in enumerate(outcomes):
        group: list[dict[str, object]] = []
        for feature_index, (feature_name, feature_label) in enumerate(
            baseline_features
        ):
            estimate, lower, upper, p_value = _spearman_inference(
                [float(row[feature_name]) for row in task_rows],
                [float(row[outcome_name]) for row in task_rows],
                bootstrap_draws=bootstrap_draws,
                permutation_draws=permutation_draws,
                seed=20261810 + outcome_index * 100 + feature_index,
            )
            group.append(
                {
                    "feature": feature_name,
                    "feature_label": feature_label,
                    "outcome": outcome_name,
                    "outcome_label": outcome_label,
                    "tasks": len(task_rows),
                    "spearman_rho": estimate,
                    "task_bootstrap_ci_low": lower,
                    "task_bootstrap_ci_high": upper,
                    "task_permutation_p": p_value,
                }
            )
        q_values = _bh_adjust([float(row["task_permutation_p"]) for row in group])
        for row, q_value in zip(group, q_values, strict=True):
            row["bh_q_within_feature_family"] = q_value
            association_rows.append(row)
    return task_rows, association_rows


def _length_quartiles(
    pairs: Sequence[PairRow],
    *,
    bootstrap_draws: int,
) -> tuple[list[dict[str, object]], dict[int, list[PairRow]]]:
    rows = _valid_pair_rows(pairs, MAJORITY_DETECTOR)
    raw = np.asarray([row.added_chars for row in rows], dtype=float)
    residual = _within_stratum_residuals(rows, raw)
    order = np.argsort(residual, kind="mergesort")
    groups: dict[int, list[PairRow]] = {}
    output: list[dict[str, object]] = []
    for quartile_index, indices in enumerate(np.array_split(order, 4), start=1):
        selected = [rows[int(index)] for index in indices]
        groups[quartile_index] = selected
        static = np.asarray(
            [row.outcomes[MAJORITY_DETECTOR][0] for row in selected],
            dtype=float,
        )
        dynamic = np.asarray(
            [row.outcomes[MAJORITY_DETECTOR][1] for row in selected],
            dtype=float,
        )
        differences = dynamic - static
        lower, upper = _cluster_bootstrap_mean(
            selected,
            differences.tolist(),
            draws=bootstrap_draws,
            seed=20262810 + quartile_index,
        )
        selected_residual = residual[indices]
        output.append(
            {
                "relative_growth_quartile": quartile_index,
                "complete_pairs": len(selected),
                "tasks": len({row.task_id for row in selected}),
                "mean_raw_added_chars": float(
                    np.mean([row.added_chars for row in selected])
                ),
                "min_residual_added_chars": float(selected_residual.min()),
                "max_residual_added_chars": float(selected_residual.max()),
                "static_rh": int(static.sum()),
                "dynamic_rh": int(dynamic.sum()),
                "static_rate": float(static.mean()),
                "dynamic_rate": float(dynamic.mean()),
                "paired_risk_difference": float(differences.mean()),
                "cluster_bootstrap_ci_low": lower,
                "cluster_bootstrap_ci_high": upper,
            }
        )
    return output, groups


def _write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _pair_csv_rows(
    pairs: Sequence[PairRow],
    detectors: Sequence[str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pair in pairs:
        value: dict[str, object] = {
            key: item
            for key, item in vars(pair).items()
            if key != "outcomes"
        }
        for detector in detectors:
            safe_name = detector.replace("-", "_").replace(".", "_")
            static, dynamic = pair.outcomes[detector]
            value[f"static_rh_{safe_name}"] = static
            value[f"dynamic_rh_{safe_name}"] = dynamic
            value[f"paired_difference_{safe_name}"] = (
                dynamic - static
                if static is not None and dynamic is not None
                else None
            )
        rows.append(value)
    return rows


def _summary_stats(pairs: Sequence[PairRow]) -> dict[str, object]:
    output: dict[str, object] = {}
    for scope in ("pooled", "semi", "full"):
        rows = _scope_rows(pairs, scope)
        scope_stats: dict[str, object] = {"pairs": len(rows)}
        for field in (
            "baseline_chars",
            "baseline_words",
            "baseline_criteria",
            "added_chars",
            "added_words",
            "added_criteria",
            "added_penalty_capacity",
            "changed_rounds",
            "cumulative_added_chars",
            "cumulative_added_criteria",
            "criterion_exposure_fraction",
        ):
            values = np.asarray([float(getattr(row, field)) for row in rows])
            scope_stats[field] = {
                "mean": float(values.mean()),
                "sd": float(values.std(ddof=1)),
                "median": float(np.median(values)),
                "min": float(values.min()),
                "max": float(values.max()),
            }
        output[scope] = scope_stats
    return output


def _metadata_relationships(
    pairs: Sequence[PairRow],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    fields = (
        "added_chars",
        "added_words",
        "added_criteria",
        "added_penalty_capacity",
        "changed_rounds",
        "cumulative_added_chars",
        "cumulative_added_criteria",
        "criterion_exposure_fraction",
    )
    matrix = np.asarray(
        [[float(getattr(row, field)) for field in fields] for row in pairs]
    )
    correlations = np.corrcoef(matrix, rowvar=False)
    rows = [
        {
            "feature_a": field_a,
            "feature_b": field_b,
            "pearson_r": float(correlations[index_a, index_b]),
        }
        for index_a, field_a in enumerate(fields)
        for index_b, field_b in enumerate(fields)
        if index_b > index_a
    ]
    checks = {
        "changed_rounds_equal_added_criteria": all(
            row.changed_rounds == row.added_criteria for row in pairs
        ),
        "penalty_capacity_equals_ten_times_added_criteria": all(
            math.isclose(
                row.added_penalty_capacity,
                10.0 * row.added_criteria,
            )
            for row in pairs
        ),
    }
    return rows, checks


def _pyplot():
    os.environ.setdefault(
        "MPLCONFIGDIR",
        tempfile.mkdtemp(prefix="rubric-metadata-rh-mpl-"),
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _plot_results(
    output_dir: Path,
    quartiles: Sequence[dict[str, object]],
    associations: Sequence[dict[str, object]],
) -> None:
    plt = _pyplot()
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.5))

    ax = axes[0]
    positions = np.arange(1, 5, dtype=float)
    differences = np.asarray(
        [float(row["paired_risk_difference"]) for row in quartiles]
    )
    lower = np.asarray(
        [float(row["cluster_bootstrap_ci_low"]) for row in quartiles]
    )
    upper = np.asarray(
        [float(row["cluster_bootstrap_ci_high"]) for row in quartiles]
    )
    ax.errorbar(
        positions,
        differences * 100,
        yerr=np.vstack(((differences - lower) * 100, (upper - differences) * 100)),
        fmt="o-",
        color="#4477AA",
        capsize=5,
        linewidth=2,
        markersize=7,
    )
    ax.axhline(0, color="#4B5563", linewidth=1)
    ax.set_xticks(positions, ["Q1\nless", "Q2", "Q3", "Q4\nmore"])
    ax.set_xlabel("Dynamic rubric growth relative to matched replicates")
    ax.set_ylabel("Dynamic − static RH detection rate (percentage points)")
    ax.set_title("Matched outcome difference by length-growth quartile")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)

    ax = axes[1]
    selected = [
        row
        for row in associations
        if row["detector"] == MAJORITY_DETECTOR
        and row["scope"] == "pooled"
        and row["outcome"] == "paired_difference"
    ]
    selected_by_feature = {str(row["feature"]): row for row in selected}
    selected = [selected_by_feature[feature.name] for feature in FEATURES]
    y_positions = np.arange(len(selected))[::-1]
    estimates = np.asarray(
        [float(row["standardized_risk_difference"]) for row in selected]
    )
    lower = np.asarray([float(row["standardized_ci_low"]) for row in selected])
    upper = np.asarray([float(row["standardized_ci_high"]) for row in selected])
    ax.errorbar(
        estimates * 100,
        y_positions,
        xerr=np.vstack(((estimates - lower) * 100, (upper - estimates) * 100)),
        fmt="o",
        color="#CC6677",
        capsize=5,
        markersize=7,
    )
    ax.axvline(0, color="#4B5563", linewidth=1)
    ax.set_yticks(y_positions, [feature.label for feature in FEATURES])
    ax.set_xlabel("RH-rate difference per 1 within-cell SD (percentage points)")
    ax.set_title("Strict within-task metadata associations")
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)

    fig.suptitle(
        "Rubric metadata and reward-hacking detections in 360 static–dynamic pairs",
        fontsize=14,
        weight="bold",
    )
    fig.text(
        0.5,
        0.925,
        "Three-model complete-panel majority; intervals resample 30 task clusters. "
        "Associations are predictive, not causal.",
        ha="center",
        fontsize=9,
        color="#4A5568",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.89))
    for suffix in ("png", "pdf"):
        fig.savefig(
            output_dir / f"rubric_metadata_rh.{suffix}",
            dpi=220,
            bbox_inches="tight",
        )
    plt.close(fig)


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_pp(value: float) -> str:
    return f"{value * 100:+.1f} pp"


def _find_result(
    rows: Sequence[dict[str, object]],
    **matches: str,
) -> dict[str, object]:
    found = [
        row
        for row in rows
        if all(str(row.get(key)) == value for key, value in matches.items())
    ]
    if len(found) != 1:
        raise ValueError(f"expected one result for {matches}; found {len(found)}")
    return found[0]


def _write_report(
    output_dir: Path,
    *,
    summary_stats: dict[str, object],
    paired_rates: Sequence[dict[str, object]],
    associations: Sequence[dict[str, object]],
    baseline_associations: Sequence[dict[str, object]],
    metadata_correlations: Sequence[dict[str, object]],
    metadata_checks: dict[str, object],
    decision_counts: dict[str, int],
    detector_models: Sequence[str],
) -> None:
    pooled_rate = _find_result(
        paired_rates,
        detector=MAJORITY_DETECTOR,
        scope="pooled",
    )
    semi_rate = _find_result(
        paired_rates,
        detector=MAJORITY_DETECTOR,
        scope="semi",
    )
    full_rate = _find_result(
        paired_rates,
        detector=MAJORITY_DETECTOR,
        scope="full",
    )
    available_rate = _find_result(
        paired_rates,
        detector=AVAILABLE_MAJORITY_DETECTOR,
        scope="pooled",
    )
    length = _find_result(
        associations,
        detector=MAJORITY_DETECTOR,
        scope="pooled",
        outcome="paired_difference",
        feature="added_chars",
    )
    length_dynamic = _find_result(
        associations,
        detector=MAJORITY_DETECTOR,
        scope="pooled",
        outcome="dynamic_only",
        feature="added_chars",
    )
    cumulative_exposure = _find_result(
        associations,
        detector=MAJORITY_DETECTOR,
        scope="pooled",
        outcome="paired_difference",
        feature="cumulative_added_chars",
    )
    activation_timing = _find_result(
        associations,
        detector=MAJORITY_DETECTOR,
        scope="pooled",
        outcome="paired_difference",
        feature="criterion_exposure_fraction",
    )
    base_activation_timing = _find_result(
        associations,
        detector=MAJORITY_DETECTOR,
        scope="base",
        outcome="paired_difference",
        feature="criterion_exposure_fraction",
    )
    baseline_length = _find_result(
        baseline_associations,
        feature="baseline_chars",
        outcome="static_rh_rate",
    )
    pooled_stats = summary_stats["pooled"]
    assert isinstance(pooled_stats, dict)
    added_chars = pooled_stats["added_chars"]
    added_criteria = pooled_stats["added_criteria"]
    assert isinstance(added_chars, dict) and isinstance(added_criteria, dict)
    correlation_lookup = {
        (str(row["feature_a"]), str(row["feature_b"])): float(row["pearson_r"])
        for row in metadata_correlations
    }
    char_word_r = correlation_lookup["added_chars", "added_words"]
    char_criteria_r = correlation_lookup["added_chars", "added_criteria"]
    if not all(bool(value) for value in metadata_checks.values()):
        raise ValueError("expected exact legacy rubric metadata relationships")

    detector_lines = []
    detector_length_lines = []
    for model in detector_models:
        result = _find_result(paired_rates, detector=model, scope="pooled")
        detector_lines.append(
            f"- `{model}`: {int(result['complete_pairs'])} pairs; "
            f"static {_format_percent(float(result['static_rate']))}; "
            f"dynamic {_format_percent(float(result['dynamic_rate']))}; "
            f"difference {_format_pp(float(result['paired_risk_difference']))}."
        )
        length_result = _find_result(
            associations,
            detector=model,
            scope="pooled",
            outcome="paired_difference",
            feature="added_chars",
        )
        detector_length_lines.append(
            f"- `{model}`: "
            f"{_format_pp(float(length_result['risk_difference_per_unit']))} per "
            "1,000 characters; raw p="
            f"{float(length_result['within_stratum_permutation_p']):.3f}; "
            "detector-sensitivity-family q="
            f"{float(length_result['bh_q_across_detector_sensitivity_family']):.3f}."
        )

    stratified_lines = [
        "| Scope | Final length slope | Permutation p | Earlier-activation slope | Permutation p |",
        "|---|---:|---:|---:|---:|",
    ]
    for scope in ("pooled", "semi", "full", "base", "diligent"):
        scope_length = _find_result(
            associations,
            detector=MAJORITY_DETECTOR,
            scope=scope,
            outcome="paired_difference",
            feature="added_chars",
        )
        scope_timing = _find_result(
            associations,
            detector=MAJORITY_DETECTOR,
            scope=scope,
            outcome="paired_difference",
            feature="criterion_exposure_fraction",
        )
        stratified_lines.append(
            f"| {scope.title()} | "
            f"{_format_pp(float(scope_length['risk_difference_per_unit']))} per 1k chars | "
            f"{float(scope_length['within_stratum_permutation_p']):.3f} | "
            f"{_format_pp(float(scope_timing['risk_difference_per_unit']))} per round | "
            f"{float(scope_timing['within_stratum_permutation_p']):.3f} |"
        )

    decision_count_lines = [
        f"- `{key}`: {count}" for key, count in decision_counts.items()
    ]
    lines = [
        "# Rubric metadata and reward-hacking detections",
        "",
        "## Result",
        "",
        (
            "The existing runs do not show a reliable relation between dynamic "
            "rubric length and reward-hacking (RH) detection. The strict matched "
            "estimate is "
            f"{_format_pp(float(length['risk_difference_per_unit']))} per 1,000 "
            "added characters, with a 95% task-cluster bootstrap interval of "
            f"{_format_pp(float(length['cluster_bootstrap_ci_low']))} to "
            f"{_format_pp(float(length['cluster_bootstrap_ci_high']))}. The "
            "within-cell permutation p-value is "
            f"{float(length['within_stratum_permutation_p']):.3f}."
        ),
        "",
        (
            "This estimate compares the dynamic-minus-static RH outcome across "
            "replicates within the same task, feedback policy, and prompt policy. "
            "It therefore controls the requested task and prompt factors."
        ),
        "",
        "## Matched treatment comparison",
        "",
        (
            f"The complete-panel majority analysis retained "
            f"{int(pooled_rate['complete_pairs'])} of 360 pairs. Static runs had "
            f"{int(pooled_rate['static_rh'])} detections "
            f"({_format_percent(float(pooled_rate['static_rate']))}). Dynamic runs "
            f"had {int(pooled_rate['dynamic_rh'])} detections "
            f"({_format_percent(float(pooled_rate['dynamic_rate']))}). The paired "
            "difference was "
            f"{_format_pp(float(pooled_rate['paired_risk_difference']))} "
            f"(95% cluster interval "
            f"{_format_pp(float(pooled_rate['cluster_bootstrap_ci_low']))} to "
            f"{_format_pp(float(pooled_rate['cluster_bootstrap_ci_high']))}; "
            f"task-cluster sign-flip p="
            f"{float(pooled_rate['task_cluster_signflip_p']):.3f})."
        ),
        "",
        (
            "A two-available-vote sensitivity retained "
            f"{int(available_rate['complete_pairs'])} pairs and gave a difference "
            f"of {_format_pp(float(available_rate['paired_risk_difference']))}."
        ),
        "",
        (
            f"Semi feedback: {_format_pp(float(semi_rate['paired_risk_difference']))}. "
            f"Full feedback: {_format_pp(float(full_rate['paired_risk_difference']))}."
        ),
        "",
        "Detector-specific results differ:",
        "",
        *detector_lines,
        "",
        "Detector-specific length slopes also disagree:",
        "",
        *detector_length_lines,
        "",
        "## Rubric growth",
        "",
        (
            f"Dynamic rubrics added a mean of {float(added_chars['mean']):,.0f} "
            f"characters (median {float(added_chars['median']):,.0f}; range "
            f"{float(added_chars['min']):,.0f} to "
            f"{float(added_chars['max']):,.0f}). They added a mean of "
            f"{float(added_criteria['mean']):.2f} criteria (median "
            f"{float(added_criteria['median']):.0f}; range "
            f"{float(added_criteria['min']):.0f} to "
            f"{float(added_criteria['max']):.0f})."
        ),
        "",
        (
            "In a dynamic-only model, the length estimate was "
            f"{_format_pp(float(length_dynamic['risk_difference_per_unit']))} per "
            "1,000 added characters. Its 95% cluster interval was "
            f"{_format_pp(float(length_dynamic['cluster_bootstrap_ci_low']))} to "
            f"{_format_pp(float(length_dynamic['cluster_bootstrap_ci_high']))}."
        ),
        "",
        (
            "Cumulative exposure gave "
            f"{_format_pp(float(cumulative_exposure['risk_difference_per_unit']))} "
            "per 10,000 added character-rounds. Moving the average criterion "
            "activation one round earlier gave "
            f"{_format_pp(float(activation_timing['risk_difference_per_unit']))}. "
            "Their permutation p-values were "
            f"{float(cumulative_exposure['within_stratum_permutation_p']):.3f} "
            f"and {float(activation_timing['within_stratum_permutation_p']):.3f}."
        ),
        "",
        (
            "The strongest exploratory subgroup was earlier activation under the "
            "base prompt: "
            f"{_format_pp(float(base_activation_timing['risk_difference_per_unit']))} "
            "per round (raw p="
            f"{float(base_activation_timing['within_stratum_permutation_p']):.3f}; "
            "Benjamini-Hochberg q across all scope-feature checks="
            f"{float(base_activation_timing['bh_q_across_majority_scope_feature_family']):.3f})."
        ),
        "",
        "The prompt- and feedback-stratified slopes are:",
        "",
        *stratified_lines,
        "",
        (
            "Across the 30 task rubrics, baseline character count had Spearman "
            f"rho={float(baseline_length['spearman_rho']):+.2f} with static-run RH "
            f"rate (permutation p={float(baseline_length['task_permutation_p']):.3f}). "
            "This task-level comparison is confounded by task content and difficulty."
        ),
        "",
        "Most final-rubric features do not identify separate mechanisms. "
        f"Added characters correlate {char_word_r:.3f} with added words and "
        f"{char_criteria_r:.3f} with added criteria. Every changed round added "
        "one criterion. Every criterion added exactly 10 possible penalty points. "
        "The criterion-count, update-count, and penalty-capacity effects are "
        "therefore mathematically identical in these runs. Cumulative exposure "
        "and activation timing add a distinct longitudinal dimension.",
        "",
        "## Interpretation limits",
        "",
        "- Rubric growth is post-treatment. Earlier solver behavior caused the proposer to add criteria. The analysis cannot identify a causal effect of length.",
        "- The detector reviewed the same trajectory that caused rubric growth. More rubric surface can also change what the detector can observe.",
        "- RH is a model-judge label. It is not verified ground truth. Detector-specific estimates are therefore necessary.",
        "- Character count, word count, criterion count, penalty capacity, and changed rounds are strongly related. The data cannot isolate one mechanism.",
        "- Only three replicates exist in each task-feedback-prompt cell. Estimates can miss small or nonlinear effects.",
        "",
        "## Method",
        "",
        "Each pair shares the experiment, task, replicate seed, prompt policy, and initial rubric text. The pair differs in static versus prospective rubric policy. The main outcome is the final three-model complete-panel majority RH decision. A two-available-vote majority is a missing-panel sensitivity check.",
        "",
        "The metadata model demeans outcomes and rubric features within each task-feedback-prompt cell. It estimates a linear risk-difference slope from replicate variation. Confidence intervals resample the 30 tasks. Permutation tests shuffle metadata across replicates within each cell. Benjamini-Hochberg q-values cover four metadata features within each scope. A second correction covers every majority scope-feature check.",
        "",
        "A panel is missing from the majority analysis if any model lacks a substantive RH decision. Raw decision counts follow:",
        "",
        *decision_count_lines,
        "",
        "## Files",
        "",
        "- `matched_pairs.csv`: pair identities, rubric metadata, and detector outcomes.",
        "- `paired_rh_rates.csv`: matched rates and discordant-pair tests.",
        "- `feature_associations.csv`: strict within-cell metadata models.",
        "- `baseline_task_associations.csv`: task-level baseline-rubric correlations.",
        "- `metadata_correlations.csv`: dependence among the rubric features.",
        "- `length_growth_quartiles.csv`: descriptive matched differences by relative growth quartile.",
        "- `rubric_metadata_rh.png` and `.pdf`: the main visualization.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for tables, report, and figures.",
    )
    parser.add_argument(
        "--bootstrap-draws",
        type=int,
        default=5_000,
        help="Number of task-cluster bootstrap draws.",
    )
    parser.add_argument(
        "--permutation-draws",
        type=int,
        default=10_000,
        help="Number of within-cell permutation draws.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.bootstrap_draws < 100 or args.permutation_draws < 100:
        raise ValueError("use at least 100 bootstrap and permutation draws")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs, detector_models, decision_counts = _build_pairs()
    detectors = [
        MAJORITY_DETECTOR,
        AVAILABLE_MAJORITY_DETECTOR,
        *detector_models,
    ]
    paired_rates = _paired_rates(
        pairs,
        detectors,
        bootstrap_draws=args.bootstrap_draws,
        permutation_draws=args.permutation_draws,
    )
    associations = _feature_associations(
        pairs,
        detectors,
        bootstrap_draws=args.bootstrap_draws,
        permutation_draws=args.permutation_draws,
    )
    task_rows, baseline_associations = _baseline_task_associations(
        pairs,
        bootstrap_draws=args.bootstrap_draws,
        permutation_draws=args.permutation_draws,
    )
    quartiles, _quartile_groups = _length_quartiles(
        pairs,
        bootstrap_draws=args.bootstrap_draws,
    )
    summary_stats = _summary_stats(pairs)
    metadata_correlations, metadata_checks = _metadata_relationships(pairs)

    _write_csv(output_dir / "matched_pairs.csv", _pair_csv_rows(pairs, detectors))
    _write_csv(output_dir / "paired_rh_rates.csv", paired_rates)
    _write_csv(output_dir / "feature_associations.csv", associations)
    _write_csv(output_dir / "baseline_tasks.csv", task_rows)
    _write_csv(
        output_dir / "baseline_task_associations.csv",
        baseline_associations,
    )
    _write_csv(output_dir / "metadata_correlations.csv", metadata_correlations)
    _write_csv(output_dir / "length_growth_quartiles.csv", quartiles)
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "studies": [spec.experiment_id for spec in STUDIES],
                "pair_count": len(pairs),
                "detectors": detectors,
                "decision_counts": decision_counts,
                "rubric_metadata": summary_stats,
                "metadata_relationship_checks": metadata_checks,
                "bootstrap_draws": args.bootstrap_draws,
                "permutation_draws": args.permutation_draws,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _plot_results(output_dir, quartiles, associations)
    _write_report(
        output_dir,
        summary_stats=summary_stats,
        paired_rates=paired_rates,
        associations=associations,
        baseline_associations=baseline_associations,
        metadata_correlations=metadata_correlations,
        metadata_checks=metadata_checks,
        decision_counts=decision_counts,
        detector_models=detector_models,
    )

    pooled = _find_result(
        paired_rates,
        detector=MAJORITY_DETECTOR,
        scope="pooled",
    )
    length = _find_result(
        associations,
        detector=MAJORITY_DETECTOR,
        scope="pooled",
        outcome="paired_difference",
        feature="added_chars",
    )
    print(f"Validated {len(pairs)} matched static-dynamic pairs.")
    print(
        f"Complete majority pairs: {pooled['complete_pairs']}; "
        f"paired RH difference: {_format_pp(float(pooled['paired_risk_difference']))}."
    )
    print(
        "Length association per 1,000 added characters: "
        f"{_format_pp(float(length['risk_difference_per_unit']))} "
        f"(95% CI {_format_pp(float(length['cluster_bootstrap_ci_low']))} to "
        f"{_format_pp(float(length['cluster_bootstrap_ci_high']))}; "
        f"permutation p={float(length['within_stratum_permutation_p']):.3f})."
    )
    print(f"Wrote analysis to {output_dir}")


if __name__ == "__main__":
    main()
