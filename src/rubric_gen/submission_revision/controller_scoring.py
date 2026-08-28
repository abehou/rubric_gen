"""Score and replay submission revision boundaries."""

from __future__ import annotations

import math
import os
import secrets
from dataclasses import replace
from numbers import Real
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic as _write_json_atomic
from rubric_gen.benchmarks import SubmissionBenchmark
from rubric_gen.submission_revision.artifacts import (
    make_read_only as _make_read_only,
    read_json_object as _read_json_object,
    sha256_file as _sha256_file,
    tree_sha256 as _tree_sha256,
    verify_submission_snapshot as _verify_submission_snapshot,
)
from rubric_gen.submission_revision.bank_scoring import preflight_bank_dispatch
from rubric_gen.submission_revision.contrasts import build_elicitation_artifact_history
from rubric_gen.submission_revision.controller_recovery_artifacts import (
    fixed_original_attempt_id,
)
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    compose_bank_score,
    project_bank_feedback,
    project_bank_simulated_user_feedback,
)
from rubric_gen.submission_revision.judge import (
    FrozenRubric,
    FrozenRubricJudge,
    JudgeArtifacts,
    SubmissionJudge,
)
from rubric_gen.submission_revision.judging.models import RUBRIC_PATH_SOURCE
from rubric_gen.submission_revision.judgment_reuse import (
    ExactJudgmentReuseStore,
    ExactSimulatorReuseStore,
    exact_judgment_request,
    exact_simulator_request,
)
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    RevisionPhase as _RevisionPhase,
    RevisionState as _RevisionState,
    SubmissionRevisionConfig,
)
from rubric_gen.submission_revision.reports import publish_revision_report
from rubric_gen.submission_revision.rubric_bank import (
    RubricBank,
    RubricBankItem,
    RubricBankPolicy,
)
from rubric_gen.submission_revision.rubric_bank_lifecycle import (
    RubricBankGeneration,
    load_rubric_bank,
    persist_rubric_bank,
    rubric_bank_directory,
)
from rubric_gen.submission_revision.seeds import ResolvedSeed
from rubric_gen.submission_revision.store import (
    RevisionStore,
    extract_scoring_identity as _extract_scoring_identity,
    extract_seed_scoring_contract as _extract_seed_scoring_contract,
)
from rubric_gen.submission_revision.visualization.revisions import (
    write_revision_score_plot,
)


class RevisionScorer:
    def __init__(
        self,
        *,
        config: SubmissionRevisionConfig,
        benchmark: SubmissionBenchmark,
        experiment_dir: Path,
        task_dir: Path,
        dependencies: RevisionDependencies,
        bank_policy: RubricBankPolicy,
        initial_bank: RubricBankGeneration,
        initial_rubric: FrozenRubric,
        master_rubric: FrozenRubric,
        master_judge: SubmissionJudge,
        seed: ResolvedSeed,
        judgment_reuse: ExactJudgmentReuseStore | None,
        simulator_reuse: ExactSimulatorReuseStore | None,
        reuse_seed_judgment: bool,
        reuse_seed_master_judgment: bool,
        instruction_sha256: str,
        data_sha256: str,
        store: RevisionStore,
    ) -> None:
        self.config = config
        self.benchmark = benchmark
        self.experiment_dir = experiment_dir
        self.task_dir = task_dir
        self.dependencies = dependencies
        self.bank_policy = bank_policy
        self.initial_bank = initial_bank
        self.initial_rubric = initial_rubric
        self.master_rubric = master_rubric
        self.master_judge = master_judge
        self.seed = seed
        self.judgment_reuse = judgment_reuse
        self.simulator_reuse = simulator_reuse
        self.reuse_seed_judgment = reuse_seed_judgment
        self.reuse_seed_master_judgment = reuse_seed_master_judgment
        self.instruction_sha256 = instruction_sha256
        self.data_sha256 = data_sha256
        self.store = store

    def verify_canonical_task_inputs(self) -> None:
        if _sha256_file(self.task_dir / "instruction.md") != self.instruction_sha256:
            raise RuntimeError(
                "canonical task instruction changed during the experiment"
            )
        if _tree_sha256(self.task_dir / "environment" / "data") != self.data_sha256:
            raise RuntimeError("canonical task data changed during the experiment")

    def compile_offline_bank(self) -> None:
        """Compile the sole offline rubric before any treatment boundary."""

        proposer = self.dependencies.bank_proposer
        if proposer is None:
            raise RuntimeError("offline elicitation has no rubric proposer")
        generation = proposer.elicit_rubric(
            instruction=(self.task_dir / "instruction.md").read_text(
                encoding="utf-8"
            ),
            current_bank=self.initial_bank.bank,
            policy=RubricBankPolicy.OFFLINE_ELICITATION,
            generation_round=1,
            artifact_history=self.elicitation_history(1),
            source_boundary=None,
            output_dir=self.experiment_dir / "rubric-generations",
        )
        generation.bank.validate_lineage(self.initial_bank.bank)
        persist_rubric_bank(
            self.experiment_dir,
            generation,
            RubricBankPolicy.OFFLINE_ELICITATION,
        )

    def run_judge_boundary(self, state: _RevisionState) -> None:
        self.validate_scored_boundaries(state)
        submission_id = state.submission_ids[-1]
        turn_index = state.next_turn_index - 1
        attempt_id = state.judge_attempts.get(submission_id)
        if attempt_id is None:
            attempt_id = secrets.token_hex(16)
            state.judge_attempts[submission_id] = attempt_id
        state.phase = _RevisionPhase.JUDGE_IN_PROGRESS
        self.store.write_state(state)
        submission_dir = self.experiment_dir / "submissions" / submission_id
        _verify_submission_snapshot(submission_dir)
        self.verify_canonical_task_inputs()
        generation = self.active_bank_generation(turn_index)
        bank = generation.bank
        review_text, answer_text = self.dependencies.judge.review_inputs(
            submission_dir
        )
        dispatch_preflight = preflight_bank_dispatch(
            bank,
            benchmark=self.config.benchmark,
            review_text=review_text,
            answer_text=answer_text,
        )
        member_artifacts: dict[str, JudgeArtifacts] = {}
        for item in bank.items:
            rubric, judge = self.bank_member_runtime(
                item, bank.generation_round
            )
            seed_reusable = (
                turn_index == 0
                and item.rubric.content_sha256 == self.initial_rubric.sha256
                and self.reuse_seed_judgment
            )
            if seed_reusable:
                validation_path, evaluation_path, _ = self.seed.judgment
                artifacts = JudgeArtifacts(validation_path, evaluation_path)
                seeded = True
            elif self.judgment_reuse is not None:
                request = exact_judgment_request(
                    task_id=self.task_dir.name,
                    replicate=self.config.replicate,
                    rubric_sha256=item.rubric.content_sha256,
                    review_text=review_text,
                    answer_text=answer_text,
                    scoring_identity=judge.scoring_identity(),
                )

                def generate() -> JudgeArtifacts:
                    return judge.evaluate(submission_dir, attempt_id)

                reused = self.judgment_reuse.resolve(
                    request=request,
                    producer={
                        "assignment_id": self.config.assignment_id,
                        "condition_id": self.config.condition_id,
                        "replicate": self.config.replicate,
                        "submission_id": submission_id,
                        "rubric_sha256": item.rubric.content_sha256,
                        "judge_attempt_id": attempt_id,
                    },
                    generate=generate,
                )
                self.judgment_reuse.persist_alias(
                    experiment_dir=self.experiment_dir,
                    assignment_id=self.config.assignment_id,
                    replicate=self.config.replicate,
                    submission_id=submission_id,
                    rubric_sha256=item.rubric.content_sha256,
                    reused=reused,
                )
                artifacts = reused.artifacts
                seeded = False
            else:
                artifacts = judge.evaluate(submission_dir, attempt_id)
                seeded = False
            self.verify_round_scoring_identity(
                artifacts.score_validation_path,
                rubric,
                judge,
                seeded=seeded,
            )
            member_artifacts[item.rubric.content_sha256] = artifacts
        self.verify_canonical_task_inputs()
        _verify_submission_snapshot(submission_dir)
        fixed_original_score, fixed_original_artifacts = (
            self.fixed_original_judgment(
                submission_dir=submission_dir,
                submission_id=submission_id,
                turn_index=turn_index,
                active_member_artifacts=member_artifacts,
                allow_generation=True,
            )
        )
        feedback = self.project_boundary_feedback(
            artifacts=member_artifacts,
            bank=bank,
            submission_id=submission_id,
            generation_round=bank.generation_round,
            submission_dir=submission_dir,
            allow_generation=True,
            fixed_original_score=fixed_original_score,
            fixed_original_artifacts=fixed_original_artifacts,
        )
        bank_evaluation = self.bank_evaluation_record(
            bank,
            member_artifacts,
            submission_id,
            dispatch_preflight,
            fixed_original_score,
        )
        if bank_evaluation["score"] != feedback.score:
            raise RuntimeError("bank evaluation and feedback scores disagree")
        bank_evaluation_path = (
            self.experiment_dir / "bank-evaluations" / f"{submission_id}.json"
        )
        if bank_evaluation_path.exists():
            if _read_json_object(
                bank_evaluation_path,
                "bank evaluation",
            ) != bank_evaluation:
                raise RuntimeError("existing bank evaluation changed")
        else:
            _write_json_atomic(bank_evaluation_path, bank_evaluation)
            _make_read_only(bank_evaluation_path)
        feedback_path = self.experiment_dir / "feedback" / f"{submission_id}.json"
        if feedback_path.exists():
            if (
                _read_json_object(feedback_path, "revision feedback")
                != feedback.payload
            ):
                raise RuntimeError("existing feedback disagrees with judge artifacts")
        else:
            _write_json_atomic(feedback_path, feedback.payload)
            _make_read_only(feedback_path)
        next_bank: dict[str, object] | None = None
        if (
            self.bank_policy is RubricBankPolicy.ONLINE_ELICITATION
            and 1 <= turn_index < self.config.revision_rounds
        ):
            assert self.dependencies.bank_proposer is not None
            next_generation = self.dependencies.bank_proposer.elicit_rubric(
                instruction=(self.task_dir / "instruction.md").read_text(),
                current_bank=bank,
                policy=self.bank_policy,
                generation_round=turn_index,
                artifact_history=self.elicitation_history(turn_index),
                source_boundary=(
                    turn_index
                    if self.bank_policy is RubricBankPolicy.ONLINE_ELICITATION
                    else None
                ),
                output_dir=self.experiment_dir / "rubric-generations",
            )
            next_generation.bank.validate_lineage(bank)
            persist_rubric_bank(
                self.experiment_dir,
                next_generation,
                self.bank_policy,
            )
            next_bank = {
                "generation_round": next_generation.bank.generation_round,
                "bank_sha256": next_generation.bank.content_sha256,
                "rubric_count": next_generation.bank.rubric_count,
                "inverse_weight_concentration": (
                    next_generation.bank.inverse_weight_concentration
                ),
                "source_boundary": next_generation.bank.source_boundary,
                "proposer_call_budget": next_generation.proposer_call_budget,
            }
        state.scores.append(feedback.score)
        state.fixed_original_scores.append(fixed_original_score)
        state.next_prompt = feedback.prompt
        state.phase = _RevisionPhase.READY_FOR_TURN
        self.store.write_state(state)
        self.publish_progress_report(state, submission_id)
        self.store.append_event(
            {
                "event": "submission_judged",
                "submission_id": submission_id,
                "turn": turn_index,
                "judge_attempt_id": attempt_id,
                "score": feedback.score,
                "fixed_original_score": fixed_original_score,
                "elicited_penalty": feedback.score - fixed_original_score,
                "feedback_policy": FeedbackPolicy(self.config.feedback_policy).value,
                "feedback_sha256": _sha256_file(feedback_path),
                "bank_evaluation_sha256": _sha256_file(bank_evaluation_path),
                "bank_generation_round": bank.generation_round,
                "bank_sha256": bank.content_sha256,
                "bank_member_sha256s": [
                    item.rubric.content_sha256 for item in bank.items
                ],
                "bank_weights": [item.weight for item in bank.items],
                "next_bank": next_bank,
            }
        )

    def bank_evaluation_record(
        self,
        bank: RubricBank,
        artifacts: dict[str, JudgeArtifacts],
        submission_id: str,
        dispatch_preflight: dict[str, object],
        fixed_original_score: float,
    ) -> dict[str, object]:
        if (
            dispatch_preflight.get("bank_sha256") != bank.content_sha256
            or dispatch_preflight.get("member_sha256s")
            != [item.rubric.content_sha256 for item in bank.items]
        ):
            raise RuntimeError("bank dispatch preflight has the wrong bank binding")
        members: dict[str, dict[str, object]] = {}
        validation_paths = {
            rubric_hash: artifact.score_validation_path
            for rubric_hash, artifact in artifacts.items()
        }
        composition = compose_bank_score(
            bank,
            validation_paths,
            fixed_original_score,
        )
        for item in bank.items:
            rubric_hash = item.rubric.content_sha256
            member = artifacts.get(rubric_hash)
            if member is None:
                raise RuntimeError("bank evaluation lacks member artifacts")
            validation = _read_json_object(
                member.score_validation_path,
                "bank member score validation",
            )
            score = validation.get("score")
            if (
                isinstance(score, bool)
                or not isinstance(score, Real)
                or not math.isfinite(float(score))
                or not 0 <= float(score) <= 100
            ):
                raise RuntimeError("bank member has an invalid score")
            if (
                validation.get("review_input_sha256")
                != dispatch_preflight.get("review_text_sha256")
                or validation.get("answer_input_sha256")
                != dispatch_preflight.get("answer_text_sha256")
            ):
                raise RuntimeError(
                    "bank member score uses a different preflight payload"
                )
            member_composition = composition.members[rubric_hash]
            members[rubric_hash] = {
                "weight": item.weight,
                "judge_score": score,
                "elicited_penalty": member_composition.elicited_penalty,
                "score": member_composition.score,
                "score_validation_sha256": _sha256_file(
                    member.score_validation_path
                ),
                "evaluation_sha256": _sha256_file(member.evaluation_path),
            }
        return {
            "kind": "canonical-original-plus-elicited-penalty-evaluation",
            "submission_id": submission_id,
            "generation_round": bank.generation_round,
            "bank_sha256": bank.content_sha256,
            "dispatch_preflight": dispatch_preflight,
            "members": members,
            "canonical_original_score": composition.canonical_original_score,
            "weighted_elicited_penalty": (
                composition.weighted_elicited_penalty
            ),
            "score": composition.score,
        }

    def project_boundary_feedback(
        self,
        *,
        artifacts: dict[str, JudgeArtifacts],
        bank: RubricBank,
        submission_id: str,
        generation_round: int,
        submission_dir: Path,
        allow_generation: bool,
        fixed_original_score: float,
        fixed_original_artifacts: JudgeArtifacts,
    ):
        policy = FeedbackPolicy(self.config.feedback_policy)
        if policy is not FeedbackPolicy.USER_SIMULATOR:
            return project_bank_feedback(
                bank,
                {
                    rubric_hash: (
                        member.score_validation_path,
                        member.evaluation_path,
                    )
                    for rubric_hash, member in artifacts.items()
                },
                policy,
                fixed_original_artifacts=(
                    fixed_original_artifacts.score_validation_path,
                    fixed_original_artifacts.evaluation_path,
                ),
                fixed_original_rubric_text=self.master_rubric.text,
                fixed_original_rubric_sha256=self.master_rubric.sha256,
                prompt_profile=self.config.prompt_profile,
                benchmark=self.config.benchmark,
            )

        simulator = self.dependencies.feedback_simulator
        if simulator is None:
            raise RuntimeError("simulated-user feedback generator is unavailable")
        generation_path = (
            self.experiment_dir
            / "feedback-generations"
            / f"{submission_id}.json"
        )
        if generation_path.is_symlink():
            raise RuntimeError(
                f"simulated-user generation is an invalid symlink: {generation_path}"
            )
        reuse_request: dict[str, object] | None = None
        instruction: str | None = None
        current_submission: str | None = None
        if self.simulator_reuse is not None:
            instruction = (self.task_dir / "instruction.md").read_text(
                encoding="utf-8"
            )
            current_submission = self.benchmark.render_submission(
                submission_dir / "workspace"
            )
            reuse_request = exact_simulator_request(
                experiment_id=self.config.experiment_id,
                task_id=self.task_dir.name,
                replicate=self.config.replicate,
                instruction=instruction,
                bank_sha256=bank.content_sha256,
                current_submission=current_submission,
                simulator_identity=simulator.identity(),
            )
        if generation_path.is_file():
            generation = _read_json_object(
                generation_path,
                "simulated-user generation",
            )
            if self.simulator_reuse is not None:
                assert reuse_request is not None
                reused = self.simulator_reuse.validate_alias(
                    self.experiment_dir
                    / "simulated-user-aliases"
                    / f"{submission_id}.json",
                    assignment_id=self.config.assignment_id,
                    replicate=self.config.replicate,
                    submission_id=submission_id,
                    expected_request=reuse_request,
                )
                expected_generation = self.simulator_reuse.assignment_record(
                    reused,
                    experiment_id=self.config.experiment_id,
                    assignment_id=self.config.assignment_id,
                    submission_id=submission_id,
                    generation_round=generation_round,
                    bank_sha256=bank.content_sha256,
                    simulator_identity=simulator.identity(),
                )
                if generation != expected_generation:
                    raise RuntimeError(
                        "simulated-user generation differs from its shared artifact"
                    )
        else:
            if os.path.lexists(generation_path):
                raise RuntimeError(
                    "simulated-user generation is not a regular file: "
                    f"{generation_path}"
                )
            if not allow_generation:
                raise RuntimeError(
                    f"missing simulated-user generation for {submission_id}"
                )
            workspace = submission_dir / "workspace"
            if instruction is None:
                instruction = (self.task_dir / "instruction.md").read_text(
                    encoding="utf-8"
                )
            if current_submission is None:
                current_submission = self.benchmark.render_submission(workspace)
            if self.simulator_reuse is not None:
                assert reuse_request is not None
                reused = self.simulator_reuse.resolve(
                    request=reuse_request,
                    producer={
                        "assignment_id": self.config.assignment_id,
                        "condition_id": self.config.condition_id,
                        "replicate": self.config.replicate,
                        "submission_id": submission_id,
                        "generation_round": generation_round,
                    },
                    generate=lambda: simulator.generate(
                        experiment_id=self.config.experiment_id,
                        assignment_id=self.config.assignment_id,
                        submission_id=submission_id,
                        generation_round=generation_round,
                        instruction=instruction,
                        bank=bank,
                        current_submission=current_submission,
                    ),
                )
                self.simulator_reuse.persist_alias(
                    experiment_dir=self.experiment_dir,
                    assignment_id=self.config.assignment_id,
                    replicate=self.config.replicate,
                    submission_id=submission_id,
                    reused=reused,
                )
                generation = self.simulator_reuse.assignment_record(
                    reused,
                    experiment_id=self.config.experiment_id,
                    assignment_id=self.config.assignment_id,
                    submission_id=submission_id,
                    generation_round=generation_round,
                    bank_sha256=bank.content_sha256,
                    simulator_identity=simulator.identity(),
                )
            else:
                generation = simulator.generate(
                    experiment_id=self.config.experiment_id,
                    assignment_id=self.config.assignment_id,
                    submission_id=submission_id,
                    generation_round=generation_round,
                    instruction=instruction,
                    bank=bank,
                    current_submission=current_submission,
                )
            _write_json_atomic(generation_path, generation)
            _make_read_only(generation_path)
        comment = simulator.validate(
            generation,
            experiment_id=self.config.experiment_id,
            assignment_id=self.config.assignment_id,
            submission_id=submission_id,
            generation_round=generation_round,
            bank=bank,
        )
        return project_bank_simulated_user_feedback(
            bank,
            {
                rubric_hash: member.score_validation_path
                for rubric_hash, member in artifacts.items()
            },
            comment,
            fixed_original_score=fixed_original_score,
            prompt_profile=self.config.prompt_profile,
            benchmark=self.config.benchmark,
        )

    def publish_progress_report(
        self,
        state: _RevisionState,
        submission_id: str,
    ) -> None:
        """Best-effort publication that cannot abort a scientific revision."""
        try:
            write_revision_score_plot(
                state.scores,
                state.fixed_original_scores,
                self.experiment_dir / "score_improvement.png",
                task_id=self.task_dir.name,
                feedback_policy=FeedbackPolicy(self.config.feedback_policy).value,
            )
            if self.config.publish_report:
                publish_revision_report(self.experiment_dir)
        except Exception as exc:
            self.store.append_event(
                {
                    "event": "report_publication_failed",
                    "submission_id": submission_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc) or type(exc).__name__,
                }
            )

    def active_bank_generation(self, boundary: int) -> RubricBankGeneration:
        generation_round = (
            0
            if self.bank_policy is RubricBankPolicy.FIXED
            else (
                1
                if self.bank_policy is RubricBankPolicy.OFFLINE_ELICITATION
                else max(0, boundary - 1)
            )
        )
        generation = load_rubric_bank(
            self.experiment_dir,
            generation_round,
            expected_policy=self.bank_policy,
        )
        if generation_round > 0:
            prior = load_rubric_bank(
                self.experiment_dir,
                generation_round - 1,
                expected_policy=self.bank_policy,
            )
            generation.bank.validate_lineage(prior.bank)
        return generation

    def elicitation_history(self, generation_round: int):
        """Return the complete blinded history for one rubric update."""

        return build_elicitation_artifact_history(
            online=self.bank_policy is RubricBankPolicy.ONLINE_ELICITATION,
            seed_set=self.config.seed_run_dir,
            task_dir=self.task_dir,
            experiment_dir=self.experiment_dir,
            benchmark=self.benchmark,
            provider=self.config.agent.provider,
            requested_model=self.config.agent.model,
            assignment_id=self.config.assignment_id,
            generation_round=generation_round,
        )

    @staticmethod
    def frozen_bank_member(text: str, rubric_sha256: str) -> FrozenRubric:
        """Return the judge identity for one immutable bank member."""
        return FrozenRubric(
            text=text, sha256=rubric_sha256, source=RUBRIC_PATH_SOURCE,
            rubric_set_id=None, rubric_id=None,
            structured_rubric_sha256=None, manifest_sha256=None,
        )

    def bank_member_runtime(
        self,
        item: RubricBankItem,
        generation_round: int,
    ) -> tuple[FrozenRubric, object]:
        if item.rubric.content_sha256 == self.initial_rubric.sha256:
            return self.initial_rubric, self.dependencies.judge
        path = (
            rubric_bank_directory(self.experiment_dir, generation_round)
            / "members"
            / f"{item.rubric.content_sha256}.txt"
        )
        rubric = self.frozen_bank_member(
            item.rubric.content,
            item.rubric.content_sha256,
        )
        config = replace(
            self.config.judge_config(),
            rubric_name=None,
            rubric_set=None,
            rubric_path=path,
        )
        return rubric, FrozenRubricJudge(config, rubric)

    def fixed_original_judgment(
        self,
        *,
        submission_dir: Path,
        submission_id: str,
        turn_index: int,
        active_member_artifacts: dict[str, JudgeArtifacts],
        allow_generation: bool,
    ) -> tuple[float, JudgeArtifacts]:
        active_bank = self.active_bank_generation(turn_index).bank
        seeded = False
        if turn_index == 0 and self.reuse_seed_master_judgment:
            validation_path, evaluation_path, _ = self.seed.judgment
            artifacts = JudgeArtifacts(validation_path, evaluation_path)
            seeded = True
        elif (
            active_bank.rubric_count == 1
            and active_bank.items[0].rubric.content_sha256
            == self.master_rubric.sha256
            and (
                turn_index == 0
                or self.bank_policy is RubricBankPolicy.FIXED
            )
        ):
            artifacts = active_member_artifacts.get(self.master_rubric.sha256)
            if artifacts is None:
                raise RuntimeError("active bank lacks the master judgment")
        elif self.judgment_reuse is not None:
            review_text, answer_text = self.master_judge.review_inputs(submission_dir)
            request = exact_judgment_request(
                task_id=self.task_dir.name,
                replicate=self.config.replicate,
                rubric_sha256=self.master_rubric.sha256,
                review_text=review_text,
                answer_text=answer_text,
                scoring_identity=self.master_judge.scoring_identity(),
            )
            attempt_id = fixed_original_attempt_id(
                self.config.assignment_id,
                submission_id,
                self.master_rubric.sha256,
            )
            if allow_generation:
                reused = self.judgment_reuse.resolve(
                    request=request,
                    producer={
                        "assignment_id": self.config.assignment_id,
                        "condition_id": self.config.condition_id,
                        "replicate": self.config.replicate,
                        "submission_id": submission_id,
                        "rubric_sha256": self.master_rubric.sha256,
                        "judge_attempt_id": attempt_id,
                    },
                    generate=lambda: self.master_judge.evaluate(
                        submission_dir,
                        attempt_id,
                    ),
                )
                self.judgment_reuse.persist_alias(
                    experiment_dir=self.experiment_dir,
                    assignment_id=self.config.assignment_id,
                    replicate=self.config.replicate,
                    submission_id=submission_id,
                    rubric_sha256=self.master_rubric.sha256,
                    reused=reused,
                )
            else:
                reused = self.judgment_reuse.validate_alias(
                    self.experiment_dir
                    / "judgment-aliases"
                    / submission_id
                    / (self.judgment_reuse.request_sha256(request) + ".json"),
                    assignment_id=self.config.assignment_id,
                    replicate=self.config.replicate,
                    submission_id=submission_id,
                    rubric_sha256=self.master_rubric.sha256,
                    expected_request=request,
                )
            artifacts = reused.artifacts
        else:
            attempt_id = fixed_original_attempt_id(
                self.config.assignment_id,
                submission_id,
                self.master_rubric.sha256,
            )
            artifacts = (
                self.master_judge.evaluate(submission_dir, attempt_id)
                if allow_generation
                else self.master_judge.validate(submission_dir, attempt_id)
            )
        self.verify_round_scoring_identity(
            artifacts.score_validation_path,
            self.master_rubric,
            self.master_judge,
            seeded=seeded,
        )
        validation = _read_json_object(
            artifacts.score_validation_path,
            "fixed-original score validation",
        )
        score = validation.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
        ):
            raise RuntimeError("fixed-original judgment has an invalid score")
        return float(score), artifacts

    def verify_round_scoring_identity(
        self,
        validation_path: Path,
        rubric: FrozenRubric,
        judge: SubmissionJudge,
        *,
        seeded: bool = False,
    ) -> None:
        if seeded:
            validation = _read_json_object(
                validation_path,
                "seeded optimizer score validation",
            )
            identity = _extract_seed_scoring_contract(
                validation,
                context="seeded optimizer score validation",
            )
            reported = judge.scoring_identity()
            if identity != _extract_seed_scoring_contract(
                reported,
                context="round judge",
            ):
                raise RuntimeError(
                    "seeded score does not match the scoring contract"
                )
            if identity["rendered_rubric_sha256"] != rubric.sha256:
                raise RuntimeError("seeded score attests a different rubric")
            return
        if (
            self.bank_policy is RubricBankPolicy.FIXED
            and rubric.sha256 == self.initial_rubric.sha256
        ):
            self.store.verify_scoring_identity(validation_path)
            return
        validation = _read_json_object(validation_path, "optimizer score validation")
        identity = _extract_scoring_identity(
            validation, context="optimizer score validation"
        )
        reported = judge.scoring_identity()
        if identity != _extract_scoring_identity(reported, context="round judge"):
            raise RuntimeError("round scoring identity does not match rubric judge")
        if identity["rendered_rubric_sha256"] != rubric.sha256:
            raise RuntimeError("round score attests a different rubric")

    def validate_scored_boundaries(self, state: _RevisionState) -> None:
        for index, score in enumerate(state.scores):
            submission_id = f"s{index:03d}"
            submission_dir = self.experiment_dir / "submissions" / submission_id
            _verify_submission_snapshot(submission_dir)
            attempt_id = state.judge_attempts.get(submission_id)
            if attempt_id is None:
                raise RuntimeError("scored submission has no judge attempt identity")
            bank = self.active_bank_generation(index).bank
            member_artifacts: dict[str, JudgeArtifacts] = {}
            for item in bank.items:
                rubric, judge = self.bank_member_runtime(
                    item, bank.generation_round
                )
                seeded = (
                    index == 0
                    and item.rubric.content_sha256 == self.initial_rubric.sha256
                    and self.reuse_seed_judgment
                )
                if seeded:
                    validation_path, evaluation_path, _ = self.seed.judgment
                    artifacts = JudgeArtifacts(validation_path, evaluation_path)
                elif self.judgment_reuse is not None:
                    review_text, answer_text = judge.review_inputs(submission_dir)
                    expected_request = exact_judgment_request(
                        task_id=self.task_dir.name,
                        replicate=self.config.replicate,
                        rubric_sha256=item.rubric.content_sha256,
                        review_text=review_text,
                        answer_text=answer_text,
                        scoring_identity=judge.scoring_identity(),
                    )
                    alias_path = (
                        self.experiment_dir
                        / "judgment-aliases"
                        / submission_id
                        / (
                            self.judgment_reuse.request_sha256(expected_request)
                            + ".json"
                        )
                    )
                    reused = self.judgment_reuse.validate_alias(
                        alias_path,
                        assignment_id=self.config.assignment_id,
                        replicate=self.config.replicate,
                        submission_id=submission_id,
                        rubric_sha256=item.rubric.content_sha256,
                        expected_request=expected_request,
                    )
                    artifacts = reused.artifacts
                    seeded = False
                else:
                    artifacts = judge.validate(submission_dir, attempt_id)
                self.verify_round_scoring_identity(
                    artifacts.score_validation_path,
                    rubric,
                    judge,
                    seeded=seeded,
                )
                member_artifacts[item.rubric.content_sha256] = artifacts
            expected_fixed_score, fixed_original_artifacts = (
                self.fixed_original_judgment(
                    submission_dir=submission_dir,
                    submission_id=submission_id,
                    turn_index=index,
                    active_member_artifacts=member_artifacts,
                    allow_generation=False,
                )
            )
            projected = self.project_boundary_feedback(
                artifacts=member_artifacts,
                bank=bank,
                submission_id=submission_id,
                generation_round=bank.generation_round,
                submission_dir=submission_dir,
                allow_generation=False,
                fixed_original_score=expected_fixed_score,
                fixed_original_artifacts=fixed_original_artifacts,
            )
            feedback = _read_json_object(
                self.experiment_dir / "feedback" / f"{submission_id}.json",
                "revision feedback",
            )
            if projected.score != score or feedback != projected.payload:
                raise RuntimeError(
                    "stored feedback disagrees with validated judge artifacts"
                )
            bank_evaluation = _read_json_object(
                self.experiment_dir
                / "bank-evaluations"
                / f"{submission_id}.json",
                "bank evaluation",
            )
            review_text, answer_text = self.dependencies.judge.review_inputs(
                submission_dir
            )
            expected_bank_evaluation = self.bank_evaluation_record(
                bank,
                member_artifacts,
                submission_id,
                preflight_bank_dispatch(
                    bank,
                    benchmark=self.config.benchmark,
                    review_text=review_text,
                    answer_text=answer_text,
                ),
                expected_fixed_score,
            )
            if bank_evaluation != expected_bank_evaluation:
                raise RuntimeError(
                    "stored bank evaluation disagrees with member artifacts"
                )
            if expected_fixed_score != state.fixed_original_scores[index]:
                raise RuntimeError(
                    "stored fixed-original score disagrees with judge artifacts"
                )
