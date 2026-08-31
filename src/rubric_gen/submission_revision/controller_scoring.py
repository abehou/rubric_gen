"""Score and replay submission revision checkpoints."""

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
    read_json_object as _read_json_object,
    sha256_file as _sha256_file,
    tree_sha256 as _tree_sha256,
    verify_submission_snapshot as _verify_submission_snapshot,
)
from rubric_gen.submission_revision.generation_scoring import (
    preflight_generation_dispatch,
)
from rubric_gen.submission_revision.contrasts import build_elicitation_artifact_history
from rubric_gen.submission_revision.controller_recovery_artifacts import (
    fixed_original_attempt_id,
)
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    compose_rubric_score,
    project_rubric_feedback,
    project_rubric_simulated_user_feedback,
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
    discard_temporary_judgment,
    exact_judgment_request,
    load_judgment_copy,
    persist_judgment_copy,
)
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    RevisionPhase as _RevisionPhase,
    RevisionState as _RevisionState,
    SubmissionRevisionConfig,
)
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricGeneration,
    RubricPolicy,
)
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
    rubric_generation_directory,
)
from rubric_gen.submission_revision.seeds import ResolvedSeed
from rubric_gen.submission_revision.store import (
    RevisionStore,
    extract_scoring_identity as _extract_scoring_identity,
    extract_seed_scoring_contract as _extract_seed_scoring_contract,
)
from rubric_gen.submission_revision.user_simulator_history import (
    build_simulated_user_history,
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
        rubric_policy: RubricPolicy,
        initial_generation: RubricGeneration,
        initial_rubric: FrozenRubric,
        master_rubric: FrozenRubric,
        master_judge: SubmissionJudge,
        seed: ResolvedSeed,
        judgment_reuse: ExactJudgmentReuseStore | None,
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
        self.rubric_policy = rubric_policy
        self.initial_generation = initial_generation
        self.initial_rubric = initial_rubric
        self.master_rubric = master_rubric
        self.master_judge = master_judge
        self.seed = seed
        self.judgment_reuse = judgment_reuse
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

    def assignment_judgment(
        self,
        *,
        judge: SubmissionJudge,
        submission_dir: Path,
        submission_id: str,
        rubric_sha256: str,
        attempt_id: str,
        allow_generation: bool,
    ) -> JudgeArtifacts:
        """Load or create the assignment-owned copy of one judgment."""

        review_text, answer_text = judge.review_inputs(submission_dir)
        request = exact_judgment_request(
            task_id=self.task_dir.name,
            replicate=self.config.replicate,
            rubric_sha256=rubric_sha256,
            review_text=review_text,
            answer_text=answer_text,
            scoring_identity=judge.scoring_identity(),
        )
        if not allow_generation:
            return load_judgment_copy(
                experiment_dir=self.experiment_dir,
                submission_id=submission_id,
                rubric_sha256=rubric_sha256,
                expected_request=request,
            )

        generated: JudgeArtifacts | None = None

        def generate() -> JudgeArtifacts:
            nonlocal generated
            generated = judge.evaluate(submission_dir, attempt_id)
            return generated

        if self.judgment_reuse is None:
            source = generate()
        else:
            source = self.judgment_reuse.resolve(
                request=request,
                producer={
                    "assignment_id": self.config.assignment_id,
                    "condition_id": self.config.condition_id,
                    "replicate": self.config.replicate,
                    "submission_id": submission_id,
                    "rubric_sha256": rubric_sha256,
                    "judge_attempt_id": attempt_id,
                },
                generate=generate,
            )
        artifacts = persist_judgment_copy(
            experiment_dir=self.experiment_dir,
            submission_id=submission_id,
            rubric_sha256=rubric_sha256,
            request=request,
            source=source,
        )
        if generated is not None:
            discard_temporary_judgment(self.experiment_dir, generated)
        return artifacts

    def compile_offline_rubric(self) -> None:
        """Compile the sole offline rubric before any treatment checkpoint."""

        proposer = self.dependencies.rubric_proposer
        if proposer is None:
            raise RuntimeError("offline elicitation has no rubric proposer")
        generation = proposer.elicit_rubric(
            instruction=(self.task_dir / "instruction.md").read_text(
                encoding="utf-8"
            ),
            original_rubric=CompleteRubric.from_content(self.initial_rubric.text),
            current_generation=self.initial_generation,
            policy=RubricPolicy.OFFLINE_ELICITATION,
            generation_round=1,
            artifact_history=self.elicitation_history(1),
            source_checkpoint=None,
            output_dir=self.experiment_dir,
        )
        generation.validate_successor(self.initial_generation)

    def run_judge_checkpoint(self, state: _RevisionState) -> None:
        self.validate_latest_checkpoint(state)
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
        self.ensure_online_rubric_generation(turn_index)
        generation = self.active_rubric_generation(turn_index)
        review_text, answer_text = self.dependencies.judge.review_inputs(
            submission_dir
        )
        dispatch_preflight = preflight_generation_dispatch(
            generation,
            benchmark=self.config.benchmark,
            review_text=review_text,
            answer_text=answer_text,
        )
        rubric, judge = self.rubric_runtime(generation)
        seed_reusable = (
            turn_index == 0
            and generation.rubric.content_sha256 == self.initial_rubric.sha256
            and self.reuse_seed_judgment
        )
        if seed_reusable:
            validation_path, evaluation_path, _ = self.seed.judgment
            artifacts = JudgeArtifacts(validation_path, evaluation_path)
            seeded = True
        else:
            artifacts = self.assignment_judgment(
                judge=judge,
                submission_dir=submission_dir,
                submission_id=submission_id,
                rubric_sha256=generation.rubric.content_sha256,
                attempt_id=attempt_id,
                allow_generation=True,
            )
            seeded = False
        self.verify_round_scoring_identity(
            artifacts.score_validation_path,
            rubric,
            judge,
            seeded=seeded,
        )
        self.verify_canonical_task_inputs()
        _verify_submission_snapshot(submission_dir)
        fixed_original_score, fixed_original_artifacts = (
            self.fixed_original_judgment(
                submission_dir=submission_dir,
                submission_id=submission_id,
                turn_index=turn_index,
                active_artifacts=artifacts,
                allow_generation=True,
            )
        )
        rubric_evaluation = self.rubric_evaluation_record(
            generation,
            artifacts,
            submission_id,
            dispatch_preflight,
            fixed_original_score,
        )
        rubric_evaluation_path = (
            self.experiment_dir / "rubric-evaluations" / f"{submission_id}.json"
        )
        if rubric_evaluation_path.exists():
            if _read_json_object(
                rubric_evaluation_path,
                "rubric evaluation",
            ) != rubric_evaluation:
                raise RuntimeError("existing rubric evaluation changed")
        else:
            _write_json_atomic(rubric_evaluation_path, rubric_evaluation)
        has_next_turn = (
            state.stop_reason is None and turn_index < self.config.max_revisions
        )
        feedback = None
        feedback_path = self.experiment_dir / "feedback" / f"{submission_id}.json"
        if has_next_turn:
            feedback = self.project_checkpoint_feedback(
                artifacts=artifacts,
                generation=generation,
                submission_id=submission_id,
                generation_round=generation.generation_round,
                submission_dir=submission_dir,
                allow_generation=True,
                fixed_original_score=fixed_original_score,
                fixed_original_artifacts=fixed_original_artifacts,
            )
            if rubric_evaluation["score"] != feedback.score:
                raise RuntimeError("rubric evaluation and feedback scores disagree")
            if feedback_path.exists():
                if (
                    _read_json_object(feedback_path, "revision feedback")
                    != feedback.payload
                ):
                    raise RuntimeError(
                        "existing feedback disagrees with judge artifacts"
                    )
            else:
                _write_json_atomic(feedback_path, feedback.payload)
        elif os.path.lexists(feedback_path):
            raise RuntimeError("terminal submission must not contain feedback")
        score = float(rubric_evaluation["score"])
        state.scores.append(score)
        state.fixed_original_scores.append(fixed_original_score)
        state.next_prompt = feedback.prompt if feedback is not None else ""
        if has_next_turn:
            state.phase = _RevisionPhase.READY_FOR_TURN
        else:
            if state.stop_reason is None:
                state.stop_reason = "max_revisions"
            state.phase = _RevisionPhase.COMPLETED
        self.store.write_state(state)
        self.store.append_event(
            {
                "event": "submission_judged",
                "submission_id": submission_id,
                "turn": turn_index,
                "judge_attempt_id": attempt_id,
                "score": score,
                "fixed_original_score": fixed_original_score,
                "elicited_penalty": score - fixed_original_score,
                "feedback_policy": FeedbackPolicy(self.config.feedback_policy).value,
                "feedback_sha256": (
                    _sha256_file(feedback_path) if feedback is not None else None
                ),
                "rubric_evaluation_sha256": _sha256_file(rubric_evaluation_path),
                "rubric_generation_round": generation.generation_round,
                "generation_sha256": generation.generation_sha256,
                "rubric_sha256": generation.rubric.content_sha256,
            }
        )

    def ensure_online_rubric_generation(self, turn_index: int) -> None:
        """Create an online rubric only when a new submission needs it."""

        if self.rubric_policy is not RubricPolicy.ONLINE_ELICITATION:
            return
        generation_round = turn_index - 1
        if generation_round < 1:
            return
        destination = rubric_generation_directory(
            self.experiment_dir, generation_round
        )
        if destination.is_dir() and not destination.is_symlink():
            return
        proposer = self.dependencies.rubric_proposer
        if proposer is None:
            raise RuntimeError("online elicitation has no rubric proposer")
        current = load_rubric_generation(
            self.experiment_dir,
            generation_round - 1,
            expected_policy=self.rubric_policy,
        )
        generation = proposer.elicit_rubric(
            instruction=(self.task_dir / "instruction.md").read_text(),
            original_rubric=CompleteRubric.from_content(self.initial_rubric.text),
            current_generation=current,
            policy=self.rubric_policy,
            generation_round=generation_round,
            artifact_history=self.elicitation_history(generation_round),
            source_checkpoint=generation_round,
            output_dir=self.experiment_dir,
        )
        generation.validate_successor(current)

    def rubric_evaluation_record(
        self,
        generation: RubricGeneration,
        artifacts: JudgeArtifacts,
        submission_id: str,
        dispatch_preflight: dict[str, object],
        fixed_original_score: float,
    ) -> dict[str, object]:
        if (
            dispatch_preflight.get("generation_sha256")
            != generation.generation_sha256
            or dispatch_preflight.get("rubric_sha256")
            != generation.rubric.content_sha256
        ):
            raise RuntimeError("rubric dispatch has the wrong generation binding")
        composition = compose_rubric_score(
            generation,
            artifacts.score_validation_path,
            fixed_original_score,
        )
        validation = _read_json_object(
            artifacts.score_validation_path,
            "rubric score validation",
        )
        judge_score = validation.get("score")
        if (
            isinstance(judge_score, bool)
            or not isinstance(judge_score, Real)
            or not math.isfinite(float(judge_score))
            or not 0 <= float(judge_score) <= 100
        ):
            raise RuntimeError("rubric judgment has an invalid score")
        if (
            validation.get("review_input_sha256")
            != dispatch_preflight.get("review_text_sha256")
            or validation.get("answer_input_sha256")
            != dispatch_preflight.get("answer_text_sha256")
        ):
            raise RuntimeError("rubric score uses a different dispatch payload")
        return {
            "kind": "canonical-original-plus-elicited-penalty-evaluation",
            "submission_id": submission_id,
            "generation_round": generation.generation_round,
            "generation_sha256": generation.generation_sha256,
            "rubric_sha256": generation.rubric.content_sha256,
            "dispatch_preflight": dispatch_preflight,
            "judge_score": judge_score,
            "canonical_original_score": composition.canonical_original_score,
            "elicited_penalty": composition.elicited_penalty,
            "score_validation_sha256": _sha256_file(
                artifacts.score_validation_path
            ),
            "evaluation_sha256": _sha256_file(artifacts.evaluation_path),
            "score": composition.score,
        }

    def project_checkpoint_feedback(
        self,
        *,
        artifacts: JudgeArtifacts,
        generation: RubricGeneration,
        submission_id: str,
        generation_round: int,
        submission_dir: Path,
        allow_generation: bool,
        fixed_original_score: float,
        fixed_original_artifacts: JudgeArtifacts,
    ):
        policy = FeedbackPolicy(self.config.feedback_policy)
        if policy is not FeedbackPolicy.USER_SIMULATOR:
            return project_rubric_feedback(
                generation,
                (artifacts.score_validation_path, artifacts.evaluation_path),
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
        checkpoint = int(submission_id[1:])
        history = build_simulated_user_history(
            self.experiment_dir,
            self.benchmark,
            checkpoint,
        )
        current_artifact = self.benchmark.render_user_review(
            submission_dir / "workspace"
        )
        summary_path = (
            self.experiment_dir
            / "feedback-history-summaries"
            / f"{submission_id}.json"
        )
        history_summary: dict[str, object] | None = None
        if simulator.history_requires_summary(history):
            if summary_path.is_symlink():
                raise RuntimeError(
                    f"simulated-user history summary is a symlink: {summary_path}"
                )
            if summary_path.is_file():
                history_summary = _read_json_object(
                    summary_path,
                    "simulated-user history summary",
                )
            else:
                if os.path.lexists(summary_path):
                    raise RuntimeError(
                        "simulated-user history summary is not a regular file: "
                        f"{summary_path}"
                    )
                if not allow_generation:
                    raise RuntimeError(
                        f"missing simulated-user history summary for {submission_id}"
                    )
                history_summary = simulator.generate_history_summary(
                    experiment_id=self.config.experiment_id,
                    assignment_id=self.config.assignment_id,
                    submission_id=submission_id,
                    history=history,
                )
                _write_json_atomic(summary_path, history_summary)
            simulator.validate_history_summary(
                history_summary,
                experiment_id=self.config.experiment_id,
                assignment_id=self.config.assignment_id,
                submission_id=submission_id,
                history=history,
            )
        elif os.path.lexists(summary_path):
            raise RuntimeError(
                f"unexpected simulated-user history summary for {submission_id}"
            )
        generation_path = (
            self.experiment_dir
            / "feedback-generations"
            / f"{submission_id}.json"
        )
        if generation_path.is_symlink():
            raise RuntimeError(
                f"simulated-user generation is an invalid symlink: {generation_path}"
            )
        if generation_path.is_file():
            simulated_record = _read_json_object(
                generation_path,
                "simulated-user generation",
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
            simulated_record = simulator.generate(
                experiment_id=self.config.experiment_id,
                assignment_id=self.config.assignment_id,
                submission_id=submission_id,
                generation_round=generation_round,
                instruction=(self.task_dir / "instruction.md").read_text(
                    encoding="utf-8"
                ),
                generation=generation,
                current_artifact=current_artifact,
                history=history,
                history_summary=history_summary,
            )
            _write_json_atomic(generation_path, simulated_record)
        user_feedback = simulator.validate(
            simulated_record,
            experiment_id=self.config.experiment_id,
            assignment_id=self.config.assignment_id,
            submission_id=submission_id,
            generation_round=generation_round,
            generation=generation,
            current_artifact=current_artifact,
            history=history,
            history_summary=history_summary,
        )
        return project_rubric_simulated_user_feedback(
            generation,
            artifacts.score_validation_path,
            user_feedback,
            fixed_original_score=fixed_original_score,
            prompt_profile=self.config.prompt_profile,
            benchmark=self.config.benchmark,
        )

    def publish_final_plot(
        self,
        state: _RevisionState,
        submission_id: str,
    ) -> None:
        """Create the final PNG plot without changing the completed run."""
        try:
            write_revision_score_plot(
                state.scores,
                state.fixed_original_scores,
                self.experiment_dir / "score_improvement.png",
                task_id=self.task_dir.name,
                feedback_policy=FeedbackPolicy(self.config.feedback_policy).value,
            )
        except Exception as exc:
            self.store.append_event(
                {
                    "event": "plot_publication_failed",
                    "submission_id": submission_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc) or type(exc).__name__,
                }
            )

    def active_rubric_generation(self, checkpoint: int) -> RubricGeneration:
        generation_round = (
            0
            if self.rubric_policy is RubricPolicy.FIXED
            else (
                1
                if self.rubric_policy is RubricPolicy.OFFLINE_ELICITATION
                else max(0, checkpoint - 1)
            )
        )
        generation = load_rubric_generation(
            self.experiment_dir,
            generation_round,
            expected_policy=self.rubric_policy,
        )
        if generation_round > 0:
            prior = load_rubric_generation(
                self.experiment_dir,
                generation_round - 1,
                expected_policy=self.rubric_policy,
            )
            generation.validate_successor(prior)
        return generation

    def elicitation_history(self, generation_round: int):
        """Return the complete blinded history for one rubric update."""

        return build_elicitation_artifact_history(
            online=self.rubric_policy is RubricPolicy.ONLINE_ELICITATION,
            seed_set=self.config.seed_run_dir,
            task_dir=self.task_dir,
            experiment_dir=self.experiment_dir,
            benchmark=self.benchmark,
            provider=self.config.agent.provider,
            requested_model=self.config.agent.model,
            prompt_profile=self.config.prompt_profile,
            seed_replicates=self.config.elicitation_seed_replicates,
            assignment_id=self.config.assignment_id,
            generation_round=generation_round,
        )

    @staticmethod
    def frozen_generated_rubric(text: str, rubric_sha256: str) -> FrozenRubric:
        """Return the judge identity for one generated rubric."""
        return FrozenRubric(
            text=text, sha256=rubric_sha256, source=RUBRIC_PATH_SOURCE,
            rubric_set_id=None, rubric_id=None,
            structured_rubric_sha256=None, manifest_sha256=None,
        )

    def rubric_runtime(
        self,
        generation: RubricGeneration,
    ) -> tuple[FrozenRubric, object]:
        if generation.rubric.content_sha256 == self.initial_rubric.sha256:
            return self.initial_rubric, self.dependencies.judge
        path = (
            rubric_generation_directory(
                self.experiment_dir,
                generation.generation_round,
            )
            / "rubric.txt"
        )
        rubric = self.frozen_generated_rubric(
            generation.rubric.content,
            generation.rubric.content_sha256,
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
        active_artifacts: JudgeArtifacts,
        allow_generation: bool,
    ) -> tuple[float, JudgeArtifacts]:
        active_generation = self.active_rubric_generation(turn_index)
        seeded = False
        if turn_index == 0 and self.reuse_seed_master_judgment:
            validation_path, evaluation_path, _ = self.seed.judgment
            artifacts = JudgeArtifacts(validation_path, evaluation_path)
            seeded = True
        elif (
            active_generation.rubric.content_sha256 == self.master_rubric.sha256
            and (
                turn_index == 0
                or self.rubric_policy is RubricPolicy.FIXED
            )
        ):
            artifacts = active_artifacts
        else:
            attempt_id = fixed_original_attempt_id(
                self.config.assignment_id,
                submission_id,
                self.master_rubric.sha256,
            )
            artifacts = self.assignment_judgment(
                judge=self.master_judge,
                submission_dir=submission_dir,
                submission_id=submission_id,
                rubric_sha256=self.master_rubric.sha256,
                attempt_id=attempt_id,
                allow_generation=allow_generation,
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
            self.rubric_policy is RubricPolicy.FIXED
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

    def validate_latest_checkpoint(self, state: _RevisionState) -> None:
        """Validate only the latest completed score needed for resume."""

        if not state.scores:
            return
        index = len(state.scores) - 1
        submission_id = f"s{index:03d}"
        submission_dir = self.experiment_dir / "submissions" / submission_id
        _verify_submission_snapshot(submission_dir)
        attempt_id = state.judge_attempts.get(submission_id)
        if attempt_id is None:
            raise RuntimeError("scored submission has no judge attempt identity")
        generation = self.active_rubric_generation(index)
        rubric, judge = self.rubric_runtime(generation)
        seeded = (
            index == 0
            and generation.rubric.content_sha256 == self.initial_rubric.sha256
            and self.reuse_seed_judgment
        )
        if seeded:
            validation_path, evaluation_path, _ = self.seed.judgment
            artifacts = JudgeArtifacts(validation_path, evaluation_path)
        else:
            artifacts = self.assignment_judgment(
                judge=judge,
                submission_dir=submission_dir,
                submission_id=submission_id,
                rubric_sha256=generation.rubric.content_sha256,
                attempt_id=attempt_id,
                allow_generation=False,
            )
        self.verify_round_scoring_identity(
            artifacts.score_validation_path,
            rubric,
            judge,
            seeded=seeded,
        )
        expected_fixed_score, fixed_original_artifacts = self.fixed_original_judgment(
            submission_dir=submission_dir,
            submission_id=submission_id,
            turn_index=index,
            active_artifacts=artifacts,
            allow_generation=False,
        )
        rubric_evaluation = _read_json_object(
            self.experiment_dir
            / "rubric-evaluations"
            / f"{submission_id}.json",
            "rubric evaluation",
        )
        review_text, answer_text = self.dependencies.judge.review_inputs(
            submission_dir
        )
        expected_rubric_evaluation = self.rubric_evaluation_record(
            generation,
            artifacts,
            submission_id,
            preflight_generation_dispatch(
                generation,
                benchmark=self.config.benchmark,
                review_text=review_text,
                answer_text=answer_text,
            ),
            expected_fixed_score,
        )
        if rubric_evaluation != expected_rubric_evaluation:
            raise RuntimeError(
                "stored rubric evaluation disagrees with judge artifacts"
            )
        if expected_rubric_evaluation["score"] != state.scores[index]:
            raise RuntimeError("stored score disagrees with judge artifacts")
        feedback_path = self.experiment_dir / "feedback" / f"{submission_id}.json"
        following_turn = (
            self.experiment_dir
            / "turns"
            / f"turn-{index + 1:03d}"
        )
        feedback_is_actionable = (
            following_turn.is_dir() and not following_turn.is_symlink()
        ) or (
            state.phase is _RevisionPhase.READY_FOR_TURN
            and index == len(state.scores) - 1
        )
        if feedback_is_actionable:
            projected = self.project_checkpoint_feedback(
                artifacts=artifacts,
                generation=generation,
                submission_id=submission_id,
                generation_round=generation.generation_round,
                submission_dir=submission_dir,
                allow_generation=False,
                fixed_original_score=expected_fixed_score,
                fixed_original_artifacts=fixed_original_artifacts,
            )
            feedback = _read_json_object(feedback_path, "revision feedback")
            if (
                projected.score != state.scores[index]
                or feedback != projected.payload
            ):
                raise RuntimeError(
                    "stored feedback disagrees with validated judge artifacts"
                )
        elif os.path.lexists(feedback_path):
            raise RuntimeError("terminal submission must not contain feedback")
        if expected_fixed_score != state.fixed_original_scores[index]:
            raise RuntimeError(
                "stored fixed-original score disagrees with judge artifacts"
            )
