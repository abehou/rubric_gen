from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.artifacts import sha256_file
from rubric_gen.submission_revision.judge import (
    SCORING_IDENTITY_KEYS,
    JudgeArtifacts,
)
from rubric_gen.submission_revision.judgment_reuse import (
    ExactJudgmentReuseStore,
    ExactSimulatorReuseStore,
    exact_judgment_request,
    exact_simulator_request,
)


def _identity(rubric_sha256: str) -> dict[str, object]:
    value = {
        "judge_source_sha256": "1" * 64,
        "judge_runner_sha256": "2" * 64,
        "scorer_module_sha256": "3" * 64,
        "effective_judge_model": "judge-model",
        "judge_api_base": None,
        "benchmark": "paperbench-code-dev",
        "grading_engine": "paperbench-structured",
        "review_mode": "workspace",
        "max_review_chars": None,
        "rubric_source": "rubric-path",
        "rubric_set_id": None,
        "rubric_id": None,
        "structured_rubric_sha256": None,
        "rendered_rubric_sha256": rubric_sha256,
        "manifest_sha256": None,
    }
    assert set(value) == set(SCORING_IDENTITY_KEYS)
    return value


def _artifacts(
    root: Path,
    *,
    request: dict[str, object],
    review_text: str = "same review",
    answer_text: str = "same answer",
) -> JudgeArtifacts:
    root.mkdir(parents=True)
    payloads = {
        "reward.json": {"score": 43.0},
        "evaluation.json": {
            "total_score": 43.0,
            "paperbench_structured": {
                "raw_reports": [
                    {"repeat": repeat_index} for repeat_index in range(1, 6)
                ],
                "dispersion": {"min_score": 43, "max_score": 64},
            },
        },
        "usage.json": {"calls": [{"response_id": "one-provider-result"}]},
    }
    for name, value in payloads.items():
        (root / name).write_text(json.dumps(value))
    (root / "judge_input_trace.md").write_text(review_text)
    (root / "judge_input_answer.txt").write_text(answer_text)
    identity = request["scoring_identity"]
    assert isinstance(identity, dict)
    validation = {
        **identity,
        "task": request["task_id"],
        "review_input_sha256": request["review_text_sha256"],
        "answer_input_sha256": request["answer_text_sha256"],
        "reward_sha256": sha256_file(root / "reward.json"),
        "evaluation_sha256": sha256_file(root / "evaluation.json"),
        "usage_sha256": sha256_file(root / "usage.json"),
        "score": 43.0,
    }
    (root / "score_validation.json").write_text(json.dumps(validation))
    return JudgeArtifacts(
        root / "score_validation.json",
        root / "evaluation.json",
    )


def test_exact_request_reuses_one_canonical_artifact_set_across_assignments(
    tmp_path: Path,
) -> None:
    rubric_sha256 = sha256_text("rubric")
    request = exact_judgment_request(
        task_id="task-a",
        replicate=1,
        rubric_sha256=rubric_sha256,
        review_text="same review",
        answer_text="same answer",
        scoring_identity=_identity(rubric_sha256),
    )
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    calls = 0

    def generate() -> JudgeArtifacts:
        nonlocal calls
        calls += 1
        return _artifacts(tmp_path / "provider-output", request=request)

    first = store.resolve(
        request=request,
        producer={
            "assignment_id": "fixed",
            "condition_id": "fixed",
            "replicate": 1,
            "submission_id": "s000",
            "rubric_sha256": rubric_sha256,
            "judge_attempt_id": "1" * 32,
        },
        generate=generate,
    )
    second = store.resolve(
        request=request,
        producer={
            "assignment_id": "adaptive",
            "condition_id": "adaptive",
            "replicate": 1,
            "submission_id": "s000",
            "rubric_sha256": rubric_sha256,
            "judge_attempt_id": "2" * 32,
        },
        generate=generate,
    )
    assert calls == 1
    assert first == second
    assert json.loads(first.artifacts.evaluation_path.read_text())[
        "paperbench_structured"
    ]["dispersion"] == {"min_score": 43, "max_score": 64}

    fixed_alias = store.persist_alias(
        experiment_dir=tmp_path / "fixed",
        assignment_id="fixed",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        reused=first,
    )
    adaptive_alias = store.persist_alias(
        experiment_dir=tmp_path / "adaptive",
        assignment_id="adaptive",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        reused=second,
    )
    assert json.loads(fixed_alias.read_text())["request_sha256"] == (
        json.loads(adaptive_alias.read_text())["request_sha256"]
    )
    assert store.validate_alias(
        adaptive_alias,
        assignment_id="adaptive",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        expected_request=request,
    ) == second


def test_alias_and_canonical_artifact_tampering_fail_closed(tmp_path: Path) -> None:
    rubric_sha256 = sha256_text("rubric")
    request = exact_judgment_request(
        task_id="task-a",
        replicate=1,
        rubric_sha256=rubric_sha256,
        review_text="same review",
        answer_text="same answer",
        scoring_identity=_identity(rubric_sha256),
    )
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    reused = store.resolve(
        request=request,
        producer={
            "assignment_id": "fixed",
            "condition_id": "fixed",
            "replicate": 1,
            "submission_id": "s000",
            "rubric_sha256": rubric_sha256,
            "judge_attempt_id": "1" * 32,
        },
        generate=lambda: _artifacts(tmp_path / "provider-output", request=request),
    )
    alias = store.persist_alias(
        experiment_dir=tmp_path / "fixed",
        assignment_id="fixed",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        reused=reused,
    )
    alias.chmod(0o600)
    value = json.loads(alias.read_text())
    value["request_sha256"] = "0" * 64
    alias.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="another request"):
        store.validate_alias(
            alias,
            assignment_id="fixed",
            replicate=1,
            submission_id="s000",
            rubric_sha256=rubric_sha256,
            expected_request=request,
        )
    alias.write_text(json.dumps({**value, "request_sha256": reused.request_sha256}))
    evaluation = reused.artifacts.evaluation_path
    evaluation.chmod(0o600)
    evaluation.write_text("{}")
    with pytest.raises(RuntimeError, match="provenance"):
        store.validate_alias(
            alias,
            assignment_id="fixed",
            replicate=1,
            submission_id="s000",
            rubric_sha256=rubric_sha256,
            expected_request=request,
        )


def test_simulated_user_pipeline_reuses_both_provider_generations(tmp_path: Path) -> None:
    simulator = {"implementation_sha256": "1" * 64, "model": "simulator"}
    bank_sha256 = sha256_text("bank")
    request = exact_simulator_request(
        experiment_id="study-a",
        task_id="task-a",
        replicate=1,
        instruction="Solve.",
        bank_sha256=bank_sha256,
        current_submission="same submission",
        simulator_identity=simulator,
    )
    store = ExactSimulatorReuseStore(tmp_path / "shared-simulator")
    calls = 0

    def generate() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "kind": "submission-simulated-user-feedback",
            "experiment_id": "study-a",
            "assignment_id": "fixed",
            "submission_id": "s000",
            "generation_round": 0,
            "bank_sha256": bank_sha256,
            "simulator": simulator,
            "attempt_count": 1,
            "output": {
                "referenced_criteria": ["member:criterion_1"],
                "concern_categories": ["clarity"],
                "comment": "Clarify the result.",
            },
            "selection_generation": {"response_id": "selection-one"},
            "comment_generation": {"response_id": "comment-one"},
        }

    producer = {
        "assignment_id": "fixed",
        "condition_id": "fixed",
        "replicate": 1,
        "submission_id": "s000",
        "generation_round": 0,
    }
    first = store.resolve(request=request, producer=producer, generate=generate)
    second = store.resolve(
        request=request,
        producer={**producer, "assignment_id": "adaptive", "condition_id": "adaptive"},
        generate=generate,
    )
    assert first == second
    assert calls == 1
    record = store.assignment_record(
        second,
        experiment_id="study-a",
        assignment_id="adaptive",
        submission_id="s000",
        generation_round=0,
        bank_sha256=bank_sha256,
        simulator_identity=simulator,
    )
    assert record["selection_generation"] == {"response_id": "selection-one"}
    alias = store.persist_alias(
        experiment_dir=tmp_path / "adaptive",
        assignment_id="adaptive",
        replicate=1,
        submission_id="s000",
        reused=second,
    )
    assert store.validate_alias(
        alias,
        assignment_id="adaptive",
        replicate=1,
        submission_id="s000",
        expected_request=request,
    ) == second

    alias_target = alias.with_suffix(".target")
    alias.rename(alias_target)
    alias.symlink_to(alias_target.name)
    with pytest.raises(RuntimeError, match="symbolic link"):
        store.validate_alias(
            alias,
            assignment_id="adaptive",
            replicate=1,
            submission_id="s000",
            expected_request=request,
        )

    entry = store.entries / second.request_sha256
    entry_target = store.entries / (second.request_sha256 + ".target")
    entry.rename(entry_target)
    entry.symlink_to(entry_target.name, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        store.load(
            request_sha256=second.request_sha256,
            expected_request=request,
        )


def test_replicates_have_distinct_canonical_judgments(tmp_path: Path) -> None:
    rubric_sha256 = sha256_text("rubric")
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    calls = 0
    results = []
    for replicate in (1, 2):
        request = exact_judgment_request(
            task_id="task-a",
            replicate=replicate,
            rubric_sha256=rubric_sha256,
            review_text="same review",
            answer_text="same answer",
            scoring_identity=_identity(rubric_sha256),
        )

        def generate(
            request: dict[str, object] = request,
            replicate: int = replicate,
        ) -> JudgeArtifacts:
            nonlocal calls
            calls += 1
            return _artifacts(
                tmp_path / f"provider-output-{replicate}",
                request=request,
            )

        results.append(store.resolve(
            request=request,
            producer={
                "assignment_id": f"rep-{replicate}",
                "condition_id": "fixed",
                "replicate": replicate,
                "submission_id": "s000",
                "rubric_sha256": rubric_sha256,
                "judge_attempt_id": str(replicate) * 32,
            },
            generate=generate,
        ))

    assert calls == 2
    assert results[0].request_sha256 != results[1].request_sha256


def test_valid_alias_cannot_redirect_to_another_valid_request(
    tmp_path: Path,
) -> None:
    rubric_sha256 = sha256_text("rubric")
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    requests = [
        exact_judgment_request(
            task_id="task-a",
            replicate=1,
            rubric_sha256=rubric_sha256,
            review_text="same review",
            answer_text=answer,
            scoring_identity=_identity(rubric_sha256),
        )
        for answer in ("same answer", "different answer")
    ]
    reused = []
    for index, request in enumerate(requests, start=1):
        reused.append(store.resolve(
            request=request,
            producer={
                "assignment_id": f"condition-{index}",
                "condition_id": f"condition-{index}",
                "replicate": 1,
                "submission_id": "s000",
                "rubric_sha256": rubric_sha256,
                "judge_attempt_id": str(index) * 32,
            },
            generate=lambda request=request, index=index: _artifacts(
                tmp_path / f"provider-output-{index}",
                request=request,
                answer_text=("same answer", "different answer")[index - 1],
            ),
        ))
    alias = store.persist_alias(
        experiment_dir=tmp_path / "condition-1",
        assignment_id="condition-1",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        reused=reused[0],
    )
    alias.chmod(0o600)
    value = json.loads(alias.read_text())
    value.update({
        "request_sha256": reused[1].request_sha256,
        "canonical_entry": reused[1].canonical_entry,
        "canonical_record_sha256": reused[1].canonical_record_sha256,
        "score_validation_sha256": sha256_file(
            reused[1].artifacts.score_validation_path
        ),
        "evaluation_sha256": sha256_file(reused[1].artifacts.evaluation_path),
    })
    alias.write_text(json.dumps(value))

    with pytest.raises(RuntimeError, match="another request"):
        store.validate_alias(
            alias,
            assignment_id="condition-1",
            replicate=1,
            submission_id="s000",
            rubric_sha256=rubric_sha256,
            expected_request=requests[0],
        )


@pytest.mark.parametrize(
    "forged_hash",
    ["../" + "0" * 64, "/tmp/" + "0" * 64],
)
def test_simulator_alias_rejects_path_traversal(
    tmp_path: Path,
    forged_hash: str,
) -> None:
    simulator = {"implementation_sha256": "1" * 64, "model": "simulator"}
    bank_sha256 = sha256_text("bank")
    request = exact_simulator_request(
        experiment_id="study-a",
        task_id="task-a",
        replicate=1,
        instruction="Solve.",
        bank_sha256=bank_sha256,
        current_submission="same submission",
        simulator_identity=simulator,
    )
    store = ExactSimulatorReuseStore(tmp_path / "shared-simulator")
    generated = {
        "kind": "submission-simulated-user-feedback",
        "experiment_id": "study-a",
        "assignment_id": "fixed",
        "submission_id": "s000",
        "generation_round": 0,
        "bank_sha256": bank_sha256,
        "simulator": simulator,
        "attempt_count": 1,
        "output": {"comment": "Clarify."},
        "selection_generation": {"response_id": "selection"},
        "comment_generation": {"response_id": "comment"},
    }
    reused = store.resolve(
        request=request,
        producer={
            "assignment_id": "fixed",
            "condition_id": "fixed",
            "replicate": 1,
            "submission_id": "s000",
            "generation_round": 0,
        },
        generate=lambda: generated,
    )
    alias = store.persist_alias(
        experiment_dir=tmp_path / "fixed",
        assignment_id="fixed",
        replicate=1,
        submission_id="s000",
        reused=reused,
    )
    alias.chmod(0o600)
    value = json.loads(alias.read_text())
    value["request_sha256"] = forged_hash
    alias.write_text(json.dumps(value))

    with pytest.raises(RuntimeError, match="invalid identity"):
        store.validate_alias(
            alias,
            assignment_id="fixed",
            replicate=1,
            submission_id="s000",
            expected_request=request,
        )


def test_concurrent_resolves_publish_one_judgment(tmp_path: Path) -> None:
    rubric_sha256 = sha256_text("rubric")
    request = exact_judgment_request(
        task_id="task-a",
        replicate=1,
        rubric_sha256=rubric_sha256,
        review_text="same review",
        answer_text="same answer",
        scoring_identity=_identity(rubric_sha256),
    )
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    count_lock = threading.Lock()
    calls = 0

    def generate() -> JudgeArtifacts:
        nonlocal calls
        with count_lock:
            calls += 1
        return _artifacts(tmp_path / "provider-output", request=request)

    def resolve(index: int):
        return store.resolve(
            request=request,
            producer={
                "assignment_id": f"condition-{index}",
                "condition_id": f"condition-{index}",
                "replicate": 1,
                "submission_id": "s000",
                "rubric_sha256": rubric_sha256,
                "judge_attempt_id": str(index) * 32,
            },
            generate=generate,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resolve, (1, 2)))

    assert calls == 1
    assert results[0] == results[1]


def test_failed_publish_leaves_no_partial_entry_and_can_retry(
    tmp_path: Path,
) -> None:
    rubric_sha256 = sha256_text("rubric")
    request = exact_judgment_request(
        task_id="task-a",
        replicate=1,
        rubric_sha256=rubric_sha256,
        review_text="same review",
        answer_text="same answer",
        scoring_identity=_identity(rubric_sha256),
    )
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    producer = {
        "assignment_id": "fixed",
        "condition_id": "fixed",
        "replicate": 1,
        "submission_id": "s000",
        "rubric_sha256": rubric_sha256,
        "judge_attempt_id": "1" * 32,
    }
    incomplete = _artifacts(tmp_path / "incomplete-output", request=request)
    (tmp_path / "incomplete-output" / "usage.json").unlink()

    with pytest.raises(RuntimeError, match="lacks canonical artifact"):
        store.resolve(
            request=request,
            producer=producer,
            generate=lambda: incomplete,
        )

    request_sha256 = store.request_sha256(request)
    assert not (store.entries / request_sha256).exists()
    assert not any(
        path.name.startswith(f".{request_sha256}.")
        for path in store.entries.iterdir()
    )

    result = store.resolve(
        request=request,
        producer=producer,
        generate=lambda: _artifacts(
            tmp_path / "complete-output", request=request
        ),
    )
    assert result.request_sha256 == request_sha256


def test_canonical_judgment_can_resume_before_alias_publication(
    tmp_path: Path,
) -> None:
    rubric_sha256 = sha256_text("rubric")
    request = exact_judgment_request(
        task_id="task-a",
        replicate=1,
        rubric_sha256=rubric_sha256,
        review_text="same review",
        answer_text="same answer",
        scoring_identity=_identity(rubric_sha256),
    )
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    producer = {
        "assignment_id": "fixed",
        "condition_id": "fixed",
        "replicate": 1,
        "submission_id": "s000",
        "rubric_sha256": rubric_sha256,
        "judge_attempt_id": "1" * 32,
    }
    first = store.resolve(
        request=request,
        producer=producer,
        generate=lambda: _artifacts(tmp_path / "provider-output", request=request),
    )
    second = store.resolve(
        request=request,
        producer=producer,
        generate=lambda: pytest.fail("resume dispatched another judgment"),
    )
    alias = store.persist_alias(
        experiment_dir=tmp_path / "fixed",
        assignment_id="fixed",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        reused=second,
    )

    assert second == first
    assert store.validate_alias(
        alias,
        assignment_id="fixed",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        expected_request=request,
    ) == first


def test_symlinked_alias_and_canonical_entry_fail_closed(tmp_path: Path) -> None:
    rubric_sha256 = sha256_text("rubric")
    request = exact_judgment_request(
        task_id="task-a",
        replicate=1,
        rubric_sha256=rubric_sha256,
        review_text="same review",
        answer_text="same answer",
        scoring_identity=_identity(rubric_sha256),
    )
    store = ExactJudgmentReuseStore(tmp_path / "shared")
    reused = store.resolve(
        request=request,
        producer={
            "assignment_id": "fixed",
            "condition_id": "fixed",
            "replicate": 1,
            "submission_id": "s000",
            "rubric_sha256": rubric_sha256,
            "judge_attempt_id": "1" * 32,
        },
        generate=lambda: _artifacts(tmp_path / "provider-output", request=request),
    )
    alias = store.persist_alias(
        experiment_dir=tmp_path / "fixed",
        assignment_id="fixed",
        replicate=1,
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        reused=reused,
    )
    alias_target = alias.with_suffix(".target")
    alias.rename(alias_target)
    alias.symlink_to(alias_target.name)
    with pytest.raises(RuntimeError, match="symbolic link"):
        store.validate_alias(
            alias,
            assignment_id="fixed",
            replicate=1,
            submission_id="s000",
            rubric_sha256=rubric_sha256,
            expected_request=request,
        )

    entry = store.entries / reused.request_sha256
    entry_target = store.entries / (reused.request_sha256 + ".target")
    entry.rename(entry_target)
    entry.symlink_to(entry_target.name, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        store.load(
            request_sha256=reused.request_sha256,
            expected_request=request,
        )


def test_concurrent_resolves_publish_one_simulator_result(
    tmp_path: Path,
) -> None:
    simulator = {"implementation_sha256": "1" * 64, "model": "simulator"}
    bank_sha256 = sha256_text("bank")
    request = exact_simulator_request(
        experiment_id="study-a",
        task_id="task-a",
        replicate=1,
        instruction="Solve.",
        bank_sha256=bank_sha256,
        current_submission="same submission",
        simulator_identity=simulator,
    )
    store = ExactSimulatorReuseStore(tmp_path / "shared-simulator")
    count_lock = threading.Lock()
    calls = 0

    def generate() -> dict[str, object]:
        nonlocal calls
        with count_lock:
            calls += 1
        return {
            "kind": "submission-simulated-user-feedback",
            "experiment_id": "study-a",
            "assignment_id": "fixed",
            "submission_id": "s000",
            "generation_round": 0,
            "bank_sha256": bank_sha256,
            "simulator": simulator,
            "attempt_count": 1,
            "output": {"comment": "Clarify."},
            "selection_generation": {"response_id": "selection"},
            "comment_generation": {"response_id": "comment"},
        }

    def resolve(index: int):
        return store.resolve(
            request=request,
            producer={
                "assignment_id": f"condition-{index}",
                "condition_id": f"condition-{index}",
                "replicate": 1,
                "submission_id": "s000",
                "generation_round": 0,
            },
            generate=generate,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resolve, (1, 2)))

    assert calls == 1
    assert results[0] == results[1]


def test_failed_simulator_publish_leaves_no_partial_entry_and_can_retry(
    tmp_path: Path,
) -> None:
    simulator = {"implementation_sha256": "1" * 64, "model": "simulator"}
    bank_sha256 = sha256_text("bank")
    request = exact_simulator_request(
        experiment_id="study-a",
        task_id="task-a",
        replicate=1,
        instruction="Solve.",
        bank_sha256=bank_sha256,
        current_submission="same submission",
        simulator_identity=simulator,
    )
    store = ExactSimulatorReuseStore(tmp_path / "shared-simulator")
    producer = {
        "assignment_id": "fixed",
        "condition_id": "fixed",
        "replicate": 1,
        "submission_id": "s000",
        "generation_round": 0,
    }
    incomplete = {
        "kind": "submission-simulated-user-feedback",
        "experiment_id": "study-a",
        "assignment_id": "fixed",
        "submission_id": "s000",
        "generation_round": 0,
        "bank_sha256": bank_sha256,
        "simulator": simulator,
        "attempt_count": 1,
        "output": {"comment": "Clarify."},
        "selection_generation": {"response_id": "selection"},
    }

    with pytest.raises(RuntimeError, match="simulated-user generator record"):
        store.resolve(
            request=request,
            producer=producer,
            generate=lambda: incomplete,
        )

    request_sha256 = store.request_sha256(request)
    assert not (store.entries / request_sha256).exists()
    assert not any(
        path.name.startswith(f".{request_sha256}.")
        for path in store.entries.iterdir()
    )

    complete = {
        **incomplete,
        "comment_generation": {"response_id": "comment"},
    }
    result = store.resolve(
        request=request,
        producer=producer,
        generate=lambda: complete,
    )
    assert result.request_sha256 == request_sha256
