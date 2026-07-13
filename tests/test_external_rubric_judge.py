from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

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
) -> BiomniBenchJudgeRunner:
    return BiomniBenchJudgeRunner(JudgeRunConfig(
        run_dir=tmp_path / "run",
        tasks_dir=tmp_path / "runtime-tasks",
        rubric_set=rubric_set,
        rubric_name=rubric_name,
        dry_run=dry_run,
        resume=resume,
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


def test_external_lookup_uses_validated_target_task(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1", "da-2-1")
    target = make_target(tmp_path, "da-1-1")
    target = replace(target, task="da-2-1")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    resolved = runner.resolve_rubric(target)

    assert resolved.path.parent.name == "da-2-1"
    assert "Analysis for da-2-1" in resolved.text
    assert resolved.source == "rubric-set"
    assert resolved.rubric_id is not None
    assert resolved.rubric_set_id is not None
    assert resolved.structured_rubric_sha256 == resolve_rubric_bundle(
        rubric_set,
        "da-2-1",
    ).rubric_sha256
    assert resolved.rendered_rubric_sha256 == hashlib.sha256(
        resolved.text.encode("utf-8")
    ).hexdigest()
    assert resolved.manifest_path == resolved.path.parent / "manifest.json"
    assert resolved.manifest_sha256 == sha256_file(resolved.manifest_path)


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
    )
    validation = json.loads((output_dir / "score_validation.json").read_text())

    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert result["judge_exit_code"] == 0
    assert result["score"] == 100
    assert validation == {
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
    }


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
    )
    validation_path = output_dir / "score_validation.json"
    validation = json.loads(validation_path.read_text())
    validation["unexpected"] = True
    validation_path.write_text(json.dumps(validation), encoding="utf-8")

    resume_runner = make_runner(tmp_path, resume=True)
    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None
