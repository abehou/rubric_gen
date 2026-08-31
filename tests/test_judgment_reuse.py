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
    exact_judgment_request,
    load_judgment_copy,
    persist_judgment_copy,
)


def _identity(rubric_sha256: str) -> dict[str, object]:
    value = {
        "scoring_implementation_sha256": "1" * 64,
        "effective_judge_model": "judge-model",
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
                "raw_report": {"score": 43.0},
            },
        },
        "usage.json": {"call": {"response_id": "one-provider-result"}},
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
    assert json.loads(first.evaluation_path.read_text())[
        "paperbench_structured"
    ]["raw_report"] == {"score": 43.0}

    fixed_copy = persist_judgment_copy(
        experiment_dir=tmp_path / "fixed",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        request=request,
        source=first,
    )
    adaptive_copy = persist_judgment_copy(
        experiment_dir=tmp_path / "adaptive",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        request=request,
        source=second,
    )
    assert fixed_copy.evaluation_path != adaptive_copy.evaluation_path
    assert (
        fixed_copy.evaluation_path.read_bytes()
        == adaptive_copy.evaluation_path.read_bytes()
    )
    assert load_judgment_copy(
        experiment_dir=tmp_path / "adaptive",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        expected_request=request,
    ) == adaptive_copy


def test_local_and_canonical_artifact_tampering_fail_closed(tmp_path: Path) -> None:
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
    local = persist_judgment_copy(
        experiment_dir=tmp_path / "fixed",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        request=request,
        source=reused,
    )
    local.evaluation_path.write_text("{}")
    with pytest.raises(RuntimeError, match="score validation changed"):
        load_judgment_copy(
            experiment_dir=tmp_path / "fixed",
            submission_id="s000",
            rubric_sha256=rubric_sha256,
            expected_request=request,
        )
    evaluation = reused.evaluation_path
    evaluation.write_text("{}")
    with pytest.raises(RuntimeError, match="provenance"):
        store.resolve(
            request=request,
            producer={
                "assignment_id": "fixed",
                "condition_id": "fixed",
                "replicate": 1,
                "submission_id": "s000",
                "rubric_sha256": rubric_sha256,
                "judge_attempt_id": "1" * 32,
            },
            generate=lambda: pytest.fail("tampered cache dispatched a judgment"),
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
    assert (
        results[0].score_validation_path.parent.name
        != results[1].score_validation_path.parent.name
    )


def test_local_copy_cannot_validate_as_another_request(
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
    persist_judgment_copy(
        experiment_dir=tmp_path / "condition-1",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        request=requests[0],
        source=reused[0],
    )
    with pytest.raises(RuntimeError, match="score validation changed"):
        load_judgment_copy(
            experiment_dir=tmp_path / "condition-1",
            submission_id="s000",
            rubric_sha256=rubric_sha256,
            expected_request=requests[1],
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

    assert not any(store.entries.iterdir())

    result = store.resolve(
        request=request,
        producer=producer,
        generate=lambda: _artifacts(
            tmp_path / "complete-output", request=request
        ),
    )
    assert result.score_validation_path.parent.parent == store.entries


def test_canonical_judgment_can_resume_before_local_copy(
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
    local = persist_judgment_copy(
        experiment_dir=tmp_path / "fixed",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        request=request,
        source=second,
    )

    assert second == first
    assert load_judgment_copy(
        experiment_dir=tmp_path / "fixed",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        expected_request=request,
    ) == local


def test_symlinked_local_and_canonical_entries_fail_closed(tmp_path: Path) -> None:
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
    local = persist_judgment_copy(
        experiment_dir=tmp_path / "fixed",
        submission_id="s000",
        rubric_sha256=rubric_sha256,
        request=request,
        source=reused,
    )
    local_root = local.score_validation_path.parent
    local_target = local_root.with_name(local_root.name + ".target")
    local_root.rename(local_target)
    local_root.symlink_to(local_target.name, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        load_judgment_copy(
            experiment_dir=tmp_path / "fixed",
            submission_id="s000",
            rubric_sha256=rubric_sha256,
            expected_request=request,
        )

    entry = reused.score_validation_path.parent
    entry_target = entry.with_name(entry.name + ".target")
    entry.rename(entry_target)
    entry.symlink_to(entry_target.name, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        store.resolve(
            request=request,
            producer={
                "assignment_id": "fixed",
                "condition_id": "fixed",
                "replicate": 1,
                "submission_id": "s000",
                "rubric_sha256": rubric_sha256,
                "judge_attempt_id": "1" * 32,
            },
            generate=lambda: pytest.fail("symlinked cache dispatched a judgment"),
        )
