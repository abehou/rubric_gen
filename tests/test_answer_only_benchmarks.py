import json
from pathlib import Path

import pytest
import yaml

from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.benchmarks.answer_only.dataset import prepare, render_rubric, stratified_order
from rubric_gen.benchmarks.answer_only.scoring import healthbench_task_score, healthbench_mean, researchqa_coverage
from rubric_gen.runtime.agents.workspaces import TaskWorkspace
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.judging.executor import JudgeExecutor
from rubric_gen.submission_revision.judging.models import grading_engine_for_benchmark, GradingEngine
from rubric_gen.submission_revision.judging.scoring import parse_rubric_levels_strict
from rubric_gen.submission_revision.rubric_generation import CompleteRubric

BENCHMARKS = ("healthbench-hard", "researchqa-parametric")
ROOT = Path(__file__).resolve().parents[1]


def rows(benchmark):
    if benchmark == "healthbench-hard":
        return [{"prompt_id": f"health-{i:03}", "example_tags": [f"theme:group-{i % 3}"],
                 "prompt": [{"role": "user", "content": "A medical question?"}],
                 "ideal_completions_data": "HIDDEN-REFERENCE",
                 "rubrics": [{"criterion": "Gives correct guidance", "points": 5},
                             {"criterion": "Recommends harmful action", "points": -10}]}
                for i in range(30)]
    return [{"id": f"research-{i:03}", "general_domain": f"domain-{i % 3}",
             "query": "A scholarly question?", "rubric": [
                 {"rubric_item": "Does the answer cover the main result?", "type": ["Other"]},
                 {"rubric_item": "Does the answer cite a relevant study?", "type": ["Citation"],
                  "citation_metadata": "HIDDEN-REFERENCE"}]}
            for i in range(30)]


@pytest.mark.parametrize("benchmark", BENCHMARKS)
def test_prepared_task_is_native_and_hides_evaluator_data(tmp_path, benchmark):
    destination = tmp_path / "tasks"
    prepare(rows(benchmark), destination, benchmark=benchmark, subset="dev3", source="fixture")
    contract = get_submission_benchmark(benchmark)
    contract.validate_experiment(destination, ("dev-001", "dev-002", "dev-003"))
    task = destination / "dev-001"
    CompleteRubric.from_content((task / "tests/rubric.txt").read_text())
    workspace = tmp_path / "workspace"
    TaskWorkspace(task, workspace).create()
    assert not (workspace / "tests").exists()
    assert list((workspace / "data").iterdir()) == []
    prompt = contract.render_initial_solver_prompt((task / "instruction.md").read_text())
    assert "HIDDEN-REFERENCE" not in prompt
    assert "No research tools" in prompt
    assert contract.output_errors(workspace)
    (workspace / "answer.txt").write_text("Answer one.")
    assert contract.output_errors(workspace) == []
    assert "Answer one." in contract.render_workspace_review(task, workspace)
    assert contract.final_evidence(workspace)[0].content == "Answer one."
    assert contract.required_outputs == ("answer.txt",)
    revision = contract.render_revision_solver_prompt("Question", "feedback", first_revision=False)
    assert "feedback" in revision and "./answer.txt" in revision
    assert grading_engine_for_benchmark(benchmark) == GradingEngine.FULL_RUBRIC_STRUCTURED
    assert len(JudgeExecutor.scoring_implementation_sha256(benchmark)) == 64
    with pytest.raises(FileExistsError):
        prepare(rows(benchmark), destination, benchmark=benchmark, subset="dev3", source="fixture")


def test_signed_healthbench_and_native_mean_are_not_per_task_clipped():
    rubric = render_rubric(rows("healthbench-hard")[0], "healthbench-hard")
    levels = parse_rubric_levels_strict(rubric)
    assert levels == {"criterion_1": {"A": 5, "B": 0}, "criterion_2": {"A": 0, "B": -10}}
    assert healthbench_task_score([5, -10], [True, True]) == -1
    assert healthbench_mean([-1, 1]) == 0  # clipping each task first would incorrectly give .5
    assert healthbench_mean([-.2, .8]) == pytest.approx(.3)
    with pytest.raises(ValueError):
        healthbench_task_score([5], [])


def test_researchqa_preserves_five_level_coverage_and_citation_item():
    rubric = render_rubric(rows("researchqa-parametric")[0], "researchqa-parametric")
    assert "cite a relevant study" in rubric
    assert parse_rubric_levels_strict(rubric)["criterion_1"] == dict(A=4, B=3, C=2, D=1, E=0)
    assert researchqa_coverage(["Completely", "Not at all"]) == .5


@pytest.mark.parametrize("benchmark,field", [("healthbench-hard", "rubrics"), ("researchqa-parametric", "rubric")])
def test_duplicate_source_criteria_preserve_separate_weights(benchmark, field):
    row = rows(benchmark)[0]
    row[field].append(dict(row[field][0]))
    rubric = render_rubric(row, benchmark)
    CompleteRubric.from_content(rubric)
    assert len(parse_rubric_levels_strict(rubric)) == 3


def test_hard_dev_and_result_are_disjoint_and_order_invariant(tmp_path):
    data = rows("healthbench-hard")
    assert stratified_order(data, "healthbench-hard") == stratified_order(data[::-1], "healthbench-hard")
    dev = prepare(data, tmp_path / "dev", benchmark="healthbench-hard", subset="dev3", source="fixture")
    result = prepare(data, tmp_path / "result", benchmark="healthbench-hard", subset="result20", source="fixture")
    assert len(result["tasks"]) == 20
    assert not {t["source_id"] for t in dev["tasks"]} & {t["source_id"] for t in result["tasks"]}


@pytest.mark.parametrize("benchmark", BENCHMARKS)
def test_dev3_yaml_loads_all_luna_with_short_native_protocol(tmp_path, benchmark):
    destination = tmp_path / "tasks"
    prepare(rows(benchmark), destination, benchmark=benchmark, subset="dev3", source="fixture")
    config = yaml.safe_load((ROOT / "experiments" / f"{benchmark}-dev3.yaml").read_text())
    config["tasks_dir"] = str(destination)
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(config))
    experiment = load_experiment(path)
    assert len(experiment.assignments) == 18
    assert experiment.protocol["min_revisions"] == experiment.protocol["max_revisions"] == 3
    assert experiment.protocol["review"] == "workspace"
    assert config["outcome_audit"]["models"] == ["gpt-5.6-luna"]
    assert config["seed_generator"]["model"] == config["solvers"][0]["model"] == "gpt-5.6-luna"


@pytest.mark.parametrize("benchmark", BENCHMARKS)
def test_controller_preserves_revision_trajectory_without_trace_deliverable(tmp_path, benchmark):
    # Reuse the existing provider-free controller fixtures, not a second runtime.
    from test_submission_revision import _write_task, _config, FakeSession, FakeJudge
    from rubric_gen.submission_revision.controller import SubmissionRevisionController
    from rubric_gen.submission_revision.models import RevisionDependencies
    from rubric_gen.benchmarks import SubmissionBenchmarkId
    task = _write_task(tmp_path)
    (task / "environment/data/values.csv").unlink()
    (task / "tests/source.json").write_text(json.dumps({"benchmark": benchmark}))
    config = _config(tmp_path, task, rounds=3, benchmark=SubmissionBenchmarkId(benchmark), review="workspace")

    class AnswerSession(FakeSession):
        def _turn(self, workspace, prompt, turn_dir, session_id):
            result = super()._turn(workspace, prompt, turn_dir, session_id)
            (workspace / "trace.md").unlink()
            return result

    session = AnswerSession()
    judge = FakeJudge(task, (80, 55, 70, 90), tmp_path / "judge")
    result = SubmissionRevisionController(config, RevisionDependencies(session=session, judge=judge)).run()
    assert result.submission_ids == ("s000", "s001", "s002", "s003")
    assert result.scores == (80, 55, 70, 90)
    final = config.experiment_dir / "submissions/s003/workspace"
    assert not (final / "trace.md").exists()
    assert get_submission_benchmark(benchmark).final_evidence(final)[0].content == "answer-3\n"
    assert len(session.prompts) == 3
