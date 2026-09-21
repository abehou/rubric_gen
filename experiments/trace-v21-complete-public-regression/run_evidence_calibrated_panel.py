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
    EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT,
)
from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    deterministic_grading_seed,
)
from rubric_gen.submission_revision.judging.models import (
    grading_engine_for_benchmark,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / "diagnostics/heldout-judge-failure-analysis/saved-case-evidence.json"
)
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/evidence-calibrated-panel"
)
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
WORKERS = 6
BENCHMARK = SubmissionBenchmarkId.BIOMNIBENCH_DA


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
        rubric_text = str(evidence["rubrics"][task_id]["neutral"]["0"])
        artifact_evidence = case["artifact_evidence"]
        review_text = str(artifact_evidence["workspace_review"])
        answer_text = str(artifact_evidence["final_answer"])
        for model in MODELS:
            control = [
                row
                for row in case["uniform_neutral"]
                if row["variant"] == 0 and row["model"] == model
            ]
            if len(control) != 1:
                raise RuntimeError(
                    f"expected one saved neutral control for {case['assignment_id']} "
                    f"{model}"
                )
            identity = {
                "policy": EVIDENCE_CALIBRATED_POLICY_ID,
                "system_prompt_sha256": sha256_text(
                    EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT
                ),
                "assignment_id": case["assignment_id"],
                "task_id": task_id,
                "role": case["role"],
                "arm": case["arm"],
                "replicate": case["replicate"],
                "model": model,
                "rubric_variant": 0,
                "rubric_sha256": sha256_text(rubric_text),
                "review_sha256": sha256_text(review_text),
                "answer_sha256": sha256_text(answer_text),
                "control_score": control[0]["score"],
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
            elif saved_attempt.get("failure") not in {
                "transient_provider",
                "transient_connection",
                "invalid_response",
            }:
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
            if category not in {
                "transient_provider",
                "transient_connection",
                "invalid_response",
            }:
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
        control = float(identity["control_score"])
        rows.append(
            {
                **identity,
                "evidence_calibrated_score": score,
                "score_change": score - control,
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
        "policy": EVIDENCE_CALIBRATED_POLICY_ID,
        "system_prompt_sha256": sha256_text(
            EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT
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
    if len(planned) != len(evidence["cases"]) * len(MODELS):
        raise RuntimeError("evidence-calibrated panel scope changed")

    rubric_judge.RUBRIC_SCORE_SYSTEM_PROMPT = (
        EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT
    )
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
