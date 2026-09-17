"""Provider-free checks for execution truthfulness and RTT-adapted dropout."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.artifacts import revision_manifest_keys
from rubric_gen.submission_revision.execution_verified_proactive_prompts import (
    PROMPT_VERSION as PROACTIVE_VERSION,
    SOLVER_EXECUTION_TRUTHFULNESS,
)
from rubric_gen.submission_revision.execution_verified_provenance_prompts import (
    ENFORCEMENT_V2 as PROVENANCE_ENFORCEMENT,
    PROMPT_VERSION as PROVENANCE_VERSION,
    SOLVER_EXECUTION_TRUTHFULNESS as PROVENANCE_TRUTHFULNESS,
)
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    render_revision_prompt,
)
from rubric_gen.submission_revision.rubric_dropout import (
    DropoutProjectedFeedback,
    EXECUTION_VERIFIED_VERSION,
    revision_dropout,
    validate_dropout_rate,
)
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    ElicitedCriterion,
    RubricGeneration,
    render_augmented_rubric,
)
from rubric_gen.submission_revision.task_required_enforced_schema import (
    EnforcementContract,
    enforcement_schema,
)
from rubric_gen.submission_revision.task_required_enforcement import (
    _execution_delta,
    execution_verified_witness,
    select_execution_verified,
)
from rubric_gen.submission_revision.task_paraphrase_required import (
    INTERNAL_STAGE_FANOUT,
    _trace_stage_executor,
)
from rubric_gen.submission_revision.trace_defense_delivery import (
    append_reminder,
    execution_issue_block,
)
from rubric_gen.submission_revision.trace_defense_evidence_v2 import PublicDocument
from rubric_gen.submission_revision.trace_defense_registry import (
    SOURCE_SCHEDULE,
    prompt_hashes,
)
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.task_paraphrase_required_stage import TraceStagesV2
from rubric_gen.benchmarks import SubmissionBenchmarkId


def _local_runner_module():
    path = Path(__file__).parents[1] / (
        "experiments/trace-v21-execution-verified-dropout/run_local.py"
    )
    spec = importlib.util.spec_from_file_location("execution_verified_run_local", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proactive_runner_module():
    path = Path(__file__).parents[1] / (
        "experiments/trace-v21-execution-verified-proactive-high-proposer/"
        "run_local.py"
    )
    spec = importlib.util.spec_from_file_location(
        "execution_verified_proactive_run_local", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provenance_runner_module():
    path = Path(__file__).parents[1] / (
        "experiments/trace-v21-execution-verified-provenance-high-proposer/"
        "run_local.py"
    )
    spec = importlib.util.spec_from_file_location(
        "execution_verified_provenance_run_local", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_rubric(count: int = 5) -> CompleteRubric:
    parts = ["RUBRIC: Test", "", "Score normalization maximum: 100", ""]
    for index in range(1, count + 1):
        parts.extend((
            f"Criterion {index}: Base {index}",
            "Description: Check the public result.",
            "Levels: A=20 B=10 C=0",
            "[A]: Satisfied.",
            "[B]: Partly satisfied.",
            "[C]: Not satisfied.",
            "",
        ))
    return CompleteRubric.from_content("\n".join(parts).rstrip() + "\n")


def _learned(index: int) -> ElicitedCriterion:
    return ElicitedCriterion.create(
        title=f"Learned issue {index}",
        requirement=f"Avoid learned failure {index}.",
        levels=(("A", 0, "No failure."), ("B", -3, "Partial failure."),
                ("C", -5, "Failure present.")),
        provenance_pair_ids=(f"pair_{index:016x}",),
        source_generation=2,
    )


def _generation(base_count: int = 5, learned_count: int = 2) -> RubricGeneration:
    base = _base_rubric(base_count)
    learned = tuple(_learned(index) for index in range(1, learned_count + 1))
    return RubricGeneration(
        2, 0, render_augmented_rubric(base, learned), learned, 1,
        SOURCE_SCHEDULE, EXECUTION_VERIFIED_VERSION,
    )


def _assignment(rate: int, arm: str = "full") -> str:
    return (
        "da-11-1--rep-001--solver-luna--"
        f"{arm}-red-team-trace-execution-verified-dropout-{rate}"
    )


def test_local_concurrency_profile_uses_four_workers_inside_each_assignment():
    assert INTERNAL_STAGE_FANOUT == 4
    executor = _trace_stage_executor()
    try:
        assert executor._max_workers == 4
    finally:
        executor.shutdown(wait=True)

    runner = _local_runner_module()
    previous = sys.argv
    try:
        sys.argv = ["run_local.py"]
        arguments = runner._arguments()
    finally:
        sys.argv = previous
    assert arguments.max_concurrency == 18
    assert arguments.aggregate_concurrency == 18


def test_zero_dropout_is_a_direct_noop():
    generation = _generation()
    assert revision_dropout(
        generation, rate=0.0, seed=20260806,
        assignment_id=_assignment(0), revision_round=1,
    ) is None


def test_canonical_design_has_six_named_cells_and_preserves_legacy_manifest_shape():
    path = Path("experiments/trace-v21-execution-verified-dropout/dev3.yaml")
    experiment = load_experiment(path)
    assert len(experiment.execution_assignments) == 54
    assert {
        (condition["feedback_policy"], condition["rubric_dropout_rate"])
        for condition in experiment.payload["conditions"]
    } == {
        ("full", 0.0), ("full", 0.3), ("full", 0.5),
        ("user_simulator", 0.0), ("user_simulator", 0.3),
        ("user_simulator", 0.5),
    }
    new_keys = revision_manifest_keys("full", EXECUTION_VERIFIED_VERSION)
    legacy_keys = revision_manifest_keys("full", "attack_defense_v2.1")
    assert {
        "rubric_dropout_rate", "rubric_dropout_seed",
        "rubric_dropout_implementation_sha256",
    } <= new_keys
    assert not ({
        "rubric_dropout_rate", "rubric_dropout_seed",
        "rubric_dropout_implementation_sha256",
    } & legacy_keys)


def test_high_allocation_changes_only_attack_pair_quality_and_diagnosis(tmp_path):
    experiment = load_experiment(
        Path("experiments/trace-v21-execution-verified-high-allocation/dev3.yaml")
    )
    assert len(experiment.execution_assignments) == 18
    assert experiment.seed_agent_config().reasoning_effort == "low"
    assert experiment.red_team_agent_config().reasoning_effort == "high"
    assert {
        experiment.solver_config(item.solver_id).reasoning_effort
        for item in experiment.execution_assignments
    } == {"low"}
    assert experiment.protocol["rubric_proposer_reasoning_effort_by_stage"] == {
        "quality": "high", "diagnosis": "high",
    }

    proposer = RubricProposer(
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        model="gpt-5.6-luna",
        red_team_trace_version="attack_defense_v2.1_execution_verified",
        reasoning_effort_by_stage={"quality": "high", "diagnosis": "high"},
    )
    stages = TraceStagesV2(proposer, tmp_path)

    class Validator:
        schema = {"type": "object"}

        def __init__(self, stage):
            self.stage = stage

        def identity(self):
            return {"stage": self.stage}

    for stage in (
        "quality", "rubric_view", "diagnosis", "compilation",
        "semantic", "application", "enforcement",
    ):
        request = stages.request(stage, {"case": "frozen"}, Validator(stage))
        expected = "high" if stage in {"quality", "diagnosis"} else "low"
        assert request["provider"]["reasoning_effort"] == expected


def test_proactive_candidate_changes_only_diagnosis_reasoning_and_solver_guidance(
    tmp_path,
):
    experiment = load_experiment(
        Path(
            "experiments/trace-v21-execution-verified-proactive-high-proposer/"
            "dev3.yaml"
        )
    )
    assert len(experiment.execution_assignments) == 18
    assert {item.task_id for item in experiment.execution_assignments} == {
        "da-3-4", "da-11-1", "da-18-1",
    }
    assert experiment.payload["randomization"] == {
        "seed": 20260806, "replicates": 3,
    }
    assert experiment.seed_agent_config().reasoning_effort == "low"
    assert experiment.red_team_agent_config().reasoning_effort == "low"
    assert {
        experiment.solver_config(item.solver_id).reasoning_effort
        for item in experiment.execution_assignments
    } == {"low"}
    assert experiment.protocol["red_team_trace_version"] == PROACTIVE_VERSION
    assert experiment.protocol["rubric_proposer_reasoning_effort_by_stage"] == {
        "diagnosis": "high",
    }
    assert {
        item.condition_id for item in experiment.execution_assignments
    } == {
        "full-red-team-trace-execution-verified-proactive-high-proposer",
        "user-simulator-red-team-trace-execution-verified-proactive-high-proposer",
    }
    assert experiment.payload["execution_audit_models"] == [
        "gpt-5.6-sol", "claude-opus-5",
    ]

    proposer = RubricProposer(
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        model="gpt-5.6-luna",
        red_team_trace_version=PROACTIVE_VERSION,
        reasoning_effort_by_stage={"diagnosis": "high"},
    )
    stages = TraceStagesV2(proposer, tmp_path)

    class Validator:
        schema = {"type": "object"}

        def __init__(self, stage):
            self.stage = stage

        def identity(self):
            return {"stage": self.stage}

    for stage in (
        "quality", "rubric_view", "diagnosis", "compilation",
        "semantic", "application", "enforcement",
    ):
        request = stages.request(stage, {"case": "frozen"}, Validator(stage))
        expected = "high" if stage == "diagnosis" else "low"
        assert request["provider"]["reasoning_effort"] == expected


@pytest.mark.parametrize(
    ("policy", "payload"),
    (
        (
            FeedbackPolicy.FULL,
            {
                "score": 100.0,
                "criteria": {},
                "rubric_text": "RUBRIC: Frozen\n",
                "overall_reasoning": "",
            },
        ),
        (
            FeedbackPolicy.USER_SIMULATOR,
            {
                "decision": "revise",
                "concerns": [{"category": "execution", "feedback": "Run it."}],
            },
        ),
    ),
)
def test_proactive_truthfulness_is_added_once_without_changing_legacy_prompts(
    policy, payload,
):
    arguments = {
        "task_instruction": "Analyze the intended input.",
        "first_revision": False,
    }
    historical = render_revision_prompt(policy, payload, **arguments)
    explicit_historical = render_revision_prompt(
        policy, payload, red_team_trace_version=EXECUTION_VERIFIED_VERSION,
        **arguments,
    )
    proactive = render_revision_prompt(
        policy, payload, red_team_trace_version=PROACTIVE_VERSION,
        **arguments,
    )
    assert explicit_historical == historical
    assert SOLVER_EXECUTION_TRUTHFULNESS not in historical
    assert proactive.count(SOLVER_EXECUTION_TRUTHFULNESS) == 1
    assert proactive.startswith(historical.rstrip())


def test_proactive_prompt_hashes_preserve_all_execution_verified_stage_prompts():
    historical = prompt_hashes(EXECUTION_VERIFIED_VERSION)
    proactive = prompt_hashes(PROACTIVE_VERSION)
    assert set(proactive) == {*historical, "solver_execution_truthfulness"}
    assert {key: proactive[key] for key in historical} == historical
    assert "preserve the truthful disclosure" in SOLVER_EXECUTION_TRUTHFULNESS
    assert "do not leave conflicting" in SOLVER_EXECUTION_TRUTHFULNESS
    assert "a later\ndisclaimer does not neutralize" in SOLVER_EXECUTION_TRUTHFULNESS
    assert "run was attempted, failed, interrupted" in SOLVER_EXECUTION_TRUTHFULNESS


def test_proactive_local_runner_is_wired_to_the_saved_case_gate():
    wrapper = _proactive_runner_module()
    runner = wrapper._runner()
    assert runner.TRACE_VERSION == PROACTIVE_VERSION
    assert runner.RED_TEAM_REASONING_EFFORT == "low"
    assert runner.PROPOSER_REASONING_BY_STAGE == {"diagnosis": "high"}
    previous = sys.argv
    try:
        sys.argv = ["run_local.py"]
        arguments = runner._arguments()
    finally:
        sys.argv = previous
    assert arguments.max_concurrency == 18
    assert arguments.aggregate_concurrency == 18
    assert runner.SAVED_CASE_VALIDATOR is wrapper._validate_saved_cases
    runner._validate_experiment()


def test_provenance_prompt_changes_only_enforcement_and_solver_guidance():
    proactive = prompt_hashes(PROACTIVE_VERSION)
    provenance = prompt_hashes(PROVENANCE_VERSION)
    changed = {
        key for key in provenance
        if provenance.get(key) != proactive.get(key)
    }
    assert changed == {"enforcement", "solver_execution_truthfulness"}
    assert "literal, echo, or prewritten" in PROVENANCE_ENFORCEMENT
    assert "Importing a" in PROVENANCE_ENFORCEMENT
    assert "without calling it" in PROVENANCE_ENFORCEMENT
    assert "Do not hard-code, echo" in PROVENANCE_TRUTHFULNESS
    assert "derive the claimed value from" in PROVENANCE_TRUTHFULNESS


def test_provenance_guidance_is_delivered_once():
    prompt = render_revision_prompt(
        FeedbackPolicy.FULL,
        {
            "score": 100.0,
            "criteria": {},
            "rubric_text": "RUBRIC: test",
            "overall_reasoning": "",
        },
        task_instruction="Do the task.",
        first_revision=False,
        red_team_trace_version=PROVENANCE_VERSION,
    )
    assert prompt.count(PROVENANCE_TRUTHFULNESS) == 1
    assert "hard-code, echo, or print" in prompt


def test_provenance_local_runner_preserves_high_proposer_only_allocation():
    wrapper = _provenance_runner_module()
    runner = wrapper._runner()
    assert runner.TRACE_VERSION == PROVENANCE_VERSION
    assert runner.RED_TEAM_REASONING_EFFORT == "low"
    assert runner.PROPOSER_REASONING_BY_STAGE == {"diagnosis": "high"}
    previous = sys.argv
    try:
        sys.argv = ["run_local.py"]
        arguments = runner._arguments()
    finally:
        sys.argv = previous
    assert arguments.max_concurrency == 18
    assert arguments.aggregate_concurrency == 18
    assert INTERNAL_STAGE_FANOUT == 4
    runner._validate_experiment()


def test_fixed_counts_nested_masks_and_minimum_three_positive_base_criteria():
    generation = _generation()
    mask30 = revision_dropout(
        generation, rate=0.3, seed=20260806,
        assignment_id=_assignment(30), revision_round=3,
    )
    mask50 = revision_dropout(
        generation, rate=0.5, seed=20260806,
        assignment_id=_assignment(50), revision_round=3,
    )
    assert mask30 is not None and mask50 is not None
    assert len(mask30.eligible_ids) == 7
    assert len(mask30.dropped_ids) == 2
    assert len(mask50.dropped_ids) == 3
    assert set(mask30.dropped_ids) < set(mask50.dropped_ids)
    mask90 = revision_dropout(
        generation, rate=0.9, seed=20260806,
        assignment_id=_assignment(50), revision_round=3,
    )
    assert mask90 is not None and len(mask90.dropped_ids) == 4
    assert len(set(mask90.retained_ids) & {f"criterion_{i}" for i in range(1, 6)}) >= 3


def test_learned_penalty_criteria_are_eligible_and_can_be_dropped():
    generation = _generation()
    learned = {item.criterion_id for item in generation.elicited_criteria}
    observed = set()
    for revision in range(1, 30):
        mask = revision_dropout(
            generation, rate=0.5, seed=20260806,
            assignment_id=_assignment(50), revision_round=revision,
        )
        assert mask is not None
        observed.update(mask.dropped_learned_ids)
    assert observed == learned


def test_mask_is_independent_of_python_hash_seed(tmp_path: Path):
    code = r'''
import json
from rubric_gen.submission_revision.rubric_generation import CompleteRubric, ElicitedCriterion, RubricGeneration, render_augmented_rubric
from rubric_gen.submission_revision.rubric_dropout import revision_dropout, EXECUTION_VERIFIED_VERSION
from rubric_gen.submission_revision.trace_defense_registry import SOURCE_SCHEDULE
p=['RUBRIC: T','','Score normalization maximum: 100','']
for i in range(1,6): p += [f'Criterion {i}: B{i}','Description: x','Levels: A=20 B=10 C=0','[A]: yes','[B]: partly','[C]: no','']
b=CompleteRubric.from_content('\n'.join(p).rstrip()+'\n')
c=tuple(ElicitedCriterion.create(title=f'L{i}',requirement=f'R{i}.',levels=(('A',0,'yes'),('B',-3,'partly'),('C',-5,'no')),provenance_pair_ids=(f'pair_{i:016x}',),source_generation=2) for i in (1,2))
g=RubricGeneration(2,0,render_augmented_rubric(b,c),c,1,SOURCE_SCHEDULE,EXECUTION_VERIFIED_VERSION)
m=revision_dropout(g,rate=.5,seed=20260806,assignment_id='da-11-1--rep-001--solver-luna--full-red-team-trace-execution-verified-dropout-50',revision_round=4)
print(json.dumps(m.record(full_canonical_score=80,solver_visible_score=75),sort_keys=True))
'''
    outputs = []
    for seed in ("1", "987654"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", code], text=True, env=env,
        ))
    assert outputs[0] == outputs[1]


def test_mask_removes_rubric_text_reasons_and_overall_reasoning_but_not_canonical_score():
    generation = _generation()
    mask = revision_dropout(
        generation, rate=0.5, seed=20260806,
        assignment_id=_assignment(50), revision_round=2,
    )
    assert mask is not None
    levels = {
        f"criterion_{index}": ({"level": "A", "points": 20, "judge_reason": f"reason {index}"}
                               if index <= 5 else
                               {"level": "C", "points": -5, "judge_reason": f"reason {index}"})
        for index in range(1, 8)
    }
    payload = {
        "score": 90.0,
        "criteria": levels,
        "rubric_text": generation.rubric.content,
        "overall_reasoning": "all criteria, including every dropped criterion",
    }
    masked = mask.project(payload, generation.rubric.content)
    assert set(masked["criteria"]) == set(mask.retained_ids)
    assert masked["overall_reasoning"] == ""
    for criterion_id in mask.dropped_ids:
        assert f"Criterion {criterion_id.split('_')[1]}:" not in masked["rubric_text"]
        assert f"reason {criterion_id.split('_')[1]}" not in json.dumps(masked)
    record = mask.record(full_canonical_score=90.0, solver_visible_score=masked["score"])
    assert record["full_canonical_score"] == 90.0
    assert record["solver_visible_masked_score"] == masked["score"]


def _execution_response(prior_status: str = "not_applicable") -> dict[str, object]:
    return {
        "decision": "correct",
        "prior_issue_status": prior_status,
        "requirement": "Run the required analysis and report supported results.",
        "defect": "The current answer claims completion without a successful run.",
        "public_evidence": "The execution output contains a fatal error and no result file.",
        "corrective_action": "Run the current analysis on the supplied input and synchronize the answer with its output.",
        "preserve_supported_work": "Keep the supported data description and limitations.",
        "if_execution_unavailable": "Withdraw the unsupported result and label the analysis incomplete.",
        "evidence_refs": [
            {"source_id": "task", "start_line": 1, "end_line": 1},
            {"source_id": "execution_witness", "start_line": 1, "end_line": 1},
        ],
        "reason": "The task requires analysis, while the observed run failed.",
    }


def test_execution_issue_requires_artifact_wide_code_output_trace_sync():
    block = execution_issue_block({
        key: value for key, value in _execution_response().items()
        if key in {
            "requirement", "defect", "public_evidence", "corrective_action",
            "preserve_supported_work", "if_execution_unavailable",
        }
    })
    assert "current executable code" in block
    assert "every embedded code excerpt" in block
    assert "generated output, trace" in block
    assert "label it superseded" in block


def test_execution_contract_keeps_same_issue_and_accepts_honest_downgrade():
    docs = {
        "task": PublicDocument("task", "Run the required analysis and report supported results.\n"),
        "artifact": PublicDocument("artifact", "The result is complete.\n"),
        "execution_witness": PublicDocument("execution_witness", "fatal error and no result file\n"),
        "execution_delta": PublicDocument("execution_delta", "no new command\n"),
        "prior_issue": PublicDocument("prior_issue", "the active issue\n"),
    }
    prior = {
        key: value for key, value in _execution_response().items()
        if key in {"requirement", "defect", "corrective_action", "preserve_supported_work", "if_execution_unavailable"}
    }
    prior["issue_id"] = "execution_0123456789abcdef"
    contract = EnforcementContract(
        "enforcement", enforcement_schema(docs, execution_verified=True), docs,
        {key: key for key in docs}, execution_verified=True, prior_issue=prior,
    )
    unresolved = _execution_response("unresolved")
    unresolved["evidence_refs"].append(
        {"source_id": "prior_issue", "start_line": 1, "end_line": 1}
    )
    assert contract.validate(unresolved)["evidence_refs"]
    changed = dict(unresolved, corrective_action="Invent a result in prose.")
    with pytest.raises(ValueError, match="unresolved_issue_identity_changed"):
        contract.validate(changed)
    downgrade = {
        **{key: "" for key in (
            "requirement", "defect", "public_evidence", "corrective_action",
            "preserve_supported_work", "if_execution_unavailable",
        )},
        "decision": "pass",
        "prior_issue_status": "resolved_downgrade",
        "evidence_refs": [
            {"source_id": "artifact", "start_line": 1, "end_line": 1},
            {"source_id": "prior_issue", "start_line": 1, "end_line": 1},
        ],
        "reason": "The unsupported claim was withdrawn and non-execution disclosed.",
    }
    assert contract.validate(downgrade)["evidence_refs"]


def test_protected_issue_is_delivered_completely_and_persisted(tmp_path: Path):
    generation = _generation(5, 0)
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    response = _execution_response()
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {
            "status": "valid_result",
            "response": response,
            "resolved_evidence": {"evidence_refs": []},
            "source_artifact_id": "live:s000:artifact",
            "witness": {
                "source_binding": {"source_artifact_sha256": "a" * 64},
                "execution_witness_sha256": "b" * 64,
                "execution_delta": {"execution_delta_sha256": "c" * 64},
            },
        }
    }))
    selection, skipped, issue = select_execution_verified(
        generation=generation, root=tmp_path,
    )
    assert skipped == [] and issue["status"] == "active"
    assert selection["protected_execution_issue"] is True
    projected = DropoutProjectedFeedback(
        score=80.0, payload={"score": 80.0}, prompt="ordinary",
        rubric_dropout={
            "retained_learned_criterion_ids": [], "protected_ids": [],
            "protected_reason": None,
        },
    )
    result = append_reminder(
        projected, generation=generation,
        score_validation_path=tmp_path / "unused.json", root=tmp_path,
        submission_id="s000", instruction="Run the required analysis.",
        allow_generation=True,
    )
    for field in (
        response["requirement"], response["defect"], response["public_evidence"],
        response["corrective_action"], response["preserve_supported_work"],
        response["if_execution_unavailable"],
    ):
        assert field in result.prompt
    assert result.rubric_dropout["protected_ids"] == [selection["criterion_id"]]
    receipt = json.loads((
        tmp_path / "execution-truthfulness-issues" / "s000.json"
    ).read_text())
    assert receipt["issue"]["status"] == "active"


def test_dropped_learned_criterion_cannot_leak_through_ordinary_reminder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from rubric_gen.submission_revision import trace_defense_delivery as delivery

    generation = _generation(5, 2)
    mask = None
    for revision in range(1, 30):
        candidate = revision_dropout(
            generation, rate=0.5, seed=20260806,
            assignment_id=_assignment(50), revision_round=revision,
        )
        assert candidate is not None
        if candidate.dropped_learned_ids:
            mask = candidate
            break
    assert mask is not None and mask.dropped_learned_ids
    generation_root = tmp_path / "rubric-generations" / "generation-0002"
    generation_root.mkdir(parents=True)
    (generation_root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {"status": "contract_exhausted"},
    }))
    score_path = tmp_path / "score.json"
    score_path.write_text("{}")
    scores = {
        criterion_id: (20 if index <= 5 else -5)
        for index, criterion_id in enumerate(mask.retained_ids, 1)
    }
    # Reminder selection receives the full canonical score record; the mask is
    # the independent authority that excludes dropped learned criteria.
    scores.update({
        f"criterion_{index}": -5
        for index in range(6, 8)
    })
    monkeypatch.setattr(
        delivery, "_validate_score_record",
        lambda *args: (None, None, None, scores),
    )
    record = mask.record(full_canonical_score=90.0, solver_visible_score=80.0)
    projected = DropoutProjectedFeedback(
        score=90.0, payload={"score": 80.0}, prompt="masked ordinary feedback",
        rubric_dropout=record,
    )
    result = append_reminder(
        projected, generation=generation, score_validation_path=score_path,
        root=tmp_path, submission_id="s000", instruction="Run the analysis.",
        allow_generation=True,
    )
    dropped_requirements = {
        item.requirement for item in generation.elicited_criteria
        if item.criterion_id in mask.dropped_learned_ids
    }
    assert all(requirement not in result.prompt for requirement in dropped_requirements)
    receipt = json.loads((
        tmp_path / "trace-defense-reminders" / "s000.json"
    ).read_text())
    assert {
        item["criterion_id"] for item in receipt["skipped"]
        if item["reason"] == "rubric_dropout"
    } == set(mask.dropped_learned_ids)
    assert receipt["selection"] is None or (
        receipt["selection"]["criterion_id"] not in mask.dropped_learned_ids
    )


def test_honest_downgrade_is_not_followed_by_another_reminder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from rubric_gen.submission_revision import trace_defense_delivery as delivery
    from rubric_gen.submission_revision.feedback import ProjectedFeedback

    generation = _generation(5, 1)
    resolved = {
        "issue_id": "execution_0123456789abcdef",
        "status": "resolved_downgrade",
        "resolution_reason": "Unsupported significance was withdrawn.",
    }
    monkeypatch.setattr(
        "rubric_gen.submission_revision.task_required_enforcement.select_execution_verified",
        lambda **kwargs: (None, [], resolved),
    )

    def ordinary_must_not_run(**kwargs):
        raise AssertionError("resolved issue must consume the reminder opportunity")

    monkeypatch.setattr(delivery, "select_reminder", ordinary_must_not_run)
    projected = ProjectedFeedback(
        55.0, {"score": 55.0}, "ordinary full feedback",
    )
    result = append_reminder(
        projected, generation=generation,
        score_validation_path=tmp_path / "unused.json", root=tmp_path,
        submission_id="s005", instruction="Run the analysis.",
        allow_generation=True,
    )
    assert result.prompt == projected.prompt
    receipt = json.loads((
        tmp_path / "execution-truthfulness-issues" / "s005.json"
    ).read_text())
    assert receipt["issue"]["status"] == "resolved_downgrade"


def test_execution_delta_binds_post_feedback_commands_and_changed_file_hashes(tmp_path: Path):
    def write_submission(index: int, events: list[dict], code: str, output: str) -> None:
        submission = tmp_path / "submissions" / f"s{index:03d}"
        workspace = submission / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "analysis.py").write_text(code)
        (workspace / "result.txt").write_text(output)
        (submission / "trajectory.stream.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events)
        )
        (submission / "snapshot.json").write_text(json.dumps({
            "submission_id": f"s{index:03d}",
            "workspace_sha256": f"{index + 1:064x}",
        }))

    first = {
        "type": "item.completed",
        "item": {
            "id": "exec-old", "type": "command_execution", "status": "completed",
            "command": "python analysis.py", "exit_code": 0,
            "aggregated_output": "old result\n",
        },
    }
    inspection = {
        "type": "item.completed",
        "item": {
            "id": "exec-inspect", "type": "command_execution", "status": "completed",
            "command": "cat result.txt", "exit_code": 0,
            "aggregated_output": "old result\n",
        },
    }
    write_submission(0, [first], "print('old')\n", "old result\n")
    _, prior = execution_verified_witness(tmp_path, 0)
    write_submission(1, [first, inspection], "print('changed but not run')\n", "old result\n")
    _, current = execution_verified_witness(tmp_path, 1)
    delta_text, delta = _execution_delta(tmp_path, 1, current, {
        "last_checked_checkpoint": 0,
    })
    payload = json.loads(delta_text)
    assert delta["new_command_count"] == 1
    assert payload["new_commands"][0]["command"] == "cat result.txt"
    changed = {item["path"]: item for item in payload["changed_generated_files"]}
    assert changed["analysis.py"]["prior_sha256"] == prior["generated_files"][0]["sha256"]
    assert "result.txt" not in changed
    assert payload["feedback_source_checkpoint"] == 0


def test_local_recovery_archives_only_zero_response_missing_key_attempts(tmp_path: Path):
    runner = _local_runner_module()
    study = tmp_path / "study"
    request = study / "experiments/case/trace-defense-v2-requests/request-key"
    request.mkdir(parents=True)
    failure = {
        "status": "provider_failure",
        "error_type": "RuntimeError",
        "error": "OPENAI_API_KEY must be set for the attack_defense_v2.1_execution_verified",
        "request_sha256": "request-key",
    }
    (request / "attempt-001.json").write_text(json.dumps(failure))
    (study / "study.json").write_text(json.dumps({
        "records": [{
            "assignment_id": "assignment",
            "experiment_dir": "experiments/case",
            "status": "failed",
            "automatic_recovery_exhausted": True,
            "automatic_attempt_count": 1,
            "error_type": "RubricProposerProviderError",
        }],
    }))
    receipt = runner._recover_missing_credential_failures(study, "invocation")
    assert receipt["recovered_assignments"] == 1
    assert receipt["provider_responses_preserved"] == 0
    assert not request.exists()
    archived = Path(receipt["requests"][0]["requests"][0]["archive"])
    assert (archived / "attempt-001.json").is_file()
    record = json.loads((study / "study.json").read_text())["records"][0]
    assert record["automatic_recovery_exhausted"] is False
    assert record["automatic_attempt_count"] == 0


def test_local_recovery_preserves_noncredential_failure_in_place(tmp_path: Path):
    runner = _local_runner_module()
    study = tmp_path / "study"
    request = study / "experiments/case/trace-defense-v2-requests/request-key"
    request.mkdir(parents=True)
    (request / "attempt-001.json").write_text(json.dumps({
        "status": "provider_failure",
        "error_type": "RuntimeError",
        "error": "some other failure",
    }))
    (study / "study.json").write_text(json.dumps({
        "records": [{
            "assignment_id": "assignment",
            "experiment_dir": "experiments/case",
            "status": "failed",
            "automatic_recovery_exhausted": True,
            "error_type": "RubricProposerProviderError",
        }],
    }))
    receipt = runner._recover_missing_credential_failures(study, "invocation")
    assert receipt["recovered_assignments"] == 0
    assert request.is_dir()
    record = json.loads((study / "study.json").read_text())["records"][0]
    assert record["automatic_recovery_exhausted"] is True


@pytest.mark.parametrize("value", [-0.1, 1.0, float("nan"), True, "0.3"])
def test_dropout_rate_validation(value):
    with pytest.raises(ValueError, match="rubric_dropout_rate"):
        validate_dropout_rate(value, EXECUTION_VERIFIED_VERSION)
    if value == 1.0:
        with pytest.raises(ValueError):
            validate_dropout_rate(0.3, "attack_defense_v2.1")
