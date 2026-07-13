from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
from dataclasses import asdict, replace
from pathlib import Path

import pytest

import rubric_gen.biomnibench as biomnibench
from rubric_gen.biomnibench import cli as cli_module
from rubric_gen.biomnibench import process_rubrics as process_rubrics_module
from rubric_gen.biomnibench import task_rubric_compiler as compiler_module
from rubric_gen.biomnibench import task_rubrics as task_rubrics_module
from rubric_gen.biomnibench.common import resolve_project_path
from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.task_rubric_compiler import (
    GeminiTaskRubricRewriter,
    RubricBundleError,
    TaskProcessRubricCompiler,
    TaskRubricCompilerConfig,
    TaskRubricRequest,
    build_task_rubric_prompt,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.task_rubrics import (
    TaskSnapshot,
    build_task_snapshot,
    canonical_json,
    sha256_text,
)


class FakeRewriter:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[TaskRubricRequest] = []

    def rewrite(self, request: TaskRubricRequest) -> str:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def publish_in_subprocess(
    temporary: Path,
    output: Path,
    result_queue: object,
) -> None:
    result_queue.put(("ready", ""))  # type: ignore[attr-defined]
    try:
        TaskProcessRubricCompiler._publish(temporary, output)
    except Exception as exc:
        result_queue.put((type(exc).__name__, str(exc)))  # type: ignore[attr-defined]
    else:
        result_queue.put(("published", ""))  # type: ignore[attr-defined]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_canonical_json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def make_task(root: Path, task_id: str = "da-1-1") -> Path:
    task = root / task_id
    data = task / "environment" / "data"
    data.mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "instruction.md").write_text(
        """# Task

## Question

Which genes respond to treatment?

## Data Files

Use `gene_exp.diff`.

## Required Outputs

Write `report.tsv`.
""",
        encoding="utf-8",
    )
    (task / "task.toml").write_text(
        f'schema_version = "1.1"\n[task]\nname = "phylo/{task_id}"\n',
        encoding="utf-8",
    )
    (task / "tests" / "rubric.txt").write_text(
        """Criterion 1: Correct comparison

    Description: Compare treated and control samples.
    Levels: A=100 B=50 C=0
      [A]: Correct.
      [B]: Partial.
      [C]: Missing.
""",
        encoding="utf-8",
    )
    (data / "gene_exp.diff").write_text(
        "gene_id\tcondition\tlog2fc\nENSG000001\ttreated\t2.0\n",
        encoding="utf-8",
    )

    # Runtime artifacts deliberately live beside immutable task inputs.
    (task / "trace.md").write_text("runtime trace", encoding="utf-8")
    (task / "answer.txt").write_text("runtime answer", encoding="utf-8")
    run_dir = task / "runs" / "condition_id-secret"
    run_dir.mkdir(parents=True)
    (run_dir / "trajectory.jsonl").write_text(
        '{"search_history": "runtime"}\n',
        encoding="utf-8",
    )
    return task


def valid_rubric(snapshot: TaskSnapshot) -> str:
    return canonical_json({
        "schema_version": 1,
        "task_id": snapshot.task_id,
        "purpose": "Evaluate the observable, evidence-grounded analysis process.",
        "criteria": [
            {
                "criterion_id": "C1",
                "title": "Task-specific analysis",
                "description": "Assess whether the required comparison was executed.",
                "max_points": 100,
                "task_anchors": ["summary:C1", "data:gene_exp.diff"],
                "required_evidence": ["Commands and outputs show the comparison."],
                "acceptable_alternatives": ["An equivalent scripted comparison."],
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
                        "description": "Partial, but supported by observable evidence.",
                    },
                    {
                        "label": "C",
                        "points": 0,
                        "description": "No supported comparison.",
                    },
                ],
            }
        ],
    })


def make_compiler(
    tmp_path: Path,
    *,
    responses: list[str | Exception] | None = None,
    output_name: str = "rubric-set",
    resume: bool = False,
    max_retries: int = 1,
    model: str = "gemini-3.5-flash",
) -> tuple[TaskProcessRubricCompiler, FakeRewriter, Path, Path]:
    tasks_dir = tmp_path / "tasks"
    task_dir = tasks_dir / "da-1-1"
    if not task_dir.exists():
        make_task(tasks_dir)
    snapshot = build_task_snapshot(task_dir)
    rewriter = FakeRewriter(responses or [valid_rubric(snapshot)])
    output = tmp_path / output_name
    config = TaskRubricCompilerConfig(
        tasks_dir=tasks_dir,
        task_ids=("da-1-1",),
        output_dir=output,
        model=model,
        max_retries=max_retries,
        resume=resume,
    )
    return TaskProcessRubricCompiler(config, rewriter=rewriter), rewriter, output, task_dir


def compile_fixture(tmp_path: Path, *, output_name: str = "rubric-set") -> Path:
    compiler, _, output, _ = make_compiler(tmp_path, output_name=output_name)
    assert compiler.run() == 0
    return output


def compile_partial_fixture(tmp_path: Path) -> Path:
    tasks_dir = tmp_path / "tasks"
    first_task = make_task(tasks_dir, "da-1-1")
    make_task(tasks_dir, "da-2-1")
    rewriter = FakeRewriter([
        valid_rubric(build_task_snapshot(first_task)),
        "not JSON",
    ])
    output = tmp_path / "rubric-set"
    compiler = TaskProcessRubricCompiler(
        TaskRubricCompilerConfig(
            tasks_dir=tasks_dir,
            task_ids=("da-1-1", "da-2-1"),
            output_dir=output,
            max_retries=0,
        ),
        rewriter=rewriter,
    )
    assert compiler.run() == 1
    return output


def compile_retry_fixture(tmp_path: Path) -> Path:
    tasks_dir = tmp_path / "tasks"
    task_dir = make_task(tasks_dir)
    compiler, _, output, _ = make_compiler(
        tmp_path,
        responses=["not JSON", valid_rubric(build_task_snapshot(task_dir))],
    )
    assert compiler.run() == 0
    return output


def reseal_task_after_attempt_mutation(output: Path, task_id: str) -> None:
    task_dir = output / "tasks" / task_id
    task_manifest_path = task_dir / "manifest.json"
    task_manifest = json.loads(task_manifest_path.read_text())
    task_manifest["artifacts"] = {
        path.relative_to(task_dir).as_posix(): sha256_file(path)
        for path in sorted(task_dir.rglob("*"))
        if path.is_file() and path != task_manifest_path
    }
    attempt_dirs = sorted(
        (task_dir / "attempts").glob("attempt-*"),
        key=lambda path: int(path.name.removeprefix("attempt-")),
    )
    final_request = json.loads((attempt_dirs[-1] / "request.json").read_text())
    request = TaskRubricRequest(
        schema_version=final_request["schema_version"],
        prompt_version=final_request["prompt_version"],
        task_snapshot=final_request["task_snapshot"],
        previous_errors=tuple(final_request["previous_errors"]),
    )
    task_manifest["hashes"]["prompt_sha256"] = sha256_text(
        build_task_rubric_prompt(request)
    )
    write_canonical_json(task_manifest_path, task_manifest)

    root_manifest_path = output / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text())
    root_manifest["tasks"][task_id]["task_manifest_sha256"] = sha256_file(
        task_manifest_path
    )
    write_canonical_json(root_manifest_path, root_manifest)


def test_compiler_retries_with_only_previous_validation_errors(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    task_dir = make_task(tasks_dir)
    response = valid_rubric(build_task_snapshot(task_dir))
    compiler, rewriter, output, _ = make_compiler(
        tmp_path,
        responses=["not JSON", response],
    )

    assert compiler.run() == 0
    assert len(rewriter.requests) == 2
    assert rewriter.requests[0].previous_errors == ()
    assert rewriter.requests[1].previous_errors
    assert "JSON" in " ".join(rewriter.requests[1].previous_errors)
    assert set(asdict(rewriter.requests[1])) == {
        "schema_version",
        "prompt_version",
        "task_snapshot",
        "previous_errors",
    }

    attempts = output / "tasks" / "da-1-1" / "attempts"
    assert (attempts / "attempt-1" / "request.json").is_file()
    assert (attempts / "attempt-1" / "response.txt").read_text() == "not JSON"
    assert json.loads((attempts / "attempt-1" / "errors.json").read_text())
    assert json.loads((attempts / "attempt-2" / "errors.json").read_text()) == []
    task_manifest = json.loads(
        (output / "tasks" / "da-1-1" / "manifest.json").read_text()
    )
    assert task_manifest["hashes"]["prompt_sha256"] == sha256_text(
        build_task_rubric_prompt(rewriter.requests[-1])
    )
    assert resolve_rubric_bundle(output, "da-1-1").task_id == "da-1-1"


def test_compiler_request_is_runtime_blind(tmp_path: Path) -> None:
    compiler, rewriter, _, _ = make_compiler(tmp_path)

    assert compiler.run() == 0
    request = canonical_json(asdict(rewriter.requests[0]))
    for forbidden in (
        "trajectory",
        "trace.md",
        "answer.txt",
        "condition_id",
        "search_history",
    ):
        assert forbidden not in request


def test_exhausted_retries_leave_audit_artifacts_without_a_seal(
    tmp_path: Path,
) -> None:
    compiler, rewriter, output, _ = make_compiler(
        tmp_path,
        responses=["not JSON", "still not JSON"],
        max_retries=1,
    )

    assert compiler.run() == 1
    assert len(rewriter.requests) == 2
    assert output.is_dir()
    assert not (output / "manifest.json").exists()
    assert not (output / "tasks" / "da-1-1" / "manifest.json").exists()
    assert (output / "failure.json").is_file()
    assert (output / "tasks" / "da-1-1" / "attempts" / "attempt-2" / "errors.json").is_file()
    with pytest.raises(RubricBundleError):
        resolve_rubric_bundle(output, "da-1-1")


def test_partial_batch_failure_records_successes_and_failures_without_seal(
    tmp_path: Path,
) -> None:
    output = compile_partial_fixture(tmp_path)
    assert not (output / "manifest.json").exists()
    incomplete = json.loads((output / "incomplete-manifest.json").read_text())
    assert incomplete["status"] == "incomplete"
    assert incomplete["successful_task_ids"] == ["da-1-1"]
    assert list(incomplete["failures"]) == ["da-2-1"]
    assert len(incomplete["rubric_set_id"]) == 64
    successful = incomplete["tasks"]["da-1-1"]
    assert set(successful) == {
        "input_sha256",
        "rubric_id",
        "rubric_sha256",
        "snapshot_sha256",
        "task_manifest_path",
        "task_manifest_sha256",
    }
    task_manifest_path = output / successful["task_manifest_path"]
    assert task_manifest_path.is_file()
    assert sha256_file(task_manifest_path) == successful["task_manifest_sha256"]
    task_manifest = json.loads(task_manifest_path.read_text())
    assert task_manifest["rubric_set_id"] == incomplete["rubric_set_id"]
    assert task_manifest["rubric_id"] == successful["rubric_id"]
    assert (output / "tasks" / "da-2-1" / "attempts" / "attempt-1").is_dir()


def test_incomplete_manifest_detects_successful_task_manifest_tampering(
    tmp_path: Path,
) -> None:
    output = compile_partial_fixture(tmp_path)
    incomplete = json.loads((output / "incomplete-manifest.json").read_text())
    successful = incomplete["tasks"]["da-1-1"]
    task_manifest_path = output / successful["task_manifest_path"]

    task_manifest_path.write_text("tampered", encoding="utf-8")

    assert sha256_file(task_manifest_path) != successful["task_manifest_sha256"]


def test_successful_bundle_records_provenance_and_resolves(tmp_path: Path) -> None:
    output = compile_fixture(tmp_path)

    bundle = resolve_rubric_bundle(output, "da-1-1")
    root_manifest = json.loads((output / "manifest.json").read_text())
    task_manifest = json.loads(bundle.task_manifest_path.read_text())

    assert root_manifest["status"] == "sealed"
    assert bundle.rubric_set_id == root_manifest["rubric_set_id"]
    assert bundle.rubric_id == bundle.rubric_sha256
    assert bundle.rubric_json_path.name == "rubric.json"
    assert bundle.rendered_path.name == "process_rubric.txt"
    assert bundle.task_manifest_path.name == "manifest.json"
    assert task_manifest["status"] == "valid"
    assert task_manifest["task_id"] == "da-1-1"
    assert task_manifest["rubric_id"] == bundle.rubric_id
    assert task_manifest["snapshot"]["input_hashes"]
    for required_hash in (
        "snapshot_sha256",
        "input_sha256",
        "model_sha256",
        "temperature_sha256",
        "prompt_sha256",
        "raw_response_sha256",
        "structured_rubric_sha256",
        "rendered_rubric_sha256",
    ):
        assert len(task_manifest["hashes"][required_hash]) == 64
    assert set(task_manifest["artifacts"]) >= {
        "rubric.json",
        "process_rubric.txt",
        "raw_response.txt",
        "attempts/attempt-1/request.json",
        "attempts/attempt-1/response.txt",
        "attempts/attempt-1/errors.json",
    }


def test_exact_resume_does_not_call_rewriter(tmp_path: Path) -> None:
    output = compile_fixture(tmp_path)
    compiler, rewriter, resumed_output, _ = make_compiler(
        tmp_path,
        output_name=output.name,
        resume=True,
    )

    assert resumed_output == output
    assert compiler.run() == 0
    assert rewriter.requests == []


@pytest.mark.parametrize("change", ("input", "config"))
def test_changed_input_or_config_does_not_resume(
    tmp_path: Path,
    change: str,
) -> None:
    output = compile_fixture(tmp_path)
    compiler, rewriter, _, task_dir = make_compiler(
        tmp_path,
        output_name=output.name,
        resume=True,
    )
    if change == "input":
        (task_dir / "instruction.md").write_text(
            (task_dir / "instruction.md").read_text() + "\nUse a second comparison.\n",
            encoding="utf-8",
        )
    else:
        compiler.config = replace(compiler.config, model="gemini-changed")

    assert compiler.run() == 1
    assert rewriter.requests == []
    assert resolve_rubric_bundle(output, "da-1-1").task_id == "da-1-1"


def test_existing_sealed_bundle_cannot_be_overwritten(tmp_path: Path) -> None:
    output = compile_fixture(tmp_path)
    manifest_before = (output / "manifest.json").read_bytes()
    compiler, rewriter, _, _ = make_compiler(tmp_path, output_name=output.name)

    assert compiler.run() == 1
    assert rewriter.requests == []
    assert (output / "manifest.json").read_bytes() == manifest_before


def test_publication_lock_prevents_replacing_concurrently_occupied_destination(
    tmp_path: Path,
) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    (temporary / "payload.txt").write_text("candidate", encoding="utf-8")
    output = tmp_path / "sealed"
    lock_path = tmp_path / ".sealed.lock"
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()

    with lock_path.open("a+", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        process = context.Process(
            target=publish_in_subprocess,
            args=(temporary, output, result_queue),
        )
        process.start()
        assert result_queue.get(timeout=5) == ("ready", "")
        process.join(timeout=0.5)
        blocked_on_lock = process.is_alive()
        if blocked_on_lock:
            output.mkdir()
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)

    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)

    assert blocked_on_lock
    assert result_queue.get(timeout=1)[0] == "RubricBundleError"
    assert output.is_dir()
    assert list(output.iterdir()) == []
    assert (temporary / "payload.txt").read_text() == "candidate"


def test_identical_content_has_stable_bundle_ids(tmp_path: Path) -> None:
    first = compile_fixture(tmp_path, output_name="first-set")
    second = compile_fixture(tmp_path, output_name="second-set")

    first_bundle = resolve_rubric_bundle(first, "da-1-1")
    second_bundle = resolve_rubric_bundle(second, "da-1-1")
    assert first_bundle.rubric_id == second_bundle.rubric_id
    assert first_bundle.rubric_set_id == second_bundle.rubric_set_id


def test_bundle_tampering_is_detected(tmp_path: Path) -> None:
    output = compile_fixture(tmp_path)
    bundle = resolve_rubric_bundle(output, "da-1-1")
    bundle.rendered_path.write_text("tampered", encoding="utf-8")

    with pytest.raises(RubricBundleError):
        resolve_rubric_bundle(output, "da-1-1")


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-request-field",
        "wrong-retry-version",
        "broken-previous-errors",
        "noncontiguous-attempt",
    ),
)
def test_resolution_validates_the_complete_retry_chain(
    tmp_path: Path,
    mutation: str,
) -> None:
    output = compile_retry_fixture(tmp_path)
    attempts = output / "tasks" / "da-1-1" / "attempts"
    final_request_path = attempts / "attempt-2" / "request.json"
    final_request = json.loads(final_request_path.read_text())
    if mutation == "extra-request-field":
        final_request["unexpected"] = "not closed"
        write_canonical_json(final_request_path, final_request)
    elif mutation == "wrong-retry-version":
        final_request["prompt_version"] = "wrong-version"
        write_canonical_json(final_request_path, final_request)
    elif mutation == "broken-previous-errors":
        final_request["previous_errors"] = ["unrelated error"]
        write_canonical_json(final_request_path, final_request)
    else:
        (attempts / "attempt-2").rename(attempts / "attempt-3")
    reseal_task_after_attempt_mutation(output, "da-1-1")

    with pytest.raises(RubricBundleError):
        resolve_rubric_bundle(output, "da-1-1")


def test_resolution_rejects_nonmember_and_unlisted_artifacts(tmp_path: Path) -> None:
    output = compile_fixture(tmp_path)

    with pytest.raises(RubricBundleError):
        resolve_rubric_bundle(output, "../da-1-1")

    (output / "tasks" / "da-1-1" / "unlisted.txt").write_text(
        "not sealed",
        encoding="utf-8",
    )
    with pytest.raises(RubricBundleError):
        resolve_rubric_bundle(output, "da-1-1")


def test_artifact_path_rejects_parent_symlink_escape(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    nested = task_dir / "nested"
    outside = tmp_path / "outside"
    nested.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    (nested / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RubricBundleError):
        compiler_module._artifact_path(task_dir, "nested/link/secret.txt")


def test_missing_task_manifest_raises_bundle_error(tmp_path: Path) -> None:
    output = compile_fixture(tmp_path)
    (output / "tasks" / "da-1-1" / "manifest.json").unlink()

    with pytest.raises(RubricBundleError):
        resolve_rubric_bundle(output, "da-1-1")


def test_gemini_adapter_prompt_contains_closed_schema_and_quality_requirements(
    tmp_path: Path,
) -> None:
    snapshot = build_task_snapshot(make_task(tmp_path / "tasks"))
    request = TaskRubricRequest(
        schema_version=1,
        prompt_version="task-process-rubric-v1",
        task_snapshot=snapshot.to_dict(),
        previous_errors=("criteria must be non-empty",),
    )
    adapter = GeminiTaskRubricRewriter(
        model="gemini-3.5-flash",
        api_key_env="TEST_KEY",
        temperature=0.7,
    )

    prompt = adapter.build_prompt(request)
    assert prompt == build_task_rubric_prompt(request)
    assert '"additionalProperties":false' in prompt
    assert '"required_evidence"' in prompt
    for requirement in (
        "partial-credit",
        "observable evidence",
        "anti-evidence",
        "verification",
        "acceptable alternatives",
    ):
        assert requirement in prompt
    for prohibition in (
        "do not reward verbosity",
        "rubric quotation",
        "judge-directed language",
        "claimed-but-unexecuted work",
        "condition IDs",
        "candidate IDs",
        "search history",
        "prior scores",
    ):
        assert prohibition.lower() in prompt.lower()
    assert "criteria must be non-empty" in prompt
    assert adapter.client.request_body("prompt")["generationConfig"]["temperature"] == 0.7


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("task_ids", ()),
        ("max_retries", -1),
        ("max_concurrency", 0),
        ("temperature", float("nan")),
    ),
)
def test_invalid_compiler_config_is_rejected(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    values = {
        "tasks_dir": tmp_path / "tasks",
        "task_ids": ("da-1-1",),
        "output_dir": tmp_path / "output",
        field: value,
    }
    with pytest.raises(ValueError, match=field):
        TaskRubricCompilerConfig(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("overlap", ("output-inside-tasks", "tasks-inside-output"))
def test_compiler_config_rejects_overlapping_input_and_output_roots(
    tmp_path: Path,
    overlap: str,
) -> None:
    if overlap == "output-inside-tasks":
        tasks_dir = tmp_path / "tasks"
        output_dir = tasks_dir / "rubric-set"
    else:
        output_dir = tmp_path / "rubric-set"
        tasks_dir = output_dir / "tasks"

    with pytest.raises(ValueError, match="output_dir"):
        TaskRubricCompilerConfig(
            tasks_dir=tasks_dir,
            task_ids=("da-1-1",),
            output_dir=output_dir,
        )


def test_cli_requires_explicit_tasks_and_output() -> None:
    args = build_parser().parse_args([
        "task-process-rubrics",
        "--task",
        "da-19-1",
        "--output-dir",
        "runs/biomnibench-rubrics/pilot",
    ])

    assert args.tasks == ["da-19-1"]
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "task-process-rubrics",
            "--output-dir",
            "out",
        ])
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "task-process-rubrics",
            "--task",
            "da-19-1",
        ])


def test_cli_maps_task_compiler_options_to_config() -> None:
    args = build_parser().parse_args([
        "task-process-rubrics",
        "--task",
        "da-19-1",
        "--task",
        "da-26-4",
        "--output-dir",
        "runs/biomnibench-rubrics/pilot",
        "--tasks-dir",
        "data/biomnibench-da",
        "--model",
        "gemini-test",
        "--api-key-env",
        "GOOGLE_API_KEY",
        "--max-retries",
        "4",
        "--max-concurrency",
        "6",
        "--resume",
    ])

    config = TaskRubricCompilerConfig.from_namespace(args)

    assert config.tasks_dir == resolve_project_path("data/biomnibench-da")
    assert config.task_ids == ("da-19-1", "da-26-4")
    assert config.output_dir == resolve_project_path(
        "runs/biomnibench-rubrics/pilot"
    )
    assert config.model == "gemini-test"
    assert config.api_key_env == "GOOGLE_API_KEY"
    assert config.max_retries == 4
    assert config.max_concurrency == 6
    assert config.resume is True


def test_cli_config_clamps_retry_and_concurrency_bounds() -> None:
    args = build_parser().parse_args([
        "task-process-rubrics",
        "--task",
        "da-19-1",
        "--output-dir",
        "runs/biomnibench-rubrics/pilot",
        "--max-retries",
        "-3",
        "--max-concurrency",
        "0",
    ])

    config = TaskRubricCompilerConfig.from_namespace(args)

    assert config.max_retries == 0
    assert config.max_concurrency == 1


def test_retrospective_process_rubric_help_is_non_canonical(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["process-rubrics", "--help"])
    help_text = capsys.readouterr().out

    assert exc_info.value.code == 0
    assert "trajectory-informed retrospective" in help_text
    assert "not canonical" in help_text
    assert "trajectory-informed retrospective" in process_rubrics_module.__doc__
    assert "not canonical" in process_rubrics_module.__doc__


def test_main_runs_task_process_rubric_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeCompiler:
        def __init__(self, config: TaskRubricCompilerConfig) -> None:
            captured["config"] = config

        def run(self) -> int:
            return 17

    monkeypatch.setattr(
        cli_module,
        "TaskProcessRubricCompiler",
        FakeCompiler,
        raising=False,
    )

    exit_code = cli_module.main([
        "task-process-rubrics",
        "--task",
        "da-19-1",
        "--output-dir",
        "runs/biomnibench-rubrics/pilot",
    ])

    assert exit_code == 17
    config = captured["config"]
    assert isinstance(config, TaskRubricCompilerConfig)
    assert config.task_ids == ("da-19-1",)


def test_package_exports_intentional_task_rubric_interfaces() -> None:
    expected_by_module = {
        task_rubrics_module: (
            "SchemaSnapshotLimits",
            "DataFileSnapshot",
            "TaskAnchor",
            "TaskSnapshot",
            "RubricLevel",
            "RubricCriterion",
            "TaskProcessRubric",
            "build_task_snapshot",
            "canonical_json",
            "sha256_text",
            "parse_task_process_rubric",
            "validate_task_process_rubric",
            "render_task_process_rubric",
        ),
        compiler_module: (
            "TaskRubricCompilerConfig",
            "TaskRubricRequest",
            "TaskRubricRewriter",
            "GeminiTaskRubricRewriter",
            "TaskProcessRubricCompiler",
            "ResolvedRubricBundle",
            "resolve_rubric_bundle",
        ),
        cli_module: ("run_task_process_rubrics",),
    }

    for module, names in expected_by_module.items():
        for name in names:
            assert getattr(biomnibench, name) is getattr(module, name)
            assert name in biomnibench.__all__
