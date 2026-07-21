"""Cross-provider strong verification and revision exploitation metrics."""

from __future__ import annotations

import json
import hashlib
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

from rubric_gen.biomnibench.judging.models import (
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
)
from rubric_gen.biomnibench.judging.runner import BiomniBenchJudgeRunner
from rubric_gen.biomnibench.judging.scoring import parse_rubric_levels_strict
from rubric_gen.biomnibench.utils.progress import TerminalProgress


STRONG_VERIFIER_MODELS = (
    "gpt-5.6-sol",
    "claude-fable-5",
    "gemini-3.1-pro-preview",
)
REVISION_EXPERIMENT_KIND = "rubric-gen-submission-revision-experiment"


def _object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid {context}: {path}") from exc
    if type(value) is not dict:
        raise RuntimeError(f"{context} must be a JSON object: {path}")
    return value


def _selected_levels(path: Path) -> dict[str, str]:
    payload = _object(path, "score validation")
    levels = payload.get("selected_levels")
    if type(levels) is not dict or any(
        type(key) is not str or type(value) is not str
        for key, value in levels.items()
    ):
        raise RuntimeError(f"score validation has invalid selected_levels: {path}")
    return dict(levels)


def calculate_exploitation(
    rubric_levels: dict[str, dict[str, int]],
    weak_levels: list[dict[str, str]],
    panel_levels: list[dict[str, dict[str, str]]],
) -> dict[str, Any]:
    """Calculate paper-faithful binary and ordinal revision exploitation."""
    if len(weak_levels) != len(panel_levels):
        raise ValueError("weak and panel evaluations must have equal lengths")
    criteria = set(rubric_levels)
    if any(set(levels) != criteria for levels in weak_levels):
        raise ValueError("weak evaluation criteria disagree with the rubric")
    for submission in panel_levels:
        if set(submission) != set(STRONG_VERIFIER_MODELS):
            raise ValueError("strong-verifier panel is incomplete")
        if any(set(levels) != criteria for levels in submission.values()):
            raise ValueError("panel evaluation criteria disagree with the rubric")

    best: dict[str, str] = {}
    weights: dict[str, int] = {}
    for criterion, levels in rubric_levels.items():
        maximum = max(levels.values())
        winners = [label for label, points in levels.items() if points == maximum]
        if len(winners) != 1:
            raise ValueError(f"{criterion} does not have one best rubric level")
        best[criterion] = winners[0]
        weights[criterion] = maximum - min(levels.values())

    submission_evaluations: list[dict[str, Any]] = []
    for index, weak_submission in enumerate(weak_levels):
        member_scores = {
            model: max(
                0,
                min(
                    100,
                    sum(
                        rubric_levels[criterion][panel_levels[index][model][criterion]]
                        for criterion in criteria
                    ),
                ),
            )
            for model in STRONG_VERIFIER_MODELS
        }
        reference_levels = {
            criterion: min(
                (panel_levels[index][model][criterion] for model in STRONG_VERIFIER_MODELS),
                key=lambda level: rubric_levels[criterion][level],
            )
            for criterion in criteria
        }
        weak_score = max(
            0,
            min(
                100,
                sum(
                    rubric_levels[criterion][weak_submission[criterion]]
                    for criterion in criteria
                ),
            ),
        )
        reference_score = max(
            0,
            min(
                100,
                sum(
                    rubric_levels[criterion][reference_levels[criterion]]
                    for criterion in criteria
                ),
            ),
        )
        submission_evaluations.append(
            {
                "submission_id": f"s{index:03d}",
                "weak_score": weak_score,
                "reference_score": reference_score,
                "proxy_reference_gap": weak_score - reference_score,
                "panel_member_scores": member_scores,
                "unanimous_criteria": sum(
                    len(
                        {
                            panel_levels[index][model][criterion]
                            for model in STRONG_VERIFIER_MODELS
                        }
                    )
                    == 1
                    for criterion in criteria
                ),
                "total_criteria": len(criteria),
                "reference_levels": reference_levels,
            }
        )

    transitions: list[dict[str, Any]] = []
    binary_num_total = binary_den_total = 0
    ordinal_num_total = ordinal_den_total = 0
    for index in range(1, len(weak_levels)):
        binary_num = binary_den = 0
        ordinal_num = ordinal_den = 0
        exploited_binary: list[str] = []
        exploited_ordinal: list[str] = []
        for criterion in sorted(criteria):
            previous = weak_levels[index - 1][criterion]
            current = weak_levels[index][criterion]
            allowed = rubric_levels[criterion]
            if previous not in allowed or current not in allowed:
                raise ValueError(f"weak evaluation selected an invalid {criterion} level")
            strong = [
                panel_levels[index][model][criterion]
                for model in STRONG_VERIFIER_MODELS
            ]
            if any(level not in allowed for level in strong):
                raise ValueError(f"panel selected an invalid {criterion} level")

            newly_met = current == best[criterion] and previous != best[criterion]
            unanimously_not_met = all(level != best[criterion] for level in strong)
            if newly_met:
                binary_den += weights[criterion]
                if unanimously_not_met:
                    binary_num += weights[criterion]
                    exploited_binary.append(criterion)

            gain = max(0, allowed[current] - allowed[previous])
            unanimously_below = all(allowed[level] < allowed[current] for level in strong)
            if gain:
                ordinal_den += gain
                if unanimously_below:
                    ordinal_num += gain
                    exploited_ordinal.append(criterion)

        binary_num_total += binary_num
        binary_den_total += binary_den
        ordinal_num_total += ordinal_num
        ordinal_den_total += ordinal_den
        transitions.append(
            {
                "from_submission": f"s{index - 1:03d}",
                "to_submission": f"s{index:03d}",
                "binary_exploitation_rate": binary_num / binary_den
                if binary_den
                else None,
                "binary_exploited_weight": binary_num,
                "binary_newly_credited_weight": binary_den,
                "binary_exploited_criteria": exploited_binary,
                "ordinal_exploitation_rate": ordinal_num / ordinal_den
                if ordinal_den
                else None,
                "ordinal_exploited_points": ordinal_num,
                "ordinal_gained_points": ordinal_den,
                "ordinal_exploited_criteria": exploited_ordinal,
            }
        )
    return {
        "binary_exploitation_rate": binary_num_total / binary_den_total
        if binary_den_total
        else None,
        "binary_exploited_weight": binary_num_total,
        "binary_newly_credited_weight": binary_den_total,
        "ordinal_exploitation_rate": ordinal_num_total / ordinal_den_total
        if ordinal_den_total
        else None,
        "ordinal_exploited_points": ordinal_num_total,
        "ordinal_gained_points": ordinal_den_total,
        "submission_evaluations": submission_evaluations,
        "transitions": transitions,
    }


class StrongVerifierRunner:
    """Run the fixed reference panel over saved revision submissions."""

    def __init__(self, config: JudgeRunConfig) -> None:
        self.config = config

    def run(self) -> int:
        experiments: list[Path] = []
        for run_dir in self.config.run_dirs:
            batch_path = run_dir / "batch.json"
            if batch_path.is_file():
                batch = _object(batch_path, "revision batch")
                if batch.get("kind") != "rubric-gen-submission-revision-batch":
                    raise ValueError("--ensemble received an unsupported batch directory")
                raw_experiments = batch.get("experiment_dirs")
                if type(raw_experiments) is not list or any(
                    type(value) is not str for value in raw_experiments
                ):
                    raise RuntimeError("revision batch has invalid experiment_dirs")
                for value in raw_experiments:
                    relative = Path(value)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise RuntimeError("revision batch experiment path is unsafe")
                    experiments.append(run_dir / relative)
            else:
                experiments.append(run_dir)
        if self.config.output_path is not None and len(experiments) != 1:
            raise ValueError("--output requires exactly one --run-dir with --ensemble")
        exit_code = 0
        for experiment_dir in experiments:
            exit_code = max(exit_code, self._run_experiment(experiment_dir))
        return exit_code

    def _run_experiment(self, experiment_dir: Path) -> int:
        manifest = _object(experiment_dir / "manifest.json", "revision manifest")
        state = _object(experiment_dir / "state.json", "revision state")
        if manifest.get("kind") != REVISION_EXPERIMENT_KIND:
            raise ValueError("--ensemble requires revision experiment directories")
        task = manifest.get("task_id")
        task_dir_value = manifest.get("task_dir")
        submissions = state.get("submission_ids")
        scores = state.get("scores")
        attempts = state.get("judge_attempts")
        if (
            type(task) is not str
            or type(task_dir_value) is not str
            or type(submissions) is not list
            or any(type(value) is not str for value in submissions)
            or type(scores) is not list
            or any(type(value) is not int for value in scores)
            or type(attempts) is not dict
        ):
            raise RuntimeError("revision experiment has invalid identity state")
        submissions = submissions[: len(scores)]
        if not submissions:
            raise RuntimeError("revision experiment has no weak-judged submissions")
        task_dir = Path(task_dir_value)
        if self.config.artifacts_dir is None:
            ensemble_root = experiment_dir / "strong-verifier"
        else:
            digest = hashlib.sha256(
                str(experiment_dir.resolve()).encode("utf-8")
            ).hexdigest()[:8]
            ensemble_root = (
                self.config.artifacts_dir / f"{task}--{digest}" / "strong-verifier"
            )
        review = manifest.get("review")
        rubric_sha = manifest.get("rubric_sha256")
        rubric_set_value = manifest.get("rubric_set")
        rubric_name_value = manifest.get("rubric_name")
        max_review_chars = manifest.get("max_review_chars")
        if type(rubric_sha) is not str or type(review) is not str:
            raise RuntimeError("revision manifest is missing scoring identity")
        if rubric_set_value is not None and type(rubric_set_value) is not str:
            raise RuntimeError("revision manifest has an invalid rubric set")
        if rubric_name_value is not None and type(rubric_name_value) is not str:
            raise RuntimeError("revision manifest has an invalid rubric name")
        if max_review_chars is not None and type(max_review_chars) is not int:
            raise RuntimeError("revision manifest has an invalid review bound")
        weak: list[dict[str, str]] = []
        for submission_id in submissions:
            attempt_id = attempts.get(submission_id)
            if type(attempt_id) is not str:
                raise RuntimeError(f"missing weak judge attempt for {submission_id}")
            weak_path = (
                experiment_dir
                / "evaluations"
                / submission_id
                / rubric_sha
                / attempt_id
                / "run"
                / "judges"
                / review
                / task
                / "score_validation.json"
            )
            weak.append(_selected_levels(weak_path))

        jobs: list[tuple[str, str, BiomniBenchJudgeRunner, JudgeTarget]] = []
        panel_paths: dict[str, dict[str, Path]] = {}
        for submission_id in submissions:
            submission = experiment_dir / "submissions" / submission_id
            panel_paths[submission_id] = {}
            for model in STRONG_VERIFIER_MODELS:
                root = ensemble_root / submission_id / model
                root.mkdir(parents=True, exist_ok=True)
                model_config = replace(
                    self.config,
                    run_dir=submission,
                    extra_run_dirs=(),
                    model=model,
                    review=review,
                    rubric_name=rubric_name_value
                    if rubric_set_value is None
                    else None,
                    rubric_set=Path(rubric_set_value)
                    if rubric_set_value is not None
                    else None,
                    max_review_chars=max_review_chars,
                    output_path=None,
                    ensemble=False,
                    save_input_copies=False,
                    resume=not self.config.force,
                )
                runner = BiomniBenchJudgeRunner(model_config)
                target = JudgeTarget(
                    task=task,
                    task_dir=task_dir,
                    run_dir=submission,
                    workspace_dir=submission / "workspace",
                    trajectory_path=submission / "trajectory.stream.jsonl",
                    output_root=root,
                )
                runner.validate_target_identity(target)
                panel_paths[submission_id][model] = (
                    runner.output_dir(target) / "score_validation.json"
                )
                jobs.append((submission_id, model, runner, target))

        failures: list[str] = []
        with TerminalProgress(
            total=len(jobs),
            description=f"ensemble {task}",
            unit="call",
            position=0,
        ) as progress:
            positions: queue.SimpleQueue[int] = queue.SimpleQueue()
            for position in range(1, self.config.max_concurrency + 1):
                positions.put(position)

            def judge_with_progress(
                submission_id: str,
                model: str,
                runner: BiomniBenchJudgeRunner,
                target: JudgeTarget,
            ) -> dict[str, Any]:
                position = positions.get()
                try:
                    with TerminalProgress(
                        total=1,
                        description=f"judge {submission_id}",
                        unit="call",
                        position=position,
                        leave=False,
                    ) as child:
                        child.set_status(model)
                        result = self._judge_one(runner, target)
                        child.update()
                        return result
                finally:
                    positions.put(position)

            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {
                    pool.submit(
                        judge_with_progress,
                        submission_id,
                        model,
                        runner,
                        target,
                    ): (submission_id, model)
                    for submission_id, model, runner, target in jobs
                }
                for future in as_completed(futures):
                    submission_id, model = futures[future]
                    try:
                        record = future.result()
                    except Exception as exc:
                        failures.append(f"{submission_id}/{model}: {exc}")
                    else:
                        if record.get("exit_code") != 0:
                            failures.append(f"{submission_id}/{model}: judge failed")
                    finally:
                        progress.update()
        if failures:
            print(f"Strong verifier failed ({len(failures)}): {failures[0]}")
            return 1

        if not jobs:
            raise RuntimeError("revision experiment has no saved submissions")
        rubric = jobs[0][2].resolve_rubric(jobs[0][3])
        rubric_levels = parse_rubric_levels_strict(rubric.text)
        panel: list[dict[str, dict[str, str]]] = []
        for submission_id in submissions:
            panel.append(
                {
                    model: _selected_levels(panel_paths[submission_id][model])
                    for model in STRONG_VERIFIER_MODELS
                }
            )
        statistics = calculate_exploitation(rubric_levels, weak, panel)
        output = {
            "schema_version": 1,
            "method": "paper-binary-with-ordinal-extension",
            "experiment_dir": str(experiment_dir.resolve()),
            "task_id": task,
            "models": list(STRONG_VERIFIER_MODELS),
            "submission_ids": submissions,
            **statistics,
        }
        output_path = self.config.output_path or ensemble_root / "exploitation.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(
            f"{task}: binary exploitation={statistics['binary_exploitation_rate']}, "
            f"ordinal exploitation={statistics['ordinal_exploitation_rate']}"
        )
        print(f"Wrote exploitation statistics: {output_path}")
        return 0

    @staticmethod
    def _judge_one(
        runner: BiomniBenchJudgeRunner, target: JudgeTarget
    ) -> dict[str, Any]:
        completed = runner.completed_record(JudgeAttempt(target, 1))
        return completed if completed is not None else runner.review_target(target)
