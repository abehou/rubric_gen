"""Local rubric-dropout correctness and complete trace revision smokes."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
import yaml

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.feedback import FeedbackPolicy, project_rubric_feedback
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict, validate_judge_score,
)
from rubric_gen.submission_revision.rubric_dropout import revision_dropout
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric, ElicitedCriterion, RubricGeneration, RubricPolicy, render_augmented_rubric,
)


def rubric(weights=(4, 6, 10, 12, 14, 16, 18, 20)):
    return CompleteRubric.from_content(
        f"Score normalization maximum: {sum(weights)}\n\n" + "\n".join(
            f"Criterion {i}: Requirement-marker-{i}\n"
            f"Description: Check evidence-marker-{i}.\n"
            f"Levels: A={weight} B={weight // 2} C=0\n"
            f"[A]: Complete.\n[B]: Partial.\n[C]: Absent.\n"
            for i, weight in enumerate(weights, 1)
        )
    )


def mask(text, **kwargs):
    return revision_dropout(text, **{
        "rate": 0.3, "seed": 42, "assignment_id": "assignment", "revision_round": 1,
        **kwargs,
    })


def judgment(root, text, *, active=False):
    root.mkdir(parents=True)
    levels = parse_rubric_levels_strict(text)
    criteria = {}
    for i, (key, points) in enumerate(levels.items()):
        level = "B" if max(points.values()) == 0 or i % 2 else "C" if active else "A"
        criteria[key] = {"level": level, "points": points[level], "reason": f"reason-{key}"}
    evaluation = {"criteria": criteria, "reasoning": "global summary: " + " ".join(criteria)}
    evaluation_text = json.dumps(evaluation)
    score = validate_judge_score(
        rubric_levels=levels, evaluation=evaluation, reward={"score": 0},
        normalization_maximum=sum(max(points.values()) for points in levels.values()),
    )
    validation = {**asdict(score), "rendered_rubric_sha256": sha256_text(text),
                  "evaluation_sha256": sha256_text(evaluation_text)}
    (root / "evaluation.json").write_text(evaluation_text)
    (root / "score_validation.json").write_text(json.dumps(validation))
    return root / "score_validation.json", root / "evaluation.json"


@pytest.fixture
def feedback_inputs(tmp_path):
    base = rubric()
    penalty = ElicitedCriterion.create(
        title="Learned public check", requirement="Inspect the public evidence.",
        levels=(("A", 0, "Pass."), ("B", -5, "Moderate."), ("C", -10, "Material.")),
        provenance_pair_ids=("pair_" + "1" * 16,), source_generation=1,
    )
    active = render_augmented_rubric(base, (penalty,))
    generation = RubricGeneration(1, None, active, (penalty,), 4)
    return {
        "generation": generation,
        "artifacts": judgment(tmp_path / "active", active.content, active=True),
        "reference_artifacts": judgment(tmp_path / "reference", base.content),
        "reference_rubric_text": base.content,
        "reference_rubric_sha256": base.content_sha256,
        "task_instruction": "Inspect the table.", "first_revision": True,
    }


def test_zero_is_direct_noop():
    assert mask("not even parsed at zero", rate=0.0) is None


@pytest.mark.parametrize("policy", [FeedbackPolicy.FULL, FeedbackPolicy.SEMI, FeedbackPolicy.SCORE_ONLY])
def test_zero_feedback_and_serialization_parity(feedback_inputs, policy):
    ordinary = project_rubric_feedback(**feedback_inputs, policy=policy)
    zero = project_rubric_feedback(**feedback_inputs, policy=policy, rubric_dropout=mask("", rate=0.0))
    assert zero == ordinary
    assert json.dumps(asdict(zero), sort_keys=True) == json.dumps(asdict(ordinary), sort_keys=True)
    assert zero.rubric_dropout is None


def test_determinism_round_variation_and_source_immutability():
    source = rubric()
    before = asdict(source)
    first = mask(source.content)
    assert mask(source.content) == first
    rounds = [mask(source.content, revision_round=i) for i in range(1, 8)]
    assert len({item.deterministic_key for item in rounds}) == 7
    assert len({item.dropped_ids for item in rounds}) > 1
    assert mask(source.content, seed=43).deterministic_key != first.deterministic_key
    assert mask(source.content, assignment_id="another").deterministic_key != first.deterministic_key
    assert asdict(source) == before


def test_mask_is_stable_across_processes_and_python_hash_seeds():
    code = (
        "from dataclasses import asdict; import json; "
        "from rubric_gen.submission_revision.rubric_dropout import revision_dropout; "
        f"print(json.dumps(asdict(revision_dropout({rubric().content!r}, "
        "rate=0.999, seed=42, assignment_id='assignment', revision_round=1))))"
    )
    outputs = [subprocess.check_output(
        [sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}, text=True,
    ) for seed in ("1", "937")]
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 8])
def test_minimum_retained(count):
    text = rubric((10,) * count).content
    for step in range(20):
        selection = mask(text, rate=0.999999, revision_round=step)
        assert len(selection.retained_ids) >= min(3, count)
        if count < 3:
            assert not selection.dropped_ids


@pytest.mark.parametrize("policy", [FeedbackPolicy.FULL, FeedbackPolicy.SEMI, FeedbackPolicy.SCORE_ONLY])
def test_score_feedback_and_full_evaluation(feedback_inputs, policy):
    generation = feedback_inputs["generation"]
    snapshot = asdict(generation)
    source_files = {path: path.read_bytes() for key in ("artifacts", "reference_artifacts") for path in feedback_inputs[key]}
    ordinary = project_rubric_feedback(**feedback_inputs, policy=FeedbackPolicy.FULL)
    selection = mask(generation.rubric.content)
    assert selection.dropped_ids
    assert "criterion_9" in selection.retained_ids  # Learned penalty, maximum zero.
    result = project_rubric_feedback(**feedback_inputs, policy=policy, rubric_dropout=selection)
    levels = parse_rubric_levels_strict(generation.rubric.content)
    retained = {key: ordinary.payload["criteria"][key] for key in selection.retained_ids}
    expected = validate_judge_score(
        rubric_levels={key: levels[key] for key in retained},
        evaluation={"criteria": retained}, reward={"score": 0},
        normalization_maximum=sum(max(levels[key].values()) for key in retained),
    ).score
    assert result.payload["score"] == expected
    assert result.score == ordinary.score  # Canonical value never replaced.
    assert result.rubric_dropout == selection.record(expected)
    for key in selection.dropped_ids:
        assert f'"{key}"' not in result.prompt
        assert f"Requirement-marker-{key.split('_')[1]}" not in result.prompt
        assert f"reason-{key}" not in result.prompt
    if policy is not FeedbackPolicy.SCORE_ONLY:
        assert set(result.payload["criteria"]) == set(selection.retained_ids)
    if policy is FeedbackPolicy.FULL:
        assert result.payload["overall_reasoning"] == ""
        assert "reason-criterion_9" in result.prompt
        assert set(parse_rubric_levels_strict(result.payload["rubric_text"])) == set(selection.retained_ids)
    assert asdict(generation) == snapshot
    assert all(path.read_bytes() == content for path, content in source_files.items())


def test_signed_and_zero_weight_criteria_are_kept():
    text = rubric().content + "\nCriterion 9: Penalty\nLevels: A=0 B=-5 C=-10\n"
    text += "\nCriterion 10: Informational\nLevels: A=0 B=0\n"
    selection = mask(text, rate=0.99)
    assert {"criterion_9", "criterion_10"} <= set(selection.retained_ids)
    # Eligibility depends on scoring points, not origin, name, or observed grade.
    text += "\nCriterion 11: Future positive learned criterion\nLevels: A=10 B=0\n"
    assert any("criterion_11" in mask(text, revision_round=i).dropped_ids for i in range(20))
    no_positive = mask("Criterion 1: Penalty\nLevels: A=0 B=-5 C=-10\n")
    assert no_positive.retained_ids == ("criterion_1",) and not no_positive.dropped_ids


def test_config_zero_identity_nonzero_roundtrip_and_wiring(tmp_path, monkeypatch):
    import test_experiment as fixture
    from rubric_gen.submission_revision.experiment import load_experiment
    from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner
    for task in ("da-1-1", "da-2-1"):
        fixture._task(tmp_path, task)
    payload = fixture._payload(tmp_path)
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload))
    original = load_experiment(path)
    for condition in payload["conditions"]:
        condition["rubric_dropout_rate"] = 0.0
    path.write_text(yaml.safe_dump(payload))
    zero = load_experiment(path)
    assert zero.payload == original.payload
    trace = next(c for c in payload["conditions"] if c["condition_id"] == "full-red-team-trace")
    trace["rubric_dropout_rate"] = 0.3
    path.write_text(yaml.safe_dump(payload))
    enabled = load_experiment(path)
    assert enabled.experiment_id != original.experiment_id
    assert enabled.assignments == original.assignments
    assert enabled.condition("full-red-team-trace")["rubric_dropout_rate"] == 0.3
    # Exercise the actual study -> controller config boundary without a run.
    import test_submission_revision as revision
    revision._resolve_test_paraphrase.__wrapped__(monkeypatch)
    task = enabled.task_dir("da-1-1")
    (task / "tests/development-rubric.txt").write_text((task / "tests/rubric.txt").read_text() + "\n")
    runner = StudyRunner(StudyRunConfig(
        experiment=enabled, output_dir=tmp_path / "study", seed_run_dir=tmp_path / "seeds",
        paraphrase_run_dir=tmp_path / "paraphrases", max_concurrency=1,
    ))
    assignment = next(a for a in enabled.assignments if a.condition_id == "full-red-team-trace" and a.task_id == "da-1-1")
    config = runner._revision_config(assignment, resume=False)
    assert config.rubric_dropout_rate == 0.3 and config.randomization_seed == 42


@pytest.mark.parametrize("bad", [-0.1, 1.0, float("nan"), float("inf"), True, "0.3", None])
def test_invalid_rate_rejected(tmp_path, bad):
    import test_experiment as fixture
    from rubric_gen.submission_revision.experiment import load_experiment
    fixture._task(tmp_path, "da-1-1")
    fixture._task(tmp_path, "da-2-1")
    payload = fixture._payload(tmp_path)
    payload["conditions"][0]["rubric_dropout_rate"] = bad
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload))
    with pytest.raises(ValueError, match="rubric_dropout_rate"):
        load_experiment(path)


def test_non_trace_dropout_rejected(tmp_path):
    import test_submission_revision as fixture
    config = fixture._config(tmp_path, fixture._write_task(tmp_path), rounds=1)
    with pytest.raises(ValueError, match="requires red_team_trace"):
        replace(config, rubric_dropout_rate=0.3)


def test_reminder_uses_retained_ids(tmp_path, monkeypatch, feedback_inputs):
    from rubric_gen.submission_revision import trace_defense_delivery as delivery
    generation = feedback_inputs["generation"]
    ordinary = project_rubric_feedback(**feedback_inputs, policy=FeedbackPolicy.FULL)
    selection = mask(generation.rubric.content)
    projected = replace(ordinary, rubric_dropout=selection.record(ordinary.score))
    arguments = dict(generation=generation, score_validation_path=feedback_inputs["artifacts"][0],
                     root=tmp_path / "kept", submission_id="s000", instruction="Inspect public evidence.", allow_generation=True)
    delivered = delivery.append_reminder(projected, **arguments)
    assert generation.elicited_criteria[0].requirement in delivered.prompt
    # Future positive learned criteria must also respect the rendered-ID mask.
    hidden = replace(projected, prompt="ordinary", rubric_dropout={
        **projected.rubric_dropout, "retained_criterion_ids": list(selection.retained_ids[:-1]),
    })
    delivered = delivery.append_reminder(hidden, **{**arguments, "root": tmp_path / "hidden"})
    assert delivered.prompt == "ordinary"


@pytest.mark.parametrize("rate,policy,interrupt", [
    (0.0, FeedbackPolicy.FULL, False),
    (0.3, FeedbackPolicy.FULL, False),
    (0.0, FeedbackPolicy.USER_SIMULATOR, False),
    (0.3, FeedbackPolicy.USER_SIMULATOR, False),
    (0.3, FeedbackPolicy.USER_SIMULATOR, True),
])
def test_local_trace_smoke(tmp_path, monkeypatch, rate, policy, interrupt):
    import test_submission_revision as fixture
    from test_trace_defense_v2 import _proposer_output
    from rubric_gen.benchmarks import get_submission_benchmark
    from rubric_gen.runtime.agents.sessions import SessionTurnResult
    from rubric_gen.submission_revision.controller import SubmissionRevisionController
    from rubric_gen.submission_revision.evolution import RubricProposer
    from rubric_gen.submission_revision.judge import FrozenRubricJudge, resolve_optimizer_rubric
    from rubric_gen.submission_revision.models import RevisionDependencies
    from rubric_gen.submission_revision.red_team import RedTeamGenerator
    from rubric_gen.submission_revision.user_simulator import (
        SimulatedUserConfig, SimulatedUserFeedback, SimulatedUserGeneration,
    )

    fixture._resolve_test_paraphrase.__wrapped__(monkeypatch)
    task = fixture._write_task(tmp_path)
    version = "attack_defense_v2.1"
    master_config = fixture.SubmissionJudgeConfig(
        task_dir=task, experiment_dir=tmp_path / "master", review="trace",
        judge_model="test-judge-model", rubric_name="rubric.txt", rubric_set=None,
        max_review_chars=None,
    )
    master_identity = FrozenRubricJudge(master_config, resolve_optimizer_rubric(master_config)).scoring_identity()
    base = fixture._config(tmp_path, task, rounds=2, seed_scoring_identity=master_identity)
    selected = tmp_path / "selected.txt"
    selected.write_text(rubric().content)
    condition_id = f"{policy.value.replace('_', '-')}-red-team-trace"
    config = replace(
        base, optimizer_rubric_path=selected, rubric_policy=RubricPolicy.RED_TEAM_TRACE,
        condition_id=condition_id,
        assignment_id=f"{task.name}--rep-001--solver-test-solver--{condition_id}",
        red_team_trace_version=version, rubric_dropout_rate=rate, randomization_seed=42,
        feedback_policy=policy, feedback_simulator=SimulatedUserConfig(model="test-simulator")
        if policy is FeedbackPolicy.USER_SIMULATOR else None,
    )
    fixture._prepare_test_pretreatment_rubric(config, task, fixture._criterion_elicitation_proposer(config))
    calls = []

    def propose(*, stage, evidence, response_schema):
        calls.append(stage)
        value = json.loads(evidence)
        if stage == "quality":
            answer = {"artifact_assessments": {"artifact_A": "Equal.", "artifact_B": "Equal."},
                      "decisive_refs": [], "preferred_artifact_id": None, "reason": "Unordered."}
        elif stage == "rubric_view":
            answer = {"artifact_id": value["artifact"]["artifact_id"], "base_score": 80,
                      "criterion_levels": [], "reason": "Same rubric."}
        else:
            raise AssertionError(stage)
        output = _proposer_output(answer, stage)
        return replace(output, generation={**output.generation,
            "requested_model": config.rubric_proposer_model, "effective_model": config.rubric_proposer_model})

    def attack(workspace, prompt, turn_dir):
        calls.append("attack")
        (workspace / "answer.txt").write_text("Synthetic contrast.")
        turn_dir.mkdir(parents=True)
        trajectory = turn_dir / "trajectory.stream.jsonl"
        trajectory.write_text('{"role":"assistant","content":"fixture"}\n')
        return SessionTurnResult("attack", "test-model", 0, trajectory)

    class MultiJudge(fixture.FakeJudge):
        def evaluate(self, submission_dir, attempt_id):
            artifacts = super().evaluate(submission_dir, attempt_id)
            validation_path, evaluation_path = judgment(tmp_path / f"grade-{self.calls}", selected.read_text())
            data = json.loads(validation_path.read_text())
            artifacts.evaluation_path.write_bytes(evaluation_path.read_bytes())
            record = json.loads(artifacts.score_validation_path.read_text())
            record.update(data)
            reward = artifacts.evaluation_path.parent / "reward.json"
            reward.write_text(json.dumps({"reward": data["normalized_score"]}))
            record["reward_sha256"] = fixture.sha256_file(reward)
            artifacts.score_validation_path.write_text(json.dumps(record))
            return artifacts

    identity = FrozenRubricJudge(config.judge_config(), resolve_optimizer_rubric(config.judge_config())).scoring_identity()
    judge = MultiJudge(task, (0, 80, 80, 80), tmp_path / "judge", identity=identity)
    requests = []

    def simulate(sim_config, request):
        requests.append(request)
        current = request.evidence.split("<full_evaluator_feedback>")[1].split("</full_evaluator_feedback>")[0]
        payload = json.loads(current)
        selection = mask(selected.read_text(), rate=rate, assignment_id=config.assignment_id, revision_round=len(requests))
        assert set(payload["criteria"]) == set(selection.retained_ids if selection else parse_rubric_levels_strict(selected.read_text()))
        if selection:
            for key in selection.dropped_ids:
                assert f"reason-{key}" not in current
                assert f"Requirement-marker-{key.split('_')[1]}" not in current
        if len(requests) == 2:
            assert '"feedback_checkpoint":"s000"' in request.evidence
        return SimulatedUserGeneration(
            text=json.dumps({"decision": "revise", "concerns": [{
                "category": "evidence_traceability", "feedback": "Please verify the public evidence."}]}),
            provider="openai", requested_model=sim_config.model, effective_model=sim_config.model,
            response_id=f"feedback-{len(requests)}",
            request_parameters={"max_output_tokens": sim_config.max_output_tokens}, provider_metadata={},
        )

    session = fixture.FakeSession(fail=interrupt)
    dependencies = RevisionDependencies(
        session=session, judge=judge,
        master_judge=fixture.FakeJudge(task, (0, 80, 80), tmp_path / "master", identity=master_identity),
        rubric_proposer=RubricProposer(
            benchmark=config.benchmark, model=config.rubric_proposer_model,
            max_retries=config.rubric_proposer_max_retries, run_proposer=propose, red_team_trace_version=version),
        red_team_generator=RedTeamGenerator(agent=config.red_team_agent, benchmark=get_submission_benchmark(config.benchmark),
                                             run_sidecar=attack, red_team_trace_version=version),
        feedback_simulator=SimulatedUserFeedback(config.feedback_simulator, generator=simulate)
        if config.feedback_simulator else None,
    )
    controller = SubmissionRevisionController(config, dependencies)
    if interrupt:
        with pytest.raises(RuntimeError):
            controller.run()
        prior_prompt = session.prompts[0]
        prior_feedback = (config.experiment_dir / "feedback/s000.json").read_bytes()
        session.fail = False
        controller = SubmissionRevisionController(replace(config, resume=True), dependencies)
    result = controller.run()
    if interrupt:
        assert session.prompts[1] == prior_prompt
        assert (config.experiment_dir / "feedback/s000.json").read_bytes() == prior_feedback
    assert len(result.submission_ids) == 3 and judge.calls == 3
    events = [json.loads(line) for line in (config.experiment_dir / "events.jsonl").read_text().splitlines()]
    judged = [event for event in events if event["event"] == "submission_judged"]
    for i, event in enumerate(judged):
        evaluation = json.loads((config.experiment_dir / f"rubric-evaluations/s{i:03d}.json").read_text())
        assert evaluation["score"] == result.scores[i] == 73.0
        assert evaluation["canonical_original_score"] == 80.0
        if rate and i < 2:
            selection = mask(selected.read_text(), rate=rate, assignment_id=config.assignment_id, revision_round=i + 1)
            assert selection.dropped_ids
            assert event["rubric_dropout"]["dropped_criterion_ids"] == list(selection.dropped_ids)
            assert event["rubric_dropout"]["retained_criterion_ids"] == list(selection.retained_ids)
            assert event["score"] == 73.0
            if policy is FeedbackPolicy.FULL:
                payload = json.loads((config.experiment_dir / f"feedback/s{i:03d}.json").read_text())
                assert payload["score"] == event["rubric_dropout"]["optimization_score"]
                assert set(payload["criteria"]) == set(selection.retained_ids)
        else:
            assert "rubric_dropout" not in event
    before = (judge.calls, len(requests), len(session.prompts), len(calls))
    assert SubmissionRevisionController(replace(config, resume=True), dependencies).run() == result
    assert before == (judge.calls, len(requests), len(session.prompts), len(calls))
    selection = SimpleNamespace(
        optimizer_path=selected, optimizer_sha256=fixture.sha256_file(selected),
        master_path=task / "tests/rubric.txt", master_sha256=fixture.sha256_file(task / "tests/rubric.txt"),
        development_path=config.development_rubric_path, development_sha256=fixture.sha256_file(config.development_rubric_path),
    )
    monkeypatch.setattr(fixture.paraphrase_validation_module, "resolve_paraphrase_selection", lambda *_: selection)
    design = fixture._design(config, task)
    design.payload["protocol"]["red_team_trace_version"] = version
    design.payload["randomization"]["seed"] = 42
    if rate:
        design.condition(config.condition_id)["rubric_dropout_rate"] = rate
    fixture.validate_completed_revision(config.experiment_dir, fixture._validation_assignment(config, task), design,
                                        config.seed_run_dir, config.experiment_dir / "paraphrases")
    from rubric_gen.submission_revision.evaluation.targets import _load_terminal_revision_state
    terminal = _load_terminal_revision_state(
        config.experiment_dir, fixture._validation_assignment(config, task),
        SimpleNamespace(experiment=design), selection, config.experiment_id,
    )
    assert terminal["scores"] == list(result.scores)
    print(json.dumps({"rate": rate, "feedback": policy.value, "interrupted": interrupt,
                      "solver_turns": len(session.prompts), "full_scores": list(result.scores),
                      "masks": [event.get("rubric_dropout") for event in judged[:2]]}))
