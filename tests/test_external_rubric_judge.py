from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from rubric_gen.biomnibench import judges as judges_module
from rubric_gen.biomnibench import rubric_scoring as rubric_scoring_module
from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.judges import (
    BiomniBenchJudgeRunner,
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
)
from rubric_gen.biomnibench.task_rubric_compiler import (
    TaskProcessRubricCompiler,
    TaskRubricCompilerConfig,
    TaskRubricRequest,
    TaskRubricRewriterProvenance,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.task_rubrics import canonical_json


class StaticRewriter:
    def rewrite(self, request: TaskRubricRequest) -> str:
        task_id = request.task_snapshot["task_id"]
        return canonical_json({
            "schema_version": 1,
            "task_id": task_id,
            "purpose": "Evaluate the observable analysis process.",
            "criteria": [
                {
                    "criterion_id": "C1",
                    "title": f"Analysis for {task_id}",
                    "description": "Assess whether the required analysis was executed.",
                    "max_points": 100,
                    "task_anchors": ["summary:C1", "data:input.tsv"],
                    "required_evidence": ["Commands and outputs show the analysis."],
                    "acceptable_alternatives": ["An equivalent scripted analysis."],
                    "anti_evidence": ["A claim unsupported by a produced artifact."],
                    "verification": ["Inspect the commands and report.tsv."],
                    "levels": [
                        {
                            "label": "A",
                            "points": 100,
                            "description": "Complete and independently verifiable.",
                        },
                        {
                            "label": "B",
                            "points": 50,
                            "description": "Partial, but supported by evidence.",
                        },
                        {
                            "label": "C",
                            "points": 0,
                            "description": "No supported analysis.",
                        },
                    ],
                }
            ],
        })


class SignedPenaltyRewriter(StaticRewriter):
    def rewrite(self, request: TaskRubricRequest) -> str:
        payload = json.loads(super().rewrite(request))
        payload["criteria"].append({
            "criterion_id": "C2",
            "title": "Unsupported-claim penalty",
            "description": "Penalize claims that contradict the evidence.",
            "max_points": 0,
            "task_anchors": ["evidence:final-claims"],
            "required_evidence": ["Final claims are traceable to results."],
            "acceptable_alternatives": ["No unsupported claims are made."],
            "anti_evidence": ["The final answer invents a result."],
            "verification": ["Cross-check final claims against artifacts."],
            "levels": [
                {
                    "label": "A",
                    "points": 0,
                    "description": "Every claim is supported.",
                },
                {
                    "label": "B",
                    "points": -5,
                    "description": "One material claim is weakly supported.",
                },
                {
                    "label": "C",
                    "points": -10,
                    "description": "A material claim is contradicted.",
                },
            ],
        })
        return canonical_json(payload)


def rewriter_provenance_for(
    rewriter_type: type[object],
) -> TaskRubricRewriterProvenance:
    implementation_id = f"{rewriter_type.__module__}.{rewriter_type.__qualname__}"
    return TaskRubricRewriterProvenance(
        schema_version=1,
        provider="test-static",
        model="gemini-3.5-flash",
        implementation_id=implementation_id,
        implementation_sha256=hashlib.sha256(
            implementation_id.encode("utf-8")
        ).hexdigest(),
    )


def make_task(root: Path, task_id: str) -> Path:
    task_dir = root / task_id
    tests_dir = task_dir / "tests"
    data_dir = task_dir / "environment" / "data"
    tests_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (task_dir / "instruction.md").write_text(
        "# Task\n\n## Question\n\nAnalyze input.tsv.\n\n"
        "## Data Files\n\nUse `input.tsv`.\n\n"
        "## Required Outputs\n\nWrite `report.tsv`.\n",
        encoding="utf-8",
    )
    (task_dir / "task.toml").write_text(
        f'schema_version = "1.1"\n[task]\nname = "test/{task_id}"\n',
        encoding="utf-8",
    )
    (tests_dir / "rubric.txt").write_text(
        "Criterion 1: Local rubric\nLevels: A=100 B=50 C=0\n",
        encoding="utf-8",
    )
    (tests_dir / "process_rubric.txt").write_text(
        "Criterion 1: Explicit local rubric\nLevels: A=100 B=25 C=0\n",
        encoding="utf-8",
    )
    (tests_dir / "llm_judge.py").write_text("print('judge')\n", encoding="utf-8")
    (data_dir / "input.tsv").write_text("value\n1\n", encoding="utf-8")
    return task_dir


def compile_rubric_set(tmp_path: Path, *task_ids: str) -> tuple[Path, Path]:
    tasks_dir = tmp_path / "compiler-tasks"
    for task_id in task_ids:
        make_task(tasks_dir, task_id)
    output = tmp_path / "rubric-set"
    compiler = TaskProcessRubricCompiler(
        TaskRubricCompilerConfig(
            tasks_dir=tasks_dir,
            task_ids=tuple(task_ids),
            output_dir=output,
            max_retries=0,
        ),
        rewriter=StaticRewriter(),
        rewriter_provenance=rewriter_provenance_for(StaticRewriter),
    )
    assert compiler.run() == 0
    return output, tasks_dir


def make_target(tmp_path: Path, task_id: str = "da-1-1") -> JudgeTarget:
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    run_dir = tmp_path / "run" / "tasks" / task_id
    workspace_dir = tmp_path / "run" / "workspaces" / task_id
    run_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    trajectory = run_dir / "trajectory.stream.jsonl"
    trajectory.write_text('{"type": "message"}\n', encoding="utf-8")
    (workspace_dir / "trace.md").write_text("trace", encoding="utf-8")
    (workspace_dir / "answer.txt").write_text("answer", encoding="utf-8")
    return JudgeTarget(
        task=task_id,
        task_dir=task_dir,
        run_dir=run_dir,
        workspace_dir=workspace_dir,
        trajectory_path=trajectory,
        output_root=tmp_path / "run",
    )


def make_runner(
    tmp_path: Path,
    *,
    rubric_set: Path | None = None,
    rubric_name: str | None = None,
    dry_run: bool = False,
    resume: bool = False,
    review: str = "trace",
    model: str | None = None,
    max_review_chars: int | None = None,
    repeats: int = 1,
) -> BiomniBenchJudgeRunner:
    return BiomniBenchJudgeRunner(JudgeRunConfig(
        run_dir=tmp_path / "run",
        tasks_dir=tmp_path / "runtime-tasks",
        rubric_set=rubric_set,
        rubric_name=rubric_name,
        dry_run=dry_run,
        resume=resume,
        review=review,
        model=model,
        max_review_chars=max_review_chars,
        repeats=repeats,
    ))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_rejects_rubric_and_rubric_set_together(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args([
        "judge",
        "--run-dir",
        str(tmp_path / "run"),
        "--rubric-set",
        str(tmp_path / "rubric-set"),
    ])
    config = JudgeRunConfig.from_namespace(args)

    assert config.rubric_set == (tmp_path / "rubric-set").resolve()
    assert config.rubric_name is None

    with pytest.raises(SystemExit):
        parser.parse_args([
            "judge",
            "--run-dir",
            str(tmp_path / "run"),
            "--rubric",
            "process_rubric.txt",
            "--rubric-set",
            str(tmp_path / "rubric-set"),
        ])


def test_target_task_must_match_canonical_task_directory(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1", "da-2-1")
    target = make_target(tmp_path, "da-1-1")
    target = replace(target, task="da-2-1")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit, match="task directory"):
        runner.resolve_rubric(target)


@pytest.mark.parametrize("mismatch", ("task", "task_dir", "workspace_dir"))
def test_batch_discovery_rejects_status_identity_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    batch_dir = tmp_path / "run"
    run_dir = batch_dir / "tasks" / task_id
    workspace_dir = batch_dir / "workspaces" / task_id
    run_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    status = {
        "task": task_id,
        "task_dir": str(task_dir),
        "workspace_dir": str(workspace_dir),
    }
    replacements = {
        "task": "da-2-1",
        "task_dir": str(tmp_path / "runtime-tasks" / "da-2-1"),
        "workspace_dir": str(tmp_path / "outside-workspace"),
    }
    status[mismatch] = replacements[mismatch]
    (run_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    runner = make_runner(tmp_path)

    with pytest.raises(SystemExit):
        runner.discover_targets()


def test_single_discovery_rejects_unsafe_status_task(tmp_path: Path) -> None:
    run_dir = tmp_path / "standalone-run"
    run_dir.mkdir()
    (run_dir / "status.json").write_text(
        json.dumps({"task": "../escape"}),
        encoding="utf-8",
    )
    runner = BiomniBenchJudgeRunner(JudgeRunConfig(
        run_dir=run_dir,
        tasks_dir=tmp_path / "runtime-tasks",
    ))

    with pytest.raises(SystemExit, match="task ID"):
        runner.discover_targets()


def test_output_symlink_escape_is_rejected_before_dry_run_writes(
    tmp_path: Path,
) -> None:
    target = make_target(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (target.output_root / "judges").symlink_to(outside, target_is_directory=True)
    runner = make_runner(tmp_path, dry_run=True)

    with pytest.raises(SystemExit, match="symlink"):
        runner.review_target(target)

    assert list(outside.iterdir()) == []


def test_dry_run_does_not_create_per_target_outputs(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, dry_run=True)
    output_dir = runner.output_dir(target)

    record = runner.review_target(target)

    assert record["status"] == "planned"
    assert not output_dir.exists()


@pytest.mark.parametrize("field", ("judge_name", "rubric_name"))
@pytest.mark.parametrize(
    "unsafe_name",
    ("../escape.py", "/tmp/escape.py", "nested/escape.py", r"nested\escape.py", ".", ".."),
)
def test_judge_artifact_overrides_require_safe_basenames(
    tmp_path: Path,
    field: str,
    unsafe_name: str,
) -> None:
    kwargs = {field: unsafe_name}

    with pytest.raises(ValueError, match="basename"):
        JudgeRunConfig(
            run_dir=tmp_path / "run",
            tasks_dir=tmp_path / "runtime-tasks",
            **kwargs,
        )


def test_default_judge_symlink_is_rejected(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    judge_path = target.task_dir / "tests" / "llm_judge.py"
    outside = tmp_path / "outside-judge.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    judge_path.unlink()
    judge_path.symlink_to(outside)

    with pytest.raises(SystemExit, match="symlink"):
        make_runner(tmp_path).find_judge(target.task_dir)


def test_default_rubric_symlink_is_rejected(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    rubric_path = target.task_dir / "tests" / "rubric.txt"
    outside = tmp_path / "outside-rubric.txt"
    outside.write_text("Criterion 1:\nLevels: A=100 B=0\n", encoding="utf-8")
    rubric_path.unlink()
    rubric_path.symlink_to(outside)

    with pytest.raises(SystemExit, match="symlink"):
        make_runner(tmp_path).resolve_rubric(target)


@pytest.mark.parametrize("field", ("judge_name", "rubric_name"))
def test_overridden_judge_artifact_symlink_is_rejected(
    tmp_path: Path,
    field: str,
) -> None:
    target = make_target(tmp_path)
    override_name = "custom.py" if field == "judge_name" else "custom.txt"
    outside = tmp_path / f"outside-{override_name}"
    outside.write_text("outside\n", encoding="utf-8")
    (target.task_dir / "tests" / override_name).symlink_to(outside)
    runner = BiomniBenchJudgeRunner(JudgeRunConfig(
        run_dir=tmp_path / "run",
        tasks_dir=tmp_path / "runtime-tasks",
        **{field: override_name},
    ))

    with pytest.raises(SystemExit, match="symlink"):
        if field == "judge_name":
            runner.find_judge(target.task_dir)
        else:
            runner.resolve_rubric(target)


def test_symlinked_tests_directory_is_rejected(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    tests_dir = target.task_dir / "tests"
    outside = tmp_path / "outside-tests"
    tests_dir.rename(outside)
    tests_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SystemExit, match="symlink"):
        make_runner(tmp_path).find_judge(target.task_dir)


def test_external_judge_consumes_verified_bundle_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    bundle = resolve_rubric_bundle(rubric_set, target.task)
    verified_text = bundle.rendered_text
    verified_manifest_sha256 = bundle.task_manifest_sha256
    bundle.rendered_path.write_text("tampered after resolve", encoding="utf-8")
    bundle.task_manifest_path.write_text("tampered after resolve", encoding="utf-8")
    monkeypatch.setattr(
        judges_module,
        "resolve_rubric_bundle",
        lambda _rubric_set, _task: bundle,
    )
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    resolved = runner.resolve_rubric(target)

    assert resolved.text == verified_text
    assert resolved.manifest_sha256 == verified_manifest_sha256


def test_external_rubric_never_falls_back(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-2-1")
    target = make_target(tmp_path, "da-1-1")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit):
        runner.resolve_rubric(target)

    assert (target.task_dir / "tests" / "rubric.txt").is_file()


def test_external_rubric_rejects_root_task_manifest_mismatch(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    task_manifest_path = rubric_set / "tasks" / target.task / "manifest.json"
    task_manifest = json.loads(task_manifest_path.read_text())
    task_manifest["task_id"] = "da-9-9"
    task_manifest_path.write_text(canonical_json(task_manifest) + "\n", encoding="utf-8")
    root_manifest_path = rubric_set / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text())
    root_manifest["tasks"][target.task]["task_manifest_sha256"] = sha256_file(
        task_manifest_path
    )
    root_manifest_path.write_text(canonical_json(root_manifest) + "\n", encoding="utf-8")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit):
        runner.resolve_rubric(target)


def test_external_rubric_rejects_rendered_hash_mismatch(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    rendered = rubric_set / "tasks" / target.task / "process_rubric.txt"
    rendered.write_text(rendered.read_text() + "tampered\n", encoding="utf-8")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit):
        runner.resolve_rubric(target)


def test_dry_run_verifies_external_rubric_bundle(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    rendered = rubric_set / "tasks" / target.task / "process_rubric.txt"
    rendered.write_text(rendered.read_text() + "tampered\n", encoding="utf-8")
    runner = make_runner(tmp_path, rubric_set=rubric_set, dry_run=True)

    with pytest.raises(SystemExit):
        runner.review_target(target)


def test_task_local_and_explicit_rubric_modes_remain_supported(tmp_path: Path) -> None:
    target = make_target(tmp_path)

    default = make_runner(tmp_path).resolve_rubric(target)
    explicit = make_runner(
        tmp_path,
        rubric_name="process_rubric.txt",
    ).resolve_rubric(target)

    assert default.path == target.task_dir / "tests" / "rubric.txt"
    assert default.source == "task-local"
    assert default.rubric_id is None
    assert default.rubric_set_id is None
    assert default.structured_rubric_sha256 is None
    assert default.rendered_rubric_sha256 == hashlib.sha256(
        default.text.encode("utf-8")
    ).hexdigest()
    assert default.manifest_path is None
    assert default.manifest_sha256 is None
    assert explicit.path == target.task_dir / "tests" / "process_rubric.txt"
    assert "Explicit local rubric" in explicit.text


def write_judge_artifacts(
    cwd: Path,
    *,
    reported_score: int = 0,
    criteria: object | None = None,
) -> None:
    logs = cwd / "logs" / "verifier"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.json").write_text(
        json.dumps({"score": reported_score}),
        encoding="utf-8",
    )
    (logs / "evaluation.json").write_text(json.dumps({
        "criteria": criteria
        if criteria is not None
        else {"criterion_1": {"level": "A", "evidence": "observable"}}
    }), encoding="utf-8")


def test_authoritative_score_and_hash_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=0)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)

    result = runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )
    validation = json.loads((output_dir / "score_validation.json").read_text())

    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert result["judge_exit_code"] == 0
    assert result["score"] == 100
    assert validation == {
        "schema_version": 1,
        "scorer_version": "rubric-scoring-v1",
        "score": 100,
        "raw_score": 100,
        "reported_score": 0,
        "score_matches_reported": False,
        "selected_levels": {"criterion_1": "A"},
        "criterion_scores": {"criterion_1": 100},
        "rubric_source": "task-local",
        "rubric_set_id": None,
        "rubric_id": None,
        "structured_rubric_sha256": None,
        "rendered_rubric_sha256": resolved.rendered_rubric_sha256,
        "manifest_sha256": None,
        "reward_sha256": sha256_file(output_dir / "reward.json"),
        "evaluation_sha256": sha256_file(output_dir / "evaluation.json"),
        "review_input_sha256": hashlib.sha256(b"trace").hexdigest(),
        "answer_input_sha256": hashlib.sha256(b"answer").hexdigest(),
        "judge_source_sha256": sha256_file(
            target.task_dir / "tests" / "llm_judge.py"
        ),
        "judge_runner_sha256": sha256_file(Path(judges_module.__file__)),
        "scorer_module_sha256": sha256_file(Path(rubric_scoring_module.__file__)),
        "effective_judge_model": runner.judge_model(os.environ.copy()),
        "review_mode": "trace",
        "max_review_chars": None,
        "task": target.task,
        "run_identity": str(target.run_dir.resolve()),
        "repeat_index": 1,
    }


def test_score_validation_hashes_the_exact_parsed_reward_and_evaluation_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)
    reward_path = output_dir / "reward.json"
    evaluation_path = output_dir / "evaluation.json"
    reward_path.write_text('{"score":100}', encoding="utf-8")
    evaluation_path.write_text(
        '{"criteria":{"criterion_1":{"level":"A"}}}',
        encoding="utf-8",
    )
    reward_sha256 = sha256_file(reward_path)
    evaluation_sha256 = sha256_file(evaluation_path)
    original_load_json = runner.load_json

    def load_then_mutate(path: Path) -> object:
        value = original_load_json(path)
        path.write_text("{}", encoding="utf-8")
        return value

    monkeypatch.setattr(runner, "load_json", load_then_mutate)
    attestation = runner.score_input_attestation(
        attempt=JudgeAttempt(target, 1),
        judge_source=b"print('judge')\n",
        review_text="trace",
        answer_text="answer",
        effective_judge_model="judge-model-a",
    )

    validation = runner.build_score_validation(
        resolved,
        reward_path,
        evaluation_path,
        attestation,
    )

    assert validation["score"] == 100
    assert validation["reward_sha256"] == reward_sha256
    assert validation["evaluation_sha256"] == evaluation_sha256


def test_judge_executes_verified_text_snapshot_when_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, rubric_set=rubric_set)
    resolved = runner.resolve_rubric(target)
    verified_text = resolved.text
    resolved.path.write_text(
        "Criterion 1: Changed after resolution\nLevels: A=1 B=0\n",
        encoding="utf-8",
    )
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert (Path(cwd) / "tests" / "rubric.txt").read_text() == verified_text
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)

    result = runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )

    assert result["status"] == "completed"
    assert result["score"] == 100


def test_malformed_criteria_fail_despite_zero_judge_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), criteria={"criterion_9": {"level": "A"}})
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)

    result = runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )

    assert result["status"] == "failed"
    assert result["exit_code"] == 2
    assert result["judge_exit_code"] == 0
    assert result["score"] is None
    assert not (output_dir / "score_validation.json").exists()


def test_score_summary_excludes_failed_scalar_scores(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)

    summary = runner.score_summary([
        {"task": "da-1-1", "status": "completed", "score": 50},
        {"task": "da-1-2", "status": "failed", "score": 100},
    ])

    assert summary["scored_attempts"] == 1
    assert summary["average_score"] == 50.0
    assert summary["tasks"][1]["score"] is None


@pytest.mark.parametrize("changed", ("rubric", "reward", "evaluation"))
def test_resume_requires_matching_artifact_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    assert runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )["status"] == "completed"
    resume_runner = make_runner(tmp_path, resume=True)
    attempt = JudgeAttempt(target=target, repeat_index=1)
    assert resume_runner.completed_record(attempt) is not None

    changed_paths = {
        "rubric": target.task_dir / "tests" / "rubric.txt",
        "reward": output_dir / "reward.json",
        "evaluation": output_dir / "evaluation.json",
    }
    path = changed_paths[changed]
    path.write_text(path.read_text() + "\n", encoding="utf-8")

    assert resume_runner.completed_record(attempt) is None


def test_resume_rejects_cache_transplanted_between_repeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, repeats=2)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    assert runner.review_target(target, repeat_index=1)["status"] == "completed"
    shutil.copytree(runner.output_dir(target, 1), runner.output_dir(target, 2))

    resume_runner = make_runner(tmp_path, repeats=2, resume=True)

    assert resume_runner.completed_record(JudgeAttempt(target, 2)) is None


def test_resume_rejects_cache_transplanted_between_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_target(tmp_path, "da-1-1")
    destination = make_target(tmp_path, "da-2-1")
    runner = make_runner(tmp_path)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    assert runner.review_target(source)["status"] == "completed"
    shutil.copytree(runner.output_dir(source), runner.output_dir(destination))

    resume_runner = make_runner(tmp_path, resume=True)

    assert resume_runner.completed_record(JudgeAttempt(destination, 1)) is None


def test_resume_rejects_cache_transplanted_between_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    source = make_target(first_root)
    destination = make_target(second_root)
    first_runner = make_runner(first_root)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    assert first_runner.review_target(source)["status"] == "completed"
    second_runner = make_runner(second_root, resume=True)
    shutil.copytree(
        first_runner.output_dir(source),
        second_runner.output_dir(destination),
    )

    assert second_runner.completed_record(JudgeAttempt(destination, 1)) is None


@pytest.mark.parametrize(
    "changed",
    (
        "trace",
        "answer",
        "judge-source",
        "model",
        "max-review-chars",
        "scorer-version",
        "score-schema-type",
        "judge-runner-module",
        "scorer-module",
    ),
)
def test_resume_binds_actual_scoring_inputs_and_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    assert runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        runner.review_text(target),
        runner.read_text(target.workspace_dir / "answer.txt"),
        attempt=JudgeAttempt(target, 1),
    )["status"] == "completed"

    resume_runner = make_runner(tmp_path, resume=True, model="judge-model-a")
    if changed == "trace":
        (target.workspace_dir / "trace.md").write_text("changed trace")
    elif changed == "answer":
        (target.workspace_dir / "answer.txt").write_text("changed answer")
    elif changed == "judge-source":
        (target.task_dir / "tests" / "llm_judge.py").write_text(
            "print('changed judge')\n"
        )
    elif changed == "model":
        resume_runner = make_runner(tmp_path, resume=True, model="judge-model-b")
    elif changed == "max-review-chars":
        resume_runner = make_runner(
            tmp_path,
            resume=True,
            model="judge-model-a",
            max_review_chars=100,
        )
    elif changed == "scorer-version":
        monkeypatch.setattr(
            judges_module,
            "RUBRIC_SCORER_VERSION",
            "changed-version",
            raising=False,
        )
    elif changed == "score-schema-type":
        validation_path = output_dir / "score_validation.json"
        validation = json.loads(validation_path.read_text())
        validation["schema_version"] = True
        validation_path.write_text(json.dumps(validation))
    elif changed == "judge-runner-module":
        monkeypatch.setattr(
            BiomniBenchJudgeRunner,
            "judge_runner_sha256",
            lambda _self: "0" * 64,
            raising=False,
        )
    else:
        monkeypatch.setattr(
            BiomniBenchJudgeRunner,
            "scorer_module_sha256",
            lambda _self: "0" * 64,
            raising=False,
        )

    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_binds_exact_trajectory_review_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, review="trajectory", model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    assert runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        runner.review_text(target),
        runner.read_text(target.workspace_dir / "answer.txt"),
        attempt=JudgeAttempt(target, 1),
    )["status"] == "completed"
    target.trajectory_path.write_text('{"type": "changed"}\n')

    resume_runner = make_runner(
        tmp_path,
        resume=True,
        review="trajectory",
        model="judge-model-a",
    )
    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_binds_review_mode_even_with_identical_review_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    assert runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )["status"] == "completed"

    resume_runner = make_runner(
        tmp_path,
        resume=True,
        review="trajectory",
        model="judge-model-a",
    )
    trajectory_output = resume_runner.output_dir(target)
    shutil.copytree(output_dir, trajectory_output)
    monkeypatch.setattr(resume_runner, "review_text", lambda _target: "trace")

    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_rejects_identical_rubric_from_different_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_set, _ = compile_rubric_set(tmp_path / "first", "da-1-1")
    second_set, _ = compile_rubric_set(
        tmp_path / "second",
        "da-1-1",
        "da-2-1",
    )
    target = make_target(tmp_path)
    first_runner = make_runner(tmp_path, rubric_set=first_set)
    first_rubric = first_runner.resolve_rubric(target)
    second_rubric = make_runner(
        tmp_path,
        rubric_set=second_set,
    ).resolve_rubric(target)
    assert first_rubric.structured_rubric_sha256 == (
        second_rubric.structured_rubric_sha256
    )
    assert first_rubric.rubric_set_id != second_rubric.rubric_set_id
    assert first_rubric.manifest_sha256 != second_rubric.manifest_sha256

    output_dir = first_runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    result = first_runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        first_rubric,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )
    assert result["status"] == "completed"
    validation = json.loads((output_dir / "score_validation.json").read_text())
    assert validation["rubric_set_id"] == first_rubric.rubric_set_id
    assert validation["manifest_sha256"] == first_rubric.manifest_sha256

    second_runner = make_runner(tmp_path, rubric_set=second_set, resume=True)
    assert second_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_rejects_non_strict_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(cmd: object, *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)
    runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )
    validation_path = output_dir / "score_validation.json"
    validation = json.loads(validation_path.read_text())
    validation["unexpected"] = True
    validation_path.write_text(json.dumps(validation), encoding="utf-8")

    resume_runner = make_runner(tmp_path, resume=True)
    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_offline_frozen_rubric_workflow_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks_dir = tmp_path / "compiler-tasks"
    compiler_task = make_task(tasks_dir, "da-1-1")
    (compiler_task / "trace.md").write_text("private runtime trace", encoding="utf-8")
    (compiler_task / "answer.txt").write_text("private runtime answer", encoding="utf-8")
    runtime_dir = compiler_task / "runs" / "condition_id-private"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "trajectory.jsonl").write_text(
        '{"search_history": "private runtime history"}\n',
        encoding="utf-8",
    )
    rubric_set = tmp_path / "rubric-set"
    compiler = TaskProcessRubricCompiler(
        TaskRubricCompilerConfig(
            tasks_dir=tasks_dir,
            task_ids=(compiler_task.name,),
            output_dir=rubric_set,
            max_retries=0,
        ),
        rewriter=SignedPenaltyRewriter(),
        rewriter_provenance=rewriter_provenance_for(SignedPenaltyRewriter),
    )

    assert compiler.run() == 0
    bundle = resolve_rubric_bundle(rubric_set, compiler_task.name)
    request_path = bundle.task_manifest_path.parent / "attempts" / "attempt-1" / "request.json"
    compiler_request = request_path.read_text(encoding="utf-8")

    target = make_target(tmp_path, compiler_task.name)
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    def fake_run(
        cmd: object,
        *,
        cwd: Path,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(
            Path(cwd),
            reported_score=99,
            criteria={
                "criterion_1": {"level": "C", "evidence": "missing analysis"},
                "criterion_2": {"level": "C", "evidence": "contradicted claim"},
            },
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="offline judge\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judges.subprocess.run", fake_run)

    record = runner.review_target(target)
    final_record = json.loads(Path(record["score_validation"]).read_text())

    assert record["status"] == "completed"
    assert record["rubric_set_id"] == bundle.rubric_set_id
    assert record["structured_rubric_sha256"] == bundle.rubric_sha256
    assert final_record["rubric_set_id"] == bundle.rubric_set_id
    assert final_record["structured_rubric_sha256"] == bundle.rubric_sha256
    assert final_record["raw_score"] == -10
    assert final_record["score"] == record["score"] == 0
    for forbidden in (
        "trajectory",
        "trace.md",
        "answer.txt",
        "condition_id",
        "search_history",
    ):
        assert forbidden not in compiler_request
