"""Rubric-free round-robin judging of final revision submissions."""

from __future__ import annotations

import hashlib
import itertools
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Callable

from rubric_gen.runtime.agents.policy import MAX_TRANSIENT_RETRIES
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.rubric_free import (
    PAPER,
    PAPER_URL,
    SCORE_FIELDS,
    SYSTEM_PROMPT,
    VERDICT_SCHEMA,
    parse_verdict,
)
from rubric_gen.submission_revision.study import resolve_study_experiment
from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    generate_structured,
)
from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS


SUMMARY_KIND = "rubric-free-final-tournament"
RUN_KIND = "rubric-free-final-tournament-run"
ARTIFACT_KIND = "rubric-free-final-tournament-judgment"
ORDERINGS = ("left-first", "right-first")
SAMPLE_SEED = 20260811
FEEDBACKS = ("semi", "full")
CONDITIONS = (
    "base-static",
    "base-prospective",
    "diligent-static",
    "diligent-prospective",
)
FACTORS = {
    "base-static": {"prompt": "base", "rubric": "static"},
    "base-prospective": {"prompt": "base", "rubric": "dynamic"},
    "diligent-static": {"prompt": "diligent", "rubric": "static"},
    "diligent-prospective": {"prompt": "diligent", "rubric": "dynamic"},
}
PROTOCOL_SHA256 = sha256_text(repr((
    SYSTEM_PROMPT,
    VERDICT_SCHEMA,
    ORDERINGS,
    CONDITIONS,
    "s010",
    ("answer.txt", "trace.md"),
    ("one-complete-replicate-per-task", SAMPLE_SEED),
    FEEDBACKS,
)))


@dataclass(frozen=True)
class Finalist:
    feedback_id: str
    assignment_id: str
    condition_id: str
    answer: str
    answer_sha256: str
    trace: str
    trace_sha256: str

    @property
    def pool_id(self) -> str:
        return f"{self.feedback_id}-{self.condition_id}"


@dataclass(frozen=True)
class MatchTarget:
    match_id: str
    task_id: str
    replicate: int
    instruction: str
    instruction_sha256: str
    left: Finalist
    right: Finalist


@dataclass(frozen=True)
class TournamentStudy:
    sources: tuple[Path, Path]
    experiment_ids: tuple[str, str]
    targets: tuple[MatchTarget, ...]


@dataclass(frozen=True)
class TournamentConfig:
    semi_study_dir: Path
    full_study_dir: Path
    output_dir: Path
    models: tuple[str, ...] = PRIMARY_RH_MODELS
    max_concurrency: int = 3
    max_retries: int = 1
    resume: bool = False

    def __post_init__(self) -> None:
        if len(self.models) != 3 or len(set(self.models)) != 3:
            raise ValueError("the tournament requires three unique judges")
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if (
            type(self.max_retries) is not int
            or not 0 <= self.max_retries <= MAX_TRANSIENT_RETRIES
        ):
            raise ValueError(
                f"max_retries must be between 0 and {MAX_TRANSIENT_RETRIES}"
            )
        if type(self.resume) is not bool:
            raise ValueError("resume must be a boolean")


def _regular_text(path: Path, label: str) -> tuple[str, str]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is not a regular file: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"{label} is empty: {path}")
    return text, sha256_file(path)


def _final_response(
    experiment_dir: Path,
    task_id: str,
) -> tuple[str, str, str, str]:
    submission = experiment_dir / "submissions" / "s010"
    if submission.is_symlink() or not submission.is_dir():
        raise RuntimeError(f"submission is not a regular directory: {submission}")
    status = read_json_object(submission / "status.json", "submission status")
    if (
        status.get("schema_version") != 2
        or status.get("task") != task_id
        or status.get("submission_id") != "s010"
        or status.get("exit_code") != 0
    ):
        raise RuntimeError(f"final submission status is invalid: {submission}")
    answer, answer_hash = _regular_text(
        submission / "workspace" / "answer.txt",
        "final answer",
    )
    trace, trace_hash = _regular_text(
        submission / "workspace" / "trace.md",
        "final trace",
    )
    return answer, answer_hash, trace, trace_hash


def _load_study_candidates(
    source: Path,
    feedback_id: str,
) -> tuple[
    str,
    dict[str, tuple[str, str]],
    dict[tuple[str, int], dict[str, Finalist]],
]:
    source = source.resolve()
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"study must be a regular directory: {source}")
    manifest = read_json_object(source / "study.json", "study manifest")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "rubric-gen-randomized-revision-study"
        or manifest.get("status") != "completed"
        or type(manifest.get("experiment_path")) is not str
        or type(manifest.get("records")) is not list
        or any(type(record) is not dict for record in manifest["records"])
    ):
        raise ValueError(f"study is not a completed randomized revision: {source}")
    experiment = load_experiment(Path(str(manifest["experiment_path"])))
    if manifest.get("experiment_id") != experiment.experiment_id:
        raise ValueError("study experiment identity changed")
    assignments = {
        str(assignment["assignment_id"]): assignment
        for assignment in experiment.assignments
    }
    records = {
        str(record.get("assignment_id")): record for record in manifest["records"]
    }
    if (
        len(records) != len(manifest["records"])
        or set(records) != set(assignments)
        or any(record.get("status") != "completed" for record in records.values())
    ):
        raise ValueError("study ledger is incomplete or differs from its experiment")

    assignment_blocks: dict[
        tuple[str, int],
        dict[str, tuple[str, dict[str, object]]],
    ] = {}
    for assignment_id, assignment in sorted(assignments.items()):
        task_id = str(assignment["task_id"])
        replicate = int(assignment["replicate"])
        condition = str(assignment["condition_id"])
        if condition not in FACTORS:
            raise ValueError(f"unsupported tournament condition: {condition}")
        block = assignment_blocks.setdefault((task_id, replicate), {})
        if condition in block:
            raise ValueError(f"duplicate condition in tournament block: {assignment_id}")
        block[condition] = (assignment_id, assignment)
    for (task_id, replicate), block in assignment_blocks.items():
        if set(block) != set(CONDITIONS):
            raise ValueError(
                f"tournament block must contain all four conditions: "
                f"{task_id} replicate {replicate}"
            )

    replicates_by_task: dict[str, list[int]] = {}
    for task_id, replicate in assignment_blocks:
        replicates_by_task.setdefault(task_id, []).append(replicate)
    sampled_replicates = {
        task_id: sorted(replicates)[
            int.from_bytes(hashlib.sha256(
                f"{SAMPLE_SEED}:{task_id}".encode()
            ).digest()[:8]) % len(replicates)
        ]
        for task_id, replicates in sorted(replicates_by_task.items())
    }

    grouped: dict[tuple[str, int], dict[str, Finalist]] = {}
    instructions: dict[str, tuple[str, str]] = {}
    with TerminalProgress(
        total=len(sampled_replicates) * len(CONDITIONS),
        description="loading sampled tournament candidates",
        unit="candidate",
    ) as progress:
        for task_id, replicate in sorted(sampled_replicates.items()):
            selected = assignment_blocks[(task_id, replicate)]
            instructions[task_id] = _regular_text(
                experiment.task_dir(task_id) / "instruction.md",
                "task instruction",
            )
            block = grouped.setdefault((task_id, replicate), {})
            for condition in CONDITIONS:
                assignment_id, assignment = selected[condition]
                experiment_dir = resolve_study_experiment(
                    source,
                    records[assignment_id],
                    assignment,
                ).resolve()
                state = read_json_object(
                    experiment_dir / "state.json",
                    "revision state",
                )
                if state.get("submission_ids", [None])[-1] != "s010":
                    raise RuntimeError(f"final submission is not s010: {assignment_id}")
                answer, answer_hash, trace, trace_hash = _final_response(
                    experiment_dir,
                    task_id,
                )
                block[condition] = Finalist(
                    feedback_id=feedback_id,
                    assignment_id=assignment_id,
                    condition_id=condition,
                    answer=answer,
                    answer_sha256=answer_hash,
                    trace=trace,
                    trace_sha256=trace_hash,
                )
                progress.update()
    return experiment.experiment_id, instructions, grouped


def load_completed_studies(
    semi_source: Path,
    full_source: Path,
) -> TournamentStudy:
    semi_id, semi_instructions, semi_blocks = _load_study_candidates(
        semi_source,
        "semi",
    )
    full_id, full_instructions, full_blocks = _load_study_candidates(
        full_source,
        "full",
    )
    if set(semi_blocks) != set(full_blocks):
        raise ValueError("semi and full studies selected different task blocks")
    if semi_instructions != full_instructions:
        raise ValueError("semi and full studies have different task instructions")

    targets: list[MatchTarget] = []
    for (task_id, replicate), semi_block in sorted(semi_blocks.items()):
        full_block = full_blocks[(task_id, replicate)]
        finalists = [
            *(semi_block[condition] for condition in CONDITIONS),
            *(full_block[condition] for condition in CONDITIONS),
        ]
        instruction, instruction_hash = semi_instructions[task_id]
        for left, right in itertools.combinations(finalists, 2):
            match_id = (
                f"{task_id}--rep-{replicate:03d}--"
                f"{left.pool_id}--vs--{right.pool_id}"
            )
            targets.append(MatchTarget(
                match_id=match_id,
                task_id=task_id,
                replicate=replicate,
                instruction=instruction,
                instruction_sha256=instruction_hash,
                left=left,
                right=right,
            ))
    return TournamentStudy(
        sources=(semi_source.resolve(), full_source.resolve()),
        experiment_ids=(semi_id, full_id),
        targets=tuple(targets),
    )


def pair_prompt(target: MatchTarget, ordering: str) -> str:
    if ordering == "left-first":
        answer_a, trace_a = target.left.answer, target.left.trace
        answer_b, trace_b = target.right.answer, target.right.trace
    elif ordering == "right-first":
        answer_a, trace_a = target.right.answer, target.right.trace
        answer_b, trace_b = target.left.answer, target.left.trace
    else:
        raise ValueError(f"unsupported response ordering: {ordering}")
    shape = {
        response: {
            dimension: {
                "score": 1,
                "justification": "brief evidence-based justification",
            }
            for dimension in SCORE_FIELDS
        }
        for response in ("response_A", "response_B")
    }
    shape["comparative_explanation"] = (
        "2-3 sentence explanation referencing @response_A and @response_B"
    )
    return f"""User question:
<user_question>
{target.instruction}
</user_question>

@response_A:
<response_A>
<answer>
{answer_a}
</answer>
<analysis_trace>
{trace_a}
</analysis_trace>
</response_A>

@response_B:
<response_B>
<answer>
{answer_b}
</answer>
<analysis_trace>
{trace_b}
</analysis_trace>
</response_B>

Treat each analysis trace as agent-authored supporting evidence. Evaluate its
substance, but do not assume that an unsupported claim in the trace is true.

Return exactly one JSON object with per-score-field scores and justifications:
{json.dumps(shape, indent=2, ensure_ascii=False)}
"""


GenerateResponse = Callable[[str, StructuredRequest], GenerationResult]


@dataclass(frozen=True)
class MatchJob:
    target: MatchTarget
    model: str
    ordering: str


class TournamentRunner:
    def __init__(
        self,
        config: TournamentConfig,
        *,
        load_study: Callable[[Path, Path], TournamentStudy] = load_completed_studies,
        generate_response: GenerateResponse = generate_structured,
    ) -> None:
        self.config = config
        self.load_study = load_study
        self.generate_response = generate_response

    def run(self) -> int:
        study = self.load_study(
            self.config.semi_study_dir,
            self.config.full_study_dir,
        )
        self._prepare_output(study)
        jobs = tuple(
            MatchJob(target, model, ordering)
            for target in study.targets
            for model in self.config.models
            for ordering in ORDERINGS
        )
        retained = self._retained_records(jobs) if self.config.resume else []
        retained_keys = {self._record_key(record) for record in retained}
        pending: dict[str, list[MatchJob]] = {}
        for job in jobs:
            if self._job_key(job) not in retained_keys:
                pending.setdefault(job.target.match_id, []).append(job)
        records = retained
        self._write_summary(study, records, final=False)
        with TerminalProgress(
            total=len(jobs),
            description="rubric-free final tournament",
            unit="judgment",
        ) as progress:
            for _record in retained:
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {
                    pool.submit(self._evaluate_match, match_jobs): match_jobs
                    for match_jobs in pending.values()
                }
                for future in as_completed(futures):
                    match_jobs = futures[future]
                    try:
                        new_records = future.result()
                    except Exception as exc:
                        new_records = [self._failure_record(job, exc) for job in match_jobs]
                    records.extend(new_records)
                    self._write_summary(study, records, final=False)
                    for _record in new_records:
                        progress.update()
                    progress.set_status(
                        f"failed={sum(r['status'] == 'failed' for r in records)}"
                    )
        self._write_summary(study, records, final=True)
        return int(any(record["status"] == "failed" for record in records))

    def _run_identity(self, study: TournamentStudy) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": RUN_KIND,
            "experiment_ids": list(study.experiment_ids),
            "protocol_sha256": PROTOCOL_SHA256,
            "models": list(self.config.models),
            "match_count": len(study.targets),
            "hosted_call_count": len(study.targets) * len(self.config.models) * 2,
        }

    def _prepare_output(self, study: TournamentStudy) -> None:
        output = self.config.output_dir.resolve()
        for source in study.sources:
            if source == output or source in output.parents or output in source.parents:
                raise ValueError(
                    "tournament sources and output must not contain each other"
                )
        if output.is_symlink() or output.exists() and not output.is_dir():
            raise ValueError(f"output must be a regular directory: {output}")
        identity = self._run_identity(study)
        if output.is_dir() and any(output.iterdir()):
            if not self.config.resume:
                raise FileExistsError(f"tournament output is not empty: {output}")
            if read_json_object(output / "run.json", "run identity") != identity:
                raise RuntimeError("tournament resume identity changed")
            return
        output.mkdir(parents=True, exist_ok=True)
        write_json_atomic(output / "run.json", identity)

    @staticmethod
    def _job_key(job: MatchJob) -> tuple[str, str, str]:
        return job.target.match_id, job.model, job.ordering

    @staticmethod
    def _record_key(record: dict[str, object]) -> tuple[str, str, str]:
        values = (record.get("match_id"), record.get("model"), record.get("ordering"))
        if any(type(value) is not str for value in values):
            raise RuntimeError("tournament record identity is invalid")
        return str(values[0]), str(values[1]), str(values[2])

    def _artifact_path(self, job: MatchJob) -> Path:
        model_id = hashlib.sha256(job.model.encode()).hexdigest()[:16]
        return (
            self.config.output_dir
            / "artifacts"
            / job.target.match_id
            / f"model-{model_id}"
            / f"{job.ordering}.json"
        )

    @staticmethod
    def _job_identity(job: MatchJob) -> dict[str, object]:
        target = job.target
        return {
            "match_id": target.match_id,
            "task_id": target.task_id,
            "replicate": target.replicate,
            "left_assignment_id": target.left.assignment_id,
            "right_assignment_id": target.right.assignment_id,
            "left_feedback_id": target.left.feedback_id,
            "right_feedback_id": target.right.feedback_id,
            "left_condition_id": target.left.condition_id,
            "right_condition_id": target.right.condition_id,
            "submission_id": "s010",
            "instruction_sha256": target.instruction_sha256,
            "left_answer_sha256": target.left.answer_sha256,
            "right_answer_sha256": target.right.answer_sha256,
            "left_trace_sha256": target.left.trace_sha256,
            "right_trace_sha256": target.right.trace_sha256,
            "model": job.model,
            "ordering": job.ordering,
            "protocol_sha256": PROTOCOL_SHA256,
        }

    def _retained_records(self, jobs: tuple[MatchJob, ...]) -> list[dict[str, object]]:
        retained = []
        with TerminalProgress(
            total=len(jobs),
            description="validating resumed tournament judgments",
            unit="judgment",
        ) as progress:
            for job in jobs:
                path = self._artifact_path(job)
                if path.exists():
                    if path.is_symlink() or not path.is_file():
                        raise RuntimeError(f"judgment is not a regular file: {path}")
                    record = read_json_object(path, "tournament judgment")
                    self._validate_completed_record(record, job)
                    retained.append(record)
                progress.update()
        return retained

    def _validate_completed_record(
        self, record: dict[str, object], job: MatchJob
    ) -> None:
        if (
            record.get("schema_version") != 1
            or record.get("kind") != ARTIFACT_KIND
            or record.get("status") != "completed"
            or any(record.get(key) != value for key, value in self._job_identity(job).items())
            or type(record.get("attempt_count")) is not int
            or record["attempt_count"] < 1
            or type(record.get("generation")) is not dict
            or record["generation"].get("requested_model") != job.model
            or type(record.get("raw_response")) is not str
            or type(record.get("raw_response_sha256")) is not str
            or type(record.get("verdict")) is not dict
        ):
            raise RuntimeError("tournament judgment artifact is incompatible")
        if sha256_text(record["raw_response"]) != record["raw_response_sha256"]:
            raise RuntimeError("tournament judgment raw response changed")
        if parse_verdict(record["raw_response"]) != record["verdict"]:
            raise RuntimeError("tournament judgment verdict changed")

    def _evaluate_match(self, jobs: list[MatchJob]) -> list[dict[str, object]]:
        records = []
        for job in jobs:
            try:
                records.append(self._evaluate_job(job))
            except Exception as exc:
                records.append(self._failure_record(job, exc))
        return records

    def _evaluate_job(self, job: MatchJob) -> dict[str, object]:
        request = StructuredRequest(
            instructions=SYSTEM_PROMPT,
            evidence=pair_prompt(job.target, job.ordering),
            schema_name="rubric_free_final_tournament_verdict",
            schema=VERDICT_SCHEMA,
        )
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 2):
            try:
                generation = self.generate_response(job.model, request)
                verdict = parse_verdict(generation.text)
                record = {
                    "schema_version": 1,
                    "kind": ARTIFACT_KIND,
                    **self._job_identity(job),
                    "status": "completed",
                    "attempt_count": attempt,
                    "verdict": verdict,
                    "raw_response": generation.text,
                    "raw_response_sha256": sha256_text(generation.text),
                    "generation": generation.provenance(),
                }
                path = self._artifact_path(job)
                path.parent.mkdir(parents=True, exist_ok=True)
                write_json_atomic(path, record)
                return record
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise RuntimeError(
            f"tournament judge failed after {self.config.max_retries + 1} attempts: "
            f"{last_error}"
        ) from last_error

    def _failure_record(self, job: MatchJob, error: BaseException) -> dict[str, object]:
        return {**self._job_identity(job), "status": "failed", "error": str(error)}

    @staticmethod
    def _score(record: dict[str, object], response: str, dimension: str) -> float:
        return float(record["verdict"][response][dimension]["score"])

    def _match_summaries(
        self, study: TournamentStudy, records: list[dict[str, object]]
    ) -> dict[str, object]:
        record_map = {
            self._record_key(record): record
            for record in records
            if record.get("status") == "completed"
        }
        summaries: dict[str, object] = {}
        for target in study.targets:
            judges: dict[str, object] = {}
            for model in self.config.models:
                normal = record_map.get((target.match_id, model, "left-first"))
                flipped = record_map.get((target.match_id, model, "right-first"))
                if normal is None or flipped is None:
                    judges[model] = {"status": "incomplete"}
                    continue
                left_scores = {
                    dimension: fmean((
                        self._score(normal, "response_A", dimension),
                        self._score(flipped, "response_B", dimension),
                    ))
                    for dimension in SCORE_FIELDS
                }
                right_scores = {
                    dimension: fmean((
                        self._score(normal, "response_B", dimension),
                        self._score(flipped, "response_A", dimension),
                    ))
                    for dimension in SCORE_FIELDS
                }
                delta = left_scores["overall"] - right_scores["overall"]
                judges[model] = {
                    "status": "completed",
                    "left_scores": left_scores,
                    "right_scores": right_scores,
                    "overall_delta": delta,
                    "winner": "left" if delta > 0 else "right" if delta < 0 else "tie",
                }
            complete = [
                value for value in judges.values()
                if isinstance(value, dict) and value.get("status") == "completed"
            ]
            if len(complete) != 3:
                panel: dict[str, object] = {"status": "incomplete"}
            else:
                votes = [str(value["winner"]) for value in complete]
                winner = (
                    "left" if votes.count("left") >= 2
                    else "right" if votes.count("right") >= 2
                    else "tie"
                )
                panel = {
                    "status": "completed",
                    "left_mean_scores": {
                        dimension: fmean(value["left_scores"][dimension] for value in complete)
                        for dimension in SCORE_FIELDS
                    },
                    "right_mean_scores": {
                        dimension: fmean(value["right_scores"][dimension] for value in complete)
                        for dimension in SCORE_FIELDS
                    },
                    "majority_winner": winner,
                    "consensus_winner": votes[0] if len(set(votes)) == 1 else None,
                }
            summaries[target.match_id] = {
                "task_id": target.task_id,
                "replicate": target.replicate,
                "submission_id": "s010",
                "left_assignment_id": target.left.assignment_id,
                "right_assignment_id": target.right.assignment_id,
                "left_feedback_id": target.left.feedback_id,
                "right_feedback_id": target.right.feedback_id,
                "left_condition_id": target.left.condition_id,
                "right_condition_id": target.right.condition_id,
                "judges": judges,
                "panel": panel,
            }
        return summaries

    @staticmethod
    def _outcome_counts(scores: list[float]) -> dict[str, object]:
        return {
            "comparisons": len(scores),
            "wins": scores.count(1.0),
            "ties": scores.count(0.5),
            "losses": scores.count(0.0),
            "half_win_rate": fmean(scores) if scores else None,
        }

    @classmethod
    def _factor_summaries(cls, matches: dict[str, object]) -> dict[str, object]:
        complete = [
            match for match in matches.values()
            if isinstance(match, dict)
            and isinstance(match.get("panel"), dict)
            and match["panel"].get("status") == "completed"
        ]
        marginal: dict[str, list[float]] = {
            "rubric.static": [], "rubric.dynamic": [],
            "prompt.base": [], "prompt.diligent": [],
            "feedback.semi": [], "feedback.full": [],
        }
        controlled: dict[str, list[float]] = {
            "dynamic_vs_static": [],
            "dynamic_vs_static_given_base": [],
            "dynamic_vs_static_given_diligent": [],
            "diligent_vs_base": [],
            "diligent_vs_base_given_static": [],
            "diligent_vs_base_given_dynamic": [],
            "full_vs_semi": [],
        }
        for match in complete:
            left = str(match["left_condition_id"])
            right = str(match["right_condition_id"])
            left_feedback = str(match["left_feedback_id"])
            right_feedback = str(match["right_feedback_id"])
            winner = match["panel"]["majority_winner"]
            left_score = 1.0 if winner == "left" else 0.0 if winner == "right" else 0.5
            right_score = 1.0 - left_score
            for condition, feedback, score in (
                (left, left_feedback, left_score),
                (right, right_feedback, right_score),
            ):
                marginal[f"rubric.{FACTORS[condition]['rubric']}"].append(score)
                marginal[f"prompt.{FACTORS[condition]['prompt']}"].append(score)
                marginal[f"feedback.{feedback}"].append(score)

            left_factors, right_factors = FACTORS[left], FACTORS[right]
            if (
                left_feedback == right_feedback
                and left_factors["prompt"] == right_factors["prompt"]
            ):
                dynamic_score = left_score if left_factors["rubric"] == "dynamic" else right_score
                prompt = left_factors["prompt"]
                controlled["dynamic_vs_static"].append(dynamic_score)
                controlled[f"dynamic_vs_static_given_{prompt}"].append(dynamic_score)
            if (
                left_feedback == right_feedback
                and left_factors["rubric"] == right_factors["rubric"]
            ):
                diligent_score = left_score if left_factors["prompt"] == "diligent" else right_score
                rubric = left_factors["rubric"]
                controlled["diligent_vs_base"].append(diligent_score)
                controlled[f"diligent_vs_base_given_{rubric}"].append(diligent_score)
            if left == right and left_feedback != right_feedback:
                full_score = left_score if left_feedback == "full" else right_score
                controlled["full_vs_semi"].append(full_score)
        return {
            "tie_policy": "a tie gives each side half a win",
            "marginal": {key: cls._outcome_counts(value) for key, value in marginal.items()},
            "controlled": {
                key: cls._outcome_counts(value) for key, value in controlled.items()
            },
        }

    def _write_summary(
        self,
        study: TournamentStudy,
        records: list[dict[str, object]],
        *,
        final: bool,
    ) -> None:
        model_order = {model: index for index, model in enumerate(self.config.models)}
        ordering_order = {value: index for index, value in enumerate(ORDERINGS)}
        records.sort(key=lambda record: (
            str(record["match_id"]),
            model_order[str(record["model"])],
            ordering_order[str(record["ordering"])],
        ))
        total = len(study.targets) * len(self.config.models) * 2
        completed = sum(record["status"] == "completed" for record in records)
        failed = sum(record["status"] == "failed" for record in records)
        matches = self._match_summaries(study, records)
        summary_records = [
            {key: value for key, value in record.items() if key != "raw_response"}
            for record in records
        ]
        write_json_atomic(self.config.output_dir / "summary.json", {
            "schema_version": 1,
            "kind": SUMMARY_KIND,
            "status": "completed" if completed == total else "failed" if final else "running",
            "paper": {"citation": PAPER, "url": PAPER_URL},
            "source": {
                "study_dirs": {
                    feedback: str(source)
                    for feedback, source in zip(FEEDBACKS, study.sources, strict=True)
                },
                "experiment_ids": {
                    feedback: experiment_id
                    for feedback, experiment_id in zip(
                        FEEDBACKS,
                        study.experiment_ids,
                        strict=True,
                    )
                },
                "block_count": len(study.targets) // 28,
                "match_count": len(study.targets),
            },
            "protocol": {
                "system_prompt": "exact Appendix I.1 prompt",
                "method_relation": (
                    "modified Appendix I.1 pairwise method with trace evidence"
                ),
                "models": list(self.config.models),
                "submission_id": "s010",
                "feedbacks": list(FEEDBACKS),
                "conditions_per_block": 8,
                "matches_per_block": 28,
                "replicate_sampling": {
                    "policy": "one complete replicate per task",
                    "seed": SAMPLE_SEED,
                },
                "position_flipped": True,
                "response_evidence": ["answer.txt", "trace.md"],
                "rubric_visible_to_judges": False,
                "answer_visible_to_judges": True,
                "trace_visible_to_judges": True,
                "trajectory_visible_to_judges": False,
                "primary_outcome": "three-judge majority with ties retained",
                "tie_policy": "half a win for each side",
                "max_retries": self.config.max_retries,
            },
            "totals": {
                "jobs": total,
                "completed": completed,
                "failed": failed,
                "pending": total - completed - failed,
            },
            "records": summary_records,
            "matches": matches,
            "factors": self._factor_summaries(matches),
        })
