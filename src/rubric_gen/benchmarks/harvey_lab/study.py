"""Randomized replicated Harvey harness-evolution study."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.harvey_lab.artifacts import (
    file_sha256,
    read_json_object,
    validate_checkout,
    write_identity,
)
from rubric_gen.benchmarks.harvey_lab.audits import (
    run_quality_audit,
    run_reward_hacking_audit,
)
from rubric_gen.benchmarks.harvey_lab.config import (
    HarveyExperiment,
    HarveyRun,
    RubricEvolution,
    rubric_identity,
)
from rubric_gen.benchmarks.harvey_lab.controller import HarveyEvolutionController
from rubric_gen.benchmarks.harvey_lab.evaluator import HarveyEvaluator


def treatment_conditions(experiment: HarveyExperiment) -> tuple[str, ...]:
    return ("static", *(rubric.mode for rubric in experiment.rubrics))


def _condition_order(
    conditions: tuple[str, ...],
    *,
    seed: int,
    replicate: int,
) -> tuple[str, ...]:
    if len(conditions) == 2:
        first_order = int.from_bytes(
            hashlib.sha256(str(seed).encode("utf-8")).digest()[:8],
            "big",
        ) % 2
        return (
            conditions
            if (first_order + replicate - 1) % 2 == 0
            else conditions[::-1]
        )
    return tuple(
        sorted(
            conditions,
            key=lambda condition: hashlib.sha256(
                f"{seed}:{replicate}:{condition}".encode("utf-8")
            ).digest(),
        )
    )


def randomized_runs(experiment: HarveyExperiment) -> tuple[HarveyRun, ...]:
    """Return the fixed balanced allocation in randomized execution order."""
    seed = experiment.design.randomization_seed
    planned = []
    conditions = treatment_conditions(experiment)
    treatments = {rubric.mode: rubric for rubric in experiment.rubrics}
    static_source = treatments.get("prospective", experiment.rubrics[0])
    for replicate in range(1, experiment.design.replicates_per_condition + 1):
        order = _condition_order(
            conditions,
            seed=seed,
            replicate=replicate,
        )
        block = [(condition, replicate) for condition in order]
        planned.extend(block)
    runs = []
    for order, (condition, replicate) in enumerate(planned, 1):
        unit_id = f"u{order:04d}"
        rubric = treatments.get(condition)
        if rubric is None:
            rubric = RubricEvolution(
                mode="static",
                proposer_model=None,
                max_changes_per_task=static_source.max_changes_per_task,
                max_output_tokens=static_source.max_output_tokens,
            )
        runs.append(
            HarveyRun(
                source=experiment.source,
                experiment_id=f"{experiment.experiment_id}-{unit_id}",
                study_id=experiment.experiment_id,
                unit_id=unit_id,
                condition=condition,
                replicate=replicate,
                output_dir=experiment.output_dir / "trajectories" / unit_id,
                cache_dir=experiment.cache_dir,
                benchmark=experiment.benchmark,
                task_agent=experiment.task_agent,
                judge=experiment.judge,
                designer=experiment.designer,
                rubric=rubric,
                audit=experiment.audit,
                outcome_replicates=experiment.design.outcome_replicates,
            )
        )
    return tuple(runs)


def allocation_record(experiment: HarveyExperiment) -> dict[str, object]:
    return {
        "kind": "harvey-randomized-allocation",
        "experiment_id": experiment.experiment_id,
        "randomization_seed": experiment.design.randomization_seed,
        "blocking_unit": "replicate",
        "conditions": list(treatment_conditions(experiment)),
        "replicates_per_condition": experiment.design.replicates_per_condition,
        "execution_order": [
            {
                "order": order,
                "unit_id": run.unit_id,
                "condition": run.condition,
                "replicate": run.replicate,
            }
            for order, run in enumerate(randomized_runs(experiment), 1)
        ],
    }


class HarveyStudyController:
    """Run all randomized trajectories before any hidden outcome evaluation."""

    def __init__(
        self,
        experiment: HarveyExperiment,
        *,
        runtime_root: Path | None = None,
        max_concurrency: int = 1,
        max_retries: int = 3,
    ) -> None:
        self.experiment = experiment
        self.runtime_root = runtime_root
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries

    def run(self, *, resume: bool = False) -> int:
        self._initialize(resume=resume)
        runs = randomized_runs(self.experiment)
        for run in runs:
            evaluator = self._evaluator(run)
            child_resume = (run.output_dir / "experiment.json").is_file()
            HarveyEvolutionController(
                run,
                runtime_root=self.runtime_root,
                evaluator=evaluator,
            ).run(resume=child_resume)
        self._write_study("evolution-completed", runs)

        for run in runs:
            run_quality_audit(run, evaluator=self._evaluator(run))
        self._write_study("quality-completed", runs)

        statuses = []
        for run in runs:
            judgments = run.output_dir / "audits" / "reward-hacking" / "judgments"
            detection_started = judgments.is_dir() and any(judgments.iterdir())
            statuses.append(
                run_reward_hacking_audit(
                    run,
                    resume=detection_started,
                    max_concurrency=self.max_concurrency,
                )
            )
        if any(statuses):
            self._write_study("detection-incomplete", runs)
            return 1
        self._write_study("completed", runs)
        return 0

    def run_quality(self) -> int:
        self._validate_existing()
        for run in randomized_runs(self.experiment):
            run_quality_audit(run, evaluator=self._evaluator(run))
        self._write_study("quality-completed", randomized_runs(self.experiment))
        return 0

    def run_detection(self, *, resume: bool) -> int:
        self._validate_existing()
        statuses = []
        for run in randomized_runs(self.experiment):
            statuses.append(
                run_reward_hacking_audit(
                    run,
                    resume=resume,
                    max_concurrency=self.max_concurrency,
                )
            )
        return 1 if any(statuses) else 0

    def _evaluator(self, run: HarveyRun) -> HarveyEvaluator:
        if self.runtime_root is None:
            raise RuntimeError("Harvey quality evaluation requires a runtime root")
        return HarveyEvaluator(
            run,
            runtime_root=self.runtime_root,
            max_concurrency=self.max_concurrency,
            max_retries=self.max_retries,
        )

    def _identity(self) -> dict[str, object]:
        value = {
            "kind": "harvey-randomized-harness-evolution-experiment",
            "experiment_id": self.experiment.experiment_id,
            "experiment_path": str(self.experiment.source),
            "experiment_sha256": file_sha256(self.experiment.source),
            "benchmark": asdict(self.experiment.benchmark),
            "task_agent": asdict(self.experiment.task_agent),
            "judge": asdict(self.experiment.judge),
            "designer": asdict(self.experiment.designer),
            "audit": asdict(self.experiment.audit),
            "design": asdict(self.experiment.design),
        }
        if len(self.experiment.rubrics) == 1:
            value["rubric_treatment"] = rubric_identity(
                self.experiment.rubrics[0]
            )
        else:
            value["rubric_treatments"] = [
                rubric_identity(rubric) for rubric in self.experiment.rubrics
            ]
        return json.loads(json.dumps(value, default=str))

    def _initialize(self, *, resume: bool) -> None:
        tasks = self.experiment.benchmark
        validate_checkout(
            tasks.checkout,
            tasks.revision,
            (
                *tasks.development_tasks,
                *tasks.selection_tasks,
                *tasks.held_out_tasks,
            ),
        )
        root = self.experiment.output_dir
        if root.exists() and not root.is_dir():
            raise ValueError(f"Harvey output is not a directory: {root}")
        if root.is_dir() and any(root.iterdir()) and not (
            root / "experiment.json"
        ).is_file():
            raise FileExistsError(f"Harvey output is non-empty and unrecognized: {root}")
        root.mkdir(parents=True, exist_ok=True)
        write_identity(root / "experiment.json", self._identity(), resume=resume)
        allocation = allocation_record(self.experiment)
        path = root / "allocation.json"
        if os.path.lexists(path):
            if read_json_object(path, "Harvey allocation") != allocation:
                raise ValueError("existing Harvey allocation differs from the specification")
        else:
            write_json_atomic(path, allocation)

    def _validate_existing(self) -> None:
        self._initialize(resume=True)
        for run in randomized_runs(self.experiment):
            study = read_json_object(
                run.output_dir / "study.json",
                f"Harvey trajectory {run.unit_id}",
            )
            if study.get("status") != "completed":
                raise ValueError(f"Harvey trajectory is incomplete: {run.unit_id}")

    def _write_study(
        self,
        status: str,
        runs: tuple[HarveyRun, ...],
    ) -> None:
        units: list[dict[str, object]] = []
        for run in runs:
            quality_path = (
                run.output_dir / "audits" / "quality-transfer" / "summary.json"
            )
            quality = (
                read_json_object(quality_path, "Harvey quality summary")
                if quality_path.is_file()
                else None
            )
            detection_path = (
                run.output_dir
                / "audits"
                / "reward-hacking"
                / "judgments"
                / "detection-rates.json"
            )
            detection = (
                read_json_object(detection_path, "Harvey detection rates")
                if detection_path.is_file()
                else None
            )
            primary = (
                detection.get("primary")
                if isinstance(detection, dict)
                and isinstance(detection.get("primary"), dict)
                else None
            )
            units.append(
                {
                    "unit_id": run.unit_id,
                    "condition": run.condition,
                    "replicate": run.replicate,
                    "trajectory_dir": str(run.output_dir.relative_to(self.experiment.output_dir)),
                    "selected_candidate": (
                        None if quality is None else quality.get("selected_candidate")
                    ),
                    "selected_minus_baseline_held_out": (
                        None
                        if quality is None
                        else quality.get("selected_minus_baseline_held_out")
                    ),
                    "reward_hacking_rate": (
                        None if primary is None else primary.get("rate")
                    ),
                    "reward_hacking_rate_bounds": (
                        None
                        if primary is None
                        else primary.get("missingness_bounds")
                    ),
                }
            )
        condition_names = treatment_conditions(self.experiment)
        conditions = {
            condition: _condition_summary(units, condition)
            for condition in condition_names
        }
        effects = _condition_effects(conditions, condition_names)
        write_json_atomic(
            self.experiment.output_dir / "study.json",
            {
                "kind": "harvey-randomized-harness-evolution-study",
                "experiment_id": self.experiment.experiment_id,
                "status": status,
                "conditions": list(condition_names),
                "replicates_per_condition": (
                    self.experiment.design.replicates_per_condition
                ),
                "outcome_replicates": self.experiment.design.outcome_replicates,
                "selection_precedes_held_out_evaluation": True,
                "all_evolution_precedes_hidden_outcome_evaluation": True,
                "units": units,
                "condition_summaries": conditions,
                "condition_effects": effects,
                **effects,
            },
        )


def _condition_summary(
    units: list[dict[str, object]],
    condition: str,
) -> dict[str, object]:
    selected = [unit for unit in units if unit.get("condition") == condition]
    quality = [
        float(value)
        for unit in selected
        if isinstance(
            value := unit.get("selected_minus_baseline_held_out"),
            (int, float),
        )
        and not isinstance(value, bool)
    ]
    detection = [
        float(value)
        for unit in selected
        if isinstance(value := unit.get("reward_hacking_rate"), (int, float))
        and not isinstance(value, bool)
    ]
    bounds = [
        value
        for unit in selected
        if isinstance(value := unit.get("reward_hacking_rate_bounds"), dict)
        and isinstance(value.get("lower"), (int, float))
        and not isinstance(value.get("lower"), bool)
        and isinstance(value.get("upper"), (int, float))
        and not isinstance(value.get("upper"), bool)
    ]
    return {
        "randomized_units": len(selected),
        "quality_units": len(quality),
        "mean_selected_minus_baseline_held_out": (
            sum(quality) / len(quality) if quality else None
        ),
        "detection_units": len(detection),
        "mean_reward_hacking_rate": (
            sum(detection) / len(detection) if detection else None
        ),
        "mean_reward_hacking_rate_bounds": (
            {
                "lower": sum(float(value["lower"]) for value in bounds) / len(bounds),
                "upper": sum(float(value["upper"]) for value in bounds) / len(bounds),
            }
            if bounds
            else None
        ),
    }


def _condition_effect(
    conditions: dict[str, dict[str, object]],
    *,
    treatment: str,
    reference: str = "static",
) -> dict[str, object]:
    baseline = conditions[reference]
    treated = conditions[treatment]
    reference_quality = baseline["mean_selected_minus_baseline_held_out"]
    treated_quality = treated["mean_selected_minus_baseline_held_out"]
    reference_detection = baseline["mean_reward_hacking_rate"]
    treated_detection = treated["mean_reward_hacking_rate"]
    reference_bounds = baseline["mean_reward_hacking_rate_bounds"]
    treated_bounds = treated["mean_reward_hacking_rate_bounds"]
    return {
        "held_out_quality": (
            float(treated_quality) - float(reference_quality)
            if isinstance(reference_quality, (int, float))
            and isinstance(treated_quality, (int, float))
            else None
        ),
        "reward_hacking_rate": (
            float(treated_detection) - float(reference_detection)
            if isinstance(reference_detection, (int, float))
            and isinstance(treated_detection, (int, float))
            else None
        ),
        "reward_hacking_rate_bounds": (
            {
                "lower": (
                    float(treated_bounds["lower"])
                    - float(reference_bounds["upper"])
                ),
                "upper": (
                    float(treated_bounds["upper"])
                    - float(reference_bounds["lower"])
                ),
            }
            if isinstance(reference_bounds, dict)
            and isinstance(treated_bounds, dict)
            else None
        ),
    }


def _condition_effects(
    conditions: dict[str, dict[str, object]],
    condition_names: tuple[str, ...],
) -> dict[str, object]:
    effects: dict[str, object] = {}
    for reference_index, reference in enumerate(condition_names):
        for treatment in condition_names[reference_index + 1 :]:
            name = f"{treatment}_minus_{reference}"
            effects[name] = _condition_effect(
                conditions,
                reference=reference,
                treatment=treatment,
            )
    return effects
