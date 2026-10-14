"""Run one bounded, paired judge-policy panel over saved final artifacts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.base import SubmissionBenchmarkId
from rubric_gen.runtime.failures import failure_category, retry_after
from rubric_gen.submission_revision.evaluation import rubric_judge
from rubric_gen.submission_revision.evaluation.evidence_policy import (
    EVIDENCE_CALIBRATED_POLICY_ID,
    EVIDENCE_CALIBRATED_POLICY_V2_ID,
    EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT,
    EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT_V2,
)
from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    deterministic_grading_seed,
)
from rubric_gen.submission_revision.judging.models import (
    grading_engine_for_benchmark,
)


ROOT = Path(__file__).resolve().parents[2]
CASE_SCOPE = os.environ.get("EVIDENCE_CASE_SCOPE", "saved")
TASK_FILTER = os.environ.get("EVIDENCE_TASK_ID")
REPLICATE_FILTER = (
    int(os.environ["EVIDENCE_REPLICATE"])
    if os.environ.get("EVIDENCE_REPLICATE")
    else None
)
EVIDENCE_NAME = (
    "outlier4-evidence.json"
    if CASE_SCOPE == "outlier4"
    else f"original20-{TASK_FILTER}-rep{REPLICATE_FILTER:03d}-evidence.json"
    if CASE_SCOPE == "original20"
    and TASK_FILTER
    and REPLICATE_FILTER is not None
    else f"new20-remaining16-{TASK_FILTER}-rep{REPLICATE_FILTER:03d}-evidence.json"
    if CASE_SCOPE == "new20_remaining16"
    and TASK_FILTER
    and REPLICATE_FILTER is not None
    else f"new20-remaining16-{TASK_FILTER}-evidence.json"
    if CASE_SCOPE == "new20_remaining16" and TASK_FILTER
    else "new20-remaining16-evidence.json"
    if CASE_SCOPE == "new20_remaining16"
    else "saved-case-evidence.json"
)
EVIDENCE = Path(os.environ["EVIDENCE_INPUT_PATH"]) if os.environ.get(
    "EVIDENCE_INPUT_PATH"
) else ROOT / "diagnostics/heldout-judge-failure-analysis" / EVIDENCE_NAME
POLICY_VERSION = os.environ.get("EVIDENCE_POLICY_VERSION", "v1")
if POLICY_VERSION == "v1":
    POLICY_ID = EVIDENCE_CALIBRATED_POLICY_ID
    SYSTEM_PROMPT = EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT
elif POLICY_VERSION == "v2":
    POLICY_ID = EVIDENCE_CALIBRATED_POLICY_V2_ID
    SYSTEM_PROMPT = EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT_V2
else:
    raise RuntimeError(f"unknown evidence policy version: {POLICY_VERSION}")
RUN_BASE = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/"
    f"evidence-calibrated-panel-{CASE_SCOPE}-{POLICY_VERSION}"
)
RUN = RUN_BASE
if TASK_FILTER:
    RUN = RUN / TASK_FILTER
if REPLICATE_FILTER is not None:
    RUN = RUN / f"rep-{REPLICATE_FILTER:03d}"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
WORKERS = 6
BENCHMARK = SubmissionBenchmarkId.BIOMNIBENCH_DA
RETRYABLE_FAILURES = {
    "transient_provider",
    "transient_connection",
    "invalid_response",
}


def retryable_attempt(attempt: dict[str, object]) -> bool:
    if attempt.get("failure") in RETRYABLE_FAILURES:
        return True
    error = str(attempt.get("error", "")).lower()
    return "servers are currently overloaded" in error


def canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected an object: {path}")
    return value


def jobs(evidence: dict) -> tuple[dict[str, object], ...]:
    if evidence.get("models") != list(MODELS):
        raise RuntimeError("saved control models do not match the panel")
    rows = []
    for case in evidence["cases"]:
        task_id = str(case["task_id"])
        artifact_evidence = case["artifact_evidence"]
        review_text = str(artifact_evidence["workspace_review"])
        if POLICY_VERSION == "v2":
            review_text += (
                "\n\n# Sealed public execution and output evidence\n\n"
                + str(case["sealed_public_evidence"])
            )
        answer_text = str(artifact_evidence["final_answer"])
        variants = (
            range(5)
            if CASE_SCOPE in {"outlier4", "new20_remaining16", "original20"}
            else (0,)
        )
        for variant in variants:
            rubric_text = str(
                evidence["rubrics"][task_id]["neutral"][str(variant)]
            )
            for model in MODELS:
                control = [
                    row
                    for row in case.get("uniform_neutral", ())
                    if row["variant"] == variant and row["model"] == model
                ]
                if CASE_SCOPE != "original20" and len(control) != 1:
                    raise RuntimeError(
                        "expected one saved neutral control for "
                        f"{case['assignment_id']} variant {variant} {model}"
                    )
                identity = {
                    "policy": POLICY_ID,
                    "case_scope": CASE_SCOPE,
                    "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
                    "assignment_id": case["assignment_id"],
                    "task_id": task_id,
                    "role": case["role"],
                    "arm": case["arm"],
                    "replicate": case["replicate"],
                    "model": model,
                    "rubric_variant": variant,
                    "rubric_sha256": sha256_text(rubric_text),
                    "review_sha256": sha256_text(review_text),
                    "answer_sha256": sha256_text(answer_text),
                    "control_score": (
                        control[0]["score"] if control else None
                    ),
                }
                rows.append(
                    {
                        "key": hashlib.sha256(canonical(identity).encode()).hexdigest(),
                        "identity": identity,
                        "rubric_text": rubric_text,
                        "review_text": review_text,
                        "answer_text": answer_text,
                    }
                )
    return tuple(rows)


def run_job(job: dict[str, object]) -> dict[str, object]:
    identity = dict(job["identity"])
    key = str(job["key"])
    record_path = RUN / "records" / f"{key}.json"
    if record_path.is_file():
        saved = read(record_path)
        if saved.get("identity") != identity:
            raise RuntimeError("saved evidence-calibrated record identity changed")
        return saved

    rubric_text = str(job["rubric_text"])
    review_text = str(job["review_text"])
    answer_text = str(job["answer_text"])
    model = str(identity["model"])
    seed = deterministic_grading_seed(
        rubric_sha256=str(identity["rubric_sha256"]),
        review_sha256=str(identity["review_sha256"]),
        answer_sha256=str(identity["answer_sha256"]),
        requested_model=model,
        benchmark=BENCHMARK.value,
        assignment_identity=str(identity["task_id"]),
        grading_engine=grading_engine_for_benchmark(BENCHMARK).value,
        engine_release=str(rubric_judge.RUBRIC_SCORE_ENGINE_IDENTITY["engine"]),
    )
    attempts = RUN / "attempts" / key
    attempts.mkdir(parents=True, exist_ok=True)
    last_error: BaseException | None = None
    for attempt in range(1, rubric_judge.JUDGE_MAX_ATTEMPTS + 1):
        attempt_path = attempts / f"attempt-{attempt:03d}.json"
        generation_path = attempts / f"attempt-{attempt:03d}.response.json"
        if attempt_path.is_file():
            saved_attempt = read(attempt_path)
            if saved_attempt.get("identity") != identity:
                raise RuntimeError("saved evidence-calibrated attempt identity changed")
            if saved_attempt.get("status") == "completed":
                write_json_atomic(record_path, saved_attempt)
                return saved_attempt
            if generation_path.is_file() and saved_attempt.get("failure") is None:
                pass
            elif not retryable_attempt(saved_attempt):
                raise RuntimeError(
                    f"saved non-recoverable panel failure: {saved_attempt.get('error')}"
                )
            else:
                continue
        else:
            write_json_atomic(
                attempt_path,
                {"identity": identity, "attempt": attempt, "status": "started"},
            )
        token = rubric_judge._GENERATION_PATH.set(generation_path)
        started = time.monotonic()
        try:
            records = rubric_judge.grade_rubric_score(
                rubric_text=rubric_text,
                review_text=review_text,
                answer_text=answer_text,
                requested_model=model,
                seed=seed,
            )
        except Exception as exc:
            last_error = exc
            category = failure_category(exc)
            if isinstance(exc, rubric_judge.FullRubricJudgeError):
                category = "invalid_response"
            if "servers are currently overloaded" in str(exc).lower():
                category = "transient_provider"
            write_json_atomic(
                attempt_path,
                {
                    "identity": identity,
                    "attempt": attempt,
                    "status": "failed",
                    "failure": category,
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": time.monotonic() - started,
                },
            )
            if category not in RETRYABLE_FAILURES:
                raise
            if attempt < rubric_judge.JUDGE_MAX_ATTEMPTS:
                time.sleep(retry_after(exc, attempt))
        else:
            result = {
                "identity": identity,
                "attempt": attempt,
                "status": "completed",
                "elapsed_seconds": time.monotonic() - started,
                "records": asdict(records),
            }
            write_json_atomic(attempt_path, result)
            write_json_atomic(record_path, result)
            return result
        finally:
            rubric_judge._GENERATION_PATH.reset(token)
    raise RuntimeError(
        f"evidence-calibrated panel job exhausted retries: {last_error}"
    ) from last_error


def summarize(records: list[dict[str, object]]) -> dict[str, object]:
    rows = []
    for record in records:
        identity = record["identity"]
        score = float(record["records"]["score"])
        control_value = identity["control_score"]
        control = float(control_value) if control_value is not None else None
        rows.append(
            {
                **identity,
                "evidence_calibrated_score": score,
                "score_change": score - control if control is not None else None,
                "elapsed_seconds": record["elapsed_seconds"],
                "attempt": record["attempt"],
                "criteria": record["records"]["evaluation"]["criteria"],
                "usage": record["records"]["usage"],
            }
        )
    rows.sort(key=lambda row: (
        row["task_id"], row["arm"], row["replicate"], row["model"], row["role"]
    ))
    return {
        "kind": "evidence-calibrated-heldout-saved-case-panel",
        "case_scope": CASE_SCOPE,
        "task_filter": TASK_FILTER,
        "replicate_filter": REPLICATE_FILTER,
        "policy": POLICY_ID,
        "system_prompt_sha256": sha256_text(
            SYSTEM_PROMPT
        ),
        "models": list(MODELS),
        "workers": WORKERS,
        "rows": rows,
    }


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("evidence-calibrated panel must run on a Babel compute node")
    evidence = read(EVIDENCE)
    planned = jobs(evidence)
    variants_per_case = (
        5
        if CASE_SCOPE in {"outlier4", "new20_remaining16", "original20"}
        else 1
    )
    if len(planned) != len(evidence["cases"]) * len(MODELS) * variants_per_case:
        raise RuntimeError("evidence-calibrated panel scope changed")

    rubric_judge.RUBRIC_SCORE_SYSTEM_PROMPT = SYSTEM_PROMPT
    started = datetime.now(timezone.utc).isoformat()
    records = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        pending = {executor.submit(run_job, job): job for job in planned}
        for future in as_completed(pending):
            records.append(future.result())
            progress = summarize(records)
            progress.update(
                status="running",
                started_at=started,
                source_commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                completed=len(records),
                total=len(planned),
            )
            write_json_atomic(RUN / "progress.json", progress)
    completion = summarize(records)
    completion.update(
        status="completed",
        started_at=started,
        finished_at=datetime.now(timezone.utc).isoformat(),
        source_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        completed=len(records),
        total=len(planned),
    )
    write_json_atomic(RUN / "completion.json", completion)
    print(canonical({
        "status": completion["status"],
        "completed": completion["completed"],
        "total": completion["total"],
        "source_commit": completion["source_commit"],
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
