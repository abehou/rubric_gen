"""Stateful controller for linear benchmark submission revision."""

from __future__ import annotations

import hashlib
import math
import os
import json
import secrets
import re
import shutil
import stat
import tempfile
from dataclasses import replace
from pathlib import Path
from numbers import Real

from tqdm.auto import trange

from rubric_gen.submission_revision.prompts import PromptProfile, solver_prompt
from rubric_gen.runtime.agents.sessions import CliSolverSessionDriver
from rubric_gen.runtime.agents.workspaces import (
    TaskWorkspace,
    ensure_artifacts_dir,
)
from rubric_gen.submission_revision.judging.models import (
    DEFAULT_JUDGE_MODEL,
    RUBRIC_PATH_SOURCE,
)
from rubric_gen.runtime.progress import PROGRESS_BAR_FORMAT
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    project_bank_feedback,
    project_bank_simulated_user_feedback,
)
from rubric_gen.submission_revision.bank_scoring import preflight_bank_dispatch
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    RevisionPhase as _RevisionPhase,
    RevisionState as _RevisionState,
    SubmissionRevisionConfig,
    SubmissionRevisionResult,
)
from rubric_gen.submission_revision.artifacts import (
    LIVE_ROOT_PREFIX as _LIVE_ROOT_PREFIX,
    live_root_parent as _live_root_parent,
    is_excluded_solution_root as _is_excluded_solution_root,
    link_solution_workspace as _link_solution_workspace,
    REVISION_EXPERIMENT_KIND as _REVISION_EXPERIMENT_KIND,
    compact_historical_workspace as _compact_historical_workspace,
    copy_solution_workspace as _copy_solution_workspace,
    make_read_only as _make_read_only,
    make_tree_owner_writable as _make_tree_owner_writable,
    make_tree_read_only as _make_tree_read_only,
    read_json_object as _read_json_object,
    revision_manifest_keys as _revision_manifest_keys,
    remove_created_live_tree as _remove_created_live_tree,
    remove_live_tree as _remove_tree,
    sha256_file as _sha256_file,
    solution_tree_sha256 as _solution_tree_sha256,
    tree_sha256 as _tree_sha256,
    validate_live_root as _validate_live_root,
    verify_submission_snapshot as _verify_submission_snapshot,
    write_json as _write_json,
    write_live_root_sentinel as _write_live_root_sentinel,
)
from rubric_gen.artifacts.serialization import (
    write_json_atomic as _write_json_atomic,
)
from rubric_gen.submission_revision.judge import (
    SCORING_IDENTITY_KEYS as _SCORING_IDENTITY_KEYS,
    FrozenRubricJudge,
    FrozenRubric,
    JudgeArtifacts as JudgeArtifacts,
    resolve_optimizer_rubric as _resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.judgment_reuse import (
    ExactJudgmentReuseStore,
    ExactSimulatorReuseStore,
    exact_judgment_request,
    exact_simulator_request,
)
from rubric_gen.submission_revision.evolution import (
    RubricBankProposer,
    rubric_generation_implementation_identity,
)
from rubric_gen.submission_revision.contrasts import (
    build_elicitation_contrasts,
)
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    RubricBank,
    RubricBankGeneration,
    RubricBankItem,
    RubricBankPolicy,
    RubricLineage,
    identity_criterion_map,
    load_rubric_bank,
    persist_rubric_bank,
    rubric_bank_directory,
)
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback
from rubric_gen.submission_revision.seeds import ResolvedSeed, resolve_seed
from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.submission_revision.store import (
    RevisionStore,
    extract_judge_execution_contract as _extract_judge_execution_contract,
    extract_scoring_identity as _extract_scoring_identity,
    extract_seed_scoring_contract as _extract_seed_scoring_contract,
)
from rubric_gen.submission_revision.reports import publish_revision_report
from rubric_gen.submission_revision.visualization.revisions import write_revision_score_plot


class _SolverTurnFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def fixed_original_attempt_id(
    assignment_id: str,
    submission_id: str,
    rubric_sha256: str,
) -> str:
    """Return the deterministic attempt ID for a fixed-original cross-score."""
    return hashlib.sha256(
        (
            "fixed-original\0"
            + assignment_id
            + "\0"
            + submission_id
            + "\0"
            + rubric_sha256
        ).encode("utf-8")
    ).hexdigest()[:32]


def _numbered_bank_directories(
    root: Path,
    *,
    required: bool,
    context: str,
) -> list[int]:
    """Return strict canonical bank directory numbers."""

    if not os.path.lexists(root):
        if required:
            raise RuntimeError(f"{context} root is missing")
        return []
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"{context} root is invalid")
    rounds: list[int] = []
    for path in root.iterdir():
        name = path.name
        if (
            path.is_symlink()
            or not path.is_dir()
            or len(name) != 9
            or not name.startswith("bank-")
            or not name[5:].isdigit()
        ):
            raise RuntimeError(f"{context} root contains an invalid entry")
        rounds.append(int(name[5:]))
    if len(set(rounds)) != len(rounds):
        raise RuntimeError(f"{context} root contains duplicate rounds")
    return sorted(rounds)


def _rubric_generation_entries(
    root: Path,
) -> tuple[list[int], list[int]]:
    """Return generation and provider-ledger rounds."""

    if not os.path.lexists(root):
        return [], []
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("rubric generation root is invalid")
    rounds: list[int] = []
    ledger_rounds: list[int] = []
    for path in root.iterdir():
        name = path.name
        if (
            not path.is_symlink()
            and path.is_dir()
            and len(name) == 9
            and name.startswith("bank-")
            and name[5:].isdigit()
        ):
            rounds.append(int(name[5:]))
            continue
        prefix = "bank-"
        ledger_suffix = ".provider-attempts.json"
        ledger_digits = name[len(prefix):-len(ledger_suffix)] if (
            name.startswith(prefix) and name.endswith(ledger_suffix)
        ) else ""
        if (
            not path.is_symlink()
            and path.is_file()
            and len(ledger_digits) == 4
            and ledger_digits.isdigit()
        ):
            ledger_rounds.append(int(ledger_digits))
            continue
        raise RuntimeError("rubric generation root contains an invalid entry")
    if len(set(rounds)) != len(rounds):
        raise RuntimeError("rubric generation root contains duplicate rounds")
    if len(set(ledger_rounds)) != len(ledger_rounds):
        raise RuntimeError("rubric generation root contains duplicate ledgers")
    if not set(rounds) <= set(ledger_rounds):
        raise RuntimeError("rubric generation lacks its provider attempt ledger")
    return sorted(rounds), sorted(ledger_rounds)


_LEDGER_ATOMIC_TEMP = re.compile(
    r"^\.bank-([0-9]{4})\.provider-attempts\.json\.[a-z0-9_]{8}\.tmp$"
)
_GENERATION_STAGING_DIRECTORY = re.compile(
    r"^\.bank-([0-9]{4})\.[a-z0-9_]{8}$"
)


def _remove_owned_rubric_generation_residue(
    root: Path,
    *,
    max_generation_round: int,
) -> None:
    """Remove only interrupted atomic writes and generation staging trees."""

    if not os.path.lexists(root):
        return
    root_stat = os.lstat(root)
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise RuntimeError("rubric generation root is invalid")
    changed = False
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        ledger_match = _LEDGER_ATOMIC_TEMP.fullmatch(path.name)
        stage_match = _GENERATION_STAGING_DIRECTORY.fullmatch(path.name)
        match = ledger_match or stage_match
        if match is None or not 1 <= int(match.group(1)) <= max_generation_round:
            continue
        path_stat = os.lstat(path)
        if ledger_match is not None:
            if not stat.S_ISREG(path_stat.st_mode):
                raise RuntimeError(
                    "rubric generation temporary path is not a regular file"
                )
            path.unlink()
            changed = True
            continue
        if not stat.S_ISDIR(path_stat.st_mode):
            raise RuntimeError(
                "rubric generation staging path is not a directory"
            )
        descendants = [path, *path.rglob("*")]
        for descendant in descendants:
            descendant_stat = os.lstat(descendant)
            if not (
                stat.S_ISDIR(descendant_stat.st_mode)
                or stat.S_ISREG(descendant_stat.st_mode)
            ):
                raise RuntimeError(
                    "rubric generation staging tree contains a non-regular entry"
                )
        for descendant in descendants:
            descendant_stat = os.lstat(descendant)
            additions = stat.S_IRUSR | stat.S_IWUSR
            if stat.S_ISDIR(descendant_stat.st_mode):
                additions |= stat.S_IXUSR
            descendant.chmod(stat.S_IMODE(descendant_stat.st_mode) | additions)
        shutil.rmtree(path)
        changed = True
    if changed:
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


class SubmissionRevisionController:
    """Run a fixed-length linear revision conversation for one task."""

    def __init__(
        self,
        config: SubmissionRevisionConfig,
        dependencies: RevisionDependencies | None = None,
        *,
        judgment_reuse_root: Path | None = None,
    ) -> None:
        self.config = config
        self.benchmark = get_submission_benchmark(config.benchmark)
        self.experiment_dir = Path(config.experiment_dir).resolve()
        self.task_dir = Path(config.task_dir).resolve()
        self.judgment_reuse = (
            ExactJudgmentReuseStore(judgment_reuse_root / "judge")
            if judgment_reuse_root is not None
            else None
        )
        self.simulator_reuse = (
            ExactSimulatorReuseStore(judgment_reuse_root / "simulated-user")
            if judgment_reuse_root is not None
            else None
        )
        judge_config = config.judge_config()
        self.initial_rubric = _resolve_optimizer_rubric(judge_config)
        self.bank_policy = RubricBankPolicy(
            RubricBankPolicy(config.rubric_policy).value
        )
        initial_complete_rubric = CompleteRubric.from_content(
            self.initial_rubric.text
        )
        self.initial_bank = RubricBankGeneration(
            RubricBank(
                generation_round=0,
                source_boundary=None,
                specification_anchor=initial_complete_rubric,
                specification_anchor_lineage=RubricLineage.NEW,
                prior_specification_anchor_sha256=None,
                items=(RubricBankItem(
                    rubric=initial_complete_rubric,
                    weight=1.0,
                    lineage=RubricLineage.NEW,
                    criterion_map=identity_criterion_map(initial_complete_rubric),
                ),),
            ),
            proposer_call_budget=0,
        )
        master_judge_config = config.master_judge_config()
        self.master_rubric = _resolve_optimizer_rubric(master_judge_config)
        self.instruction_sha256 = _sha256_file(self.task_dir / "instruction.md")
        self.data_sha256 = _tree_sha256(self.task_dir / "environment" / "data")
        self.seed: ResolvedSeed = resolve_seed(
            config.seed_run_dir,
            self.task_dir,
            config.replicate,
            provider=config.agent.provider,
            requested_model=config.agent.model,
        )
        self.dependencies = dependencies or RevisionDependencies(
            session=CliSolverSessionDriver(config.agent, contract=self.benchmark),
            judge=FrozenRubricJudge(judge_config, self.initial_rubric),
            master_judge=FrozenRubricJudge(
                master_judge_config,
                self.master_rubric,
            ),
            bank_proposer=(
                None if self.bank_policy is RubricBankPolicy.FIXED
                else RubricBankProposer(
                    benchmark=config.benchmark,
                    model=config.rubric_proposer_model,
                    base_url=config.rubric_proposer_base_url,
                    semantic_judge_model=config.rubric_semantic_judge_model,
                    semantic_judge_base_url=(
                        config.rubric_semantic_judge_base_url
                    ),
                    semantic_judge_max_calls=(
                        config.rubric_semantic_judge_max_calls
                    ),
                    semantic_judge_max_request_bytes=(
                        config.rubric_semantic_judge_max_request_bytes
                    ),
                    semantic_judge_max_output_tokens=(
                        config.rubric_semantic_judge_max_output_tokens
                    ),
                    service_tier=(
                        config.agent.service_tier
                        if config.rubric_proposer_base_url is None else None
                    ),
                    max_retries=config.rubric_proposer_max_retries,
                )
            ),
            feedback_simulator=(
                SimulatedUserFeedback(config.feedback_simulator)
                if config.feedback_simulator is not None
                else None
            ),
        )
        if (
            self.bank_policy is not RubricBankPolicy.FIXED
            and self.dependencies.bank_proposer is None
        ):
            raise ValueError("an elicitation policy requires a rubric proposer")
        if (
            self.bank_policy is not RubricBankPolicy.FIXED
            and self.dependencies.bank_proposer is not None
            and (
                self.dependencies.bank_proposer.benchmark is not config.benchmark
                or self.dependencies.bank_proposer.model
                != config.rubric_proposer_model
                or self.dependencies.bank_proposer.base_url
                != config.rubric_proposer_base_url
                or self.dependencies.bank_proposer.max_retries
                != config.rubric_proposer_max_retries
                or self.dependencies.bank_proposer.service_tier
                != (
                    config.agent.service_tier
                    if config.rubric_proposer_base_url is None else None
                )
                or self.dependencies.bank_proposer.semantic_judge_model
                != config.rubric_semantic_judge_model
                or self.dependencies.bank_proposer.semantic_judge_base_url
                != config.rubric_semantic_judge_base_url
                or self.dependencies.bank_proposer.semantic_judge_max_calls
                != config.rubric_semantic_judge_max_calls
                or self.dependencies.bank_proposer.semantic_judge_max_request_bytes
                != config.rubric_semantic_judge_max_request_bytes
                or self.dependencies.bank_proposer.semantic_judge_max_output_tokens
                != config.rubric_semantic_judge_max_output_tokens
            )
        ):
            raise ValueError("bank proposer contract differs from revision config")
        if FeedbackPolicy(config.feedback_policy) is FeedbackPolicy.USER_SIMULATOR:
            if self.dependencies.feedback_simulator is None:
                raise ValueError(
                    "user_simulator feedback requires a feedback simulator"
                )
            assert config.feedback_simulator is not None
            if (
                self.dependencies.feedback_simulator.identity()
                != config.feedback_simulator.identity()
            ):
                raise ValueError(
                    "feedback simulator identity differs from revision config"
                )
        elif self.dependencies.feedback_simulator is not None:
            raise ValueError(
                "feedback simulator dependency is only valid for user_simulator"
            )
        self.master_judge = self.dependencies.master_judge or self.dependencies.judge
        reported_scoring_identity = self.dependencies.judge.scoring_identity()
        if set(reported_scoring_identity) != set(_SCORING_IDENTITY_KEYS):
            raise RuntimeError(
                "submission judge returned an incomplete scoring identity"
            )
        self.scoring_identity = _extract_scoring_identity(
            reported_scoring_identity,
            context="submission judge",
        )
        if (
            self.scoring_identity["rendered_rubric_sha256"]
            != self.initial_rubric.sha256
        ):
            raise RuntimeError("submission judge resolved a different optimizer rubric")
        reported_master_identity = self.master_judge.scoring_identity()
        if set(reported_master_identity) != set(_SCORING_IDENTITY_KEYS):
            raise RuntimeError("master rubric judge returned an incomplete identity")
        self.master_scoring_identity = _extract_scoring_identity(
            reported_master_identity,
            context="master rubric judge",
        )
        if (
            self.master_scoring_identity["rendered_rubric_sha256"]
            != self.master_rubric.sha256
        ):
            raise RuntimeError("master rubric judge resolved a different rubric")
        _, _, seed_scoring_identity = self.seed.judgment
        seed_contract = _extract_seed_scoring_contract(
            seed_scoring_identity,
            context="seeded initial judgment",
        )
        optimizer_contract = _extract_seed_scoring_contract(
            self.scoring_identity,
            context="submission judge",
        )
        master_contract = _extract_seed_scoring_contract(
            self.master_scoring_identity,
            context="master rubric judge",
        )
        self.reuse_seed_judgment = seed_contract == optimizer_contract
        self.reuse_seed_master_judgment = seed_contract == master_contract
        seed_execution = _extract_judge_execution_contract(
            seed_contract,
            context="seeded initial judgment",
        )
        if seed_execution != _extract_judge_execution_contract(
            optimizer_contract,
            context="optimizer judge",
        ) or seed_execution != _extract_judge_execution_contract(
            master_contract,
            context="master judge",
        ):
            raise RuntimeError(
                "seeded initial judgment uses a different scoring contract for "
                "judge execution"
            )
        self.store = RevisionStore(
            self.experiment_dir,
            initial_bank=self.initial_bank,
            bank_policy=self.bank_policy,
            scoring_identity=self.scoring_identity,
        )

    def _experiment_identity(self) -> dict[str, object]:
        identity: dict[str, object] = {
            "experiment_id": self.config.experiment_id,
            "benchmark": str(self.config.benchmark),
            "assignment_id": self.config.assignment_id,
            "condition_id": self.config.condition_id,
            "replicate": self.config.replicate,
            "execution_order": self.config.execution_order,
            "task_id": self.task_dir.name,
            "task_dir": str(self.task_dir),
            "revision_rounds": self.config.revision_rounds,
            "provider": self.config.agent.provider,
            "model": self.config.agent.model,
            "executable": self.config.agent.executable,
            "isolation": "codex-custom-permission-profile",
            "command_network_access": False,
            "web_search": False,
            "reasoning_effort": self.config.agent.reasoning_effort,
            "service_tier": self.config.agent.service_tier,
            "solver_base_url": self.config.agent.base_url,
            "turn_timeout_seconds": self.config.agent.timeout_seconds,
            "judge_max_retries": self.config.judge_max_retries,
            "feedback_policy": FeedbackPolicy(self.config.feedback_policy).value,
            "prompt": PromptProfile(self.config.prompt_profile).value,
            "rubric_policy": self.bank_policy.value,
            "rubric_proposer_model": self.config.rubric_proposer_model,
            "rubric_proposer_base_url": self.config.rubric_proposer_base_url,
            "rubric_proposer_max_retries": self.config.rubric_proposer_max_retries,
            "rubric_semantic_judge_model": (
                self.config.rubric_semantic_judge_model
            ),
            "rubric_semantic_judge_base_url": (
                self.config.rubric_semantic_judge_base_url
            ),
            "rubric_semantic_judge_max_calls": (
                self.config.rubric_semantic_judge_max_calls
            ),
            "rubric_semantic_judge_max_request_bytes": (
                self.config.rubric_semantic_judge_max_request_bytes
            ),
            "rubric_semantic_judge_max_output_tokens": (
                self.config.rubric_semantic_judge_max_output_tokens
            ),
            "rubric_generation_implementation_identity": (
                rubric_generation_implementation_identity()
            ),
            "review": self.config.review,
            "judge_model": self.config.judge_model,
            "judge_base_url": self.config.judge_base_url,
            "max_review_chars": self.config.max_review_chars,
            "initial_rubric_path": str(
                self.config.optimizer_rubric_path.resolve()
            ),
            "initial_bank_sha256": self.initial_bank.bank.content_sha256,
            "initial_bank_member_count": self.initial_bank.bank.rubric_count,
            "master_rubric_name": self.config.master_rubric_name,
            "master_rubric_sha256": self.master_rubric.sha256,
            "instruction_sha256": self.instruction_sha256,
            "data_sha256": self.data_sha256,
            "seed_run_dir": str(self.seed.root),
            "seed_sha256": self.seed.sha256,
        }
        if self.config.feedback_simulator is not None:
            identity["feedback_simulator"] = self.config.feedback_simulator.identity()
        return identity

    def run(self) -> SubmissionRevisionResult:
        initialized = False
        completed = False
        if self.config.resume:
            state, live_root, workspace = self._load_resume()
            initialized = True
        else:
            if os.path.lexists(self.experiment_dir):
                raise FileExistsError(
                    f"experiment directory already exists: {self.experiment_dir}"
                )
            live_root = Path(
                tempfile.mkdtemp(
                    prefix=_LIVE_ROOT_PREFIX,
                    dir=_live_root_parent(),
                )
            )
            try:
                _write_live_root_sentinel(live_root, self.experiment_dir)
            except BaseException:
                _remove_created_live_tree(live_root)
                raise
            workspace = live_root / "workspace"
            state = _RevisionState(
                phase=_RevisionPhase.READY_FOR_JUDGE,
                next_turn_index=1,
                session_id=None,
                effective_solver_model=None,
                submission_ids=["s000"],
                scores=[],
                fixed_original_scores=[],
                judge_attempts={},
                next_prompt=solver_prompt(
                    self.config.prompt_profile,
                    self.config.benchmark,
                ),
            )
        try:
            if not initialized:
                TaskWorkspace(self.task_dir, workspace).validate()
                self._initialize(workspace, live_root, state)
                initialized = True
            total = self.config.revision_rounds + 1
            if state.phase in {
                _RevisionPhase.TURN_IN_PROGRESS,
                _RevisionPhase.FAILED_TURN,
            }:
                raise RuntimeError(
                    "experiment cannot resume an uncertain or failed solver turn"
                )
            progress_initial = len(state.scores)
            turns = (
                trange(
                    progress_initial,
                    total,
                    initial=progress_initial,
                    total=total,
                    desc=(
                        f"revise {self.task_dir.name} "
                        f"[{FeedbackPolicy(self.config.feedback_policy).value}]"
                    ),
                    unit="round",
                    dynamic_ncols=True,
                    bar_format=PROGRESS_BAR_FORMAT,
                    position=self.config.progress_position,
                    leave=self.config.progress_position is None,
                )
                if self.config.show_progress
                else range(progress_initial, total)
            )
            for _ in turns:
                if state.phase is _RevisionPhase.READY_FOR_TURN:
                    self._run_solver_turn(state, workspace)
                if state.phase in {
                    _RevisionPhase.READY_FOR_JUDGE,
                    _RevisionPhase.JUDGE_IN_PROGRESS,
                }:
                    self._run_judge_boundary(state)
                if state.phase not in {
                    _RevisionPhase.READY_FOR_TURN,
                    _RevisionPhase.COMPLETED,
                }:
                    raise RuntimeError(f"invalid revision state: {state.phase}")
            self._validate_scored_boundaries(state)
            state.phase = _RevisionPhase.COMPLETED
            self._write_state(state)
            compaction = self._compact_historical_submissions(state)
            self._append_event(
                {
                    "event": "experiment_completed",
                    "session_id": state.session_id,
                    "submission_count": len(state.submission_ids),
                    "scores": state.scores,
                    "fixed_original_scores": state.fixed_original_scores,
                    "historical_workspace_files_removed": compaction[0],
                    "historical_workspace_logical_bytes_removed": compaction[1],
                }
            )
            self._publish_progress_report(state, state.submission_ids[-1])
            completed = True
            return SubmissionRevisionResult(
                experiment_dir=self.experiment_dir,
                session_id=state.session_id or "",
                submission_ids=tuple(state.submission_ids),
                scores=tuple(state.scores),
                fixed_original_scores=tuple(state.fixed_original_scores),
            )
        finally:
            if completed or not initialized:
                _remove_tree(live_root, self.experiment_dir)
            if completed:
                self._update_manifest({"live_workspace_removed": True})

    def _initialize(
        self,
        workspace: Path,
        live_root: Path,
        state: _RevisionState,
    ) -> None:
        self.experiment_dir.mkdir(parents=True)
        TaskWorkspace(self.task_dir, workspace).create()
        self._materialize_seed(workspace)
        self._link_seed_snapshot()
        _make_read_only(workspace / "instruction.md")
        _write_json(
            self.experiment_dir / "manifest.json",
            {
                "kind": _REVISION_EXPERIMENT_KIND,
                **self._experiment_identity(),
                "submission_count": self.config.revision_rounds + 1,
                "live_workspace_dir": str(workspace),
                "live_workspace_removed": False,
                "session_id": None,
                "effective_solver_model": None,
                "initial_member_scoring_identity": self.scoring_identity,
            },
        )
        self._persist_initial_bank()
        self._write_state(state)

    def _materialize_seed(self, workspace: Path) -> None:
        source = self.seed.submission_dir / "workspace"
        for child in source.iterdir():
            destination = workspace / child.name
            if destination.exists():
                raise RuntimeError(f"seed conflicts with task workspace: {child.name}")
            if child.is_dir():
                shutil.copytree(child, destination, copy_function=shutil.copyfile)
            else:
                shutil.copyfile(child, destination)
            _make_tree_owner_writable(destination)

    def _link_seed_snapshot(self) -> None:
        source = self.seed.submission_dir
        destination = self.experiment_dir / "submissions" / "s000"
        destination.mkdir(parents=True)
        _link_solution_workspace(source / "workspace", destination / "workspace")
        os.link(source / "trajectory.stream.jsonl", destination / "trajectory.stream.jsonl")
        _write_json(
            destination / "status.json",
            {
                "task": self.task_dir.name,
                "task_dir": str(self.task_dir),
                "workspace_dir": str(destination / "workspace"),
                "provider": self.config.agent.provider,
                "session_id": None,
                "submission_id": "s000",
                "exit_code": 0,
            },
        )
        shutil.copyfile(source / "snapshot.json", destination / "snapshot.json")
        _make_tree_read_only(destination)

    def _load_resume(self) -> tuple[_RevisionState, Path, Path]:
        if not self.experiment_dir.is_dir():
            raise FileNotFoundError(
                f"experiment directory does not exist: {self.experiment_dir}"
            )
        manifest = _read_json_object(
            self.experiment_dir / "manifest.json",
            "revision manifest",
        )
        if set(manifest) != _revision_manifest_keys(self.config.feedback_policy.value):
            raise RuntimeError("revision manifest has invalid fields")
        for key, value in self._experiment_identity().items():
            if manifest.get(key) != value:
                raise RuntimeError(f"resume configuration changed: {key}")
        if manifest.get("initial_member_scoring_identity") != self.scoring_identity:
            raise RuntimeError("resume scoring identity changed")
        workspace_value = manifest.get("live_workspace_dir")
        if type(workspace_value) is not str or not workspace_value:
            raise RuntimeError("revision manifest has no live workspace")
        workspace = Path(workspace_value)
        live_root = workspace.parent
        desired_live_parent = _live_root_parent()
        if (
            os.path.lexists(live_root)
            and live_root.parent.resolve() != desired_live_parent
        ):
            _validate_live_root(live_root, self.experiment_dir)
            relocated_root = desired_live_parent / live_root.name
            if os.path.lexists(relocated_root):
                _validate_live_root(relocated_root, self.experiment_dir)
                _remove_tree(relocated_root, self.experiment_dir)
            shutil.copytree(
                live_root,
                relocated_root,
                symlinks=True,
                copy_function=shutil.copyfile,
            )
            _validate_live_root(relocated_root, self.experiment_dir)
            workspace = relocated_root / "workspace"
            manifest["live_workspace_dir"] = str(workspace)
            try:
                _write_json_atomic(self.experiment_dir / "manifest.json", manifest)
            except BaseException:
                _remove_tree(relocated_root, self.experiment_dir)
                raise
            _remove_tree(live_root, self.experiment_dir)
            live_root = relocated_root
        self._verify_initial_bank()
        self._verify_canonical_task_inputs()
        state = self._read_state()
        if state.phase is _RevisionPhase.COMPLETED:
            self._compact_historical_submissions(state)
        if workspace.name != "workspace" or not workspace.is_absolute():
            raise RuntimeError("revision manifest has an invalid live workspace path")
        if os.path.lexists(live_root):
            _validate_live_root(live_root, self.experiment_dir)
        if workspace.is_symlink() or not workspace.is_dir():
            total = self.config.revision_rounds + 1
            if (
                not os.path.lexists(live_root)
                and state.phase is _RevisionPhase.COMPLETED
                and state.next_turn_index == total
                and len(state.submission_ids)
                == len(state.scores)
                == len(state.fixed_original_scores)
                == total
            ):
                self._validate_resume_state(state, None, manifest)
                return state, live_root, workspace
            if workspace.is_symlink():
                raise RuntimeError(
                    f"live revision workspace is an invalid symlink: {workspace}"
                )
            live_root, workspace = self._rebuild_live_workspace(
                state, live_root, manifest
            )
        self._verify_live_instruction(workspace)
        if state.phase in {
            _RevisionPhase.FAILED_TURN,
            _RevisionPhase.TURN_IN_PROGRESS,
        }:
            self._recover_failed_solver_boundary(state, workspace, manifest)
        self._validate_resume_state(state, workspace, manifest)
        return state, live_root, workspace

    def _rebuild_live_workspace(
        self,
        state: _RevisionState,
        old_live_root: Path,
        manifest: dict[str, object],
    ) -> tuple[Path, Path]:
        if os.path.lexists(old_live_root):
            _validate_live_root(old_live_root, self.experiment_dir)
            _remove_tree(old_live_root, self.experiment_dir)
        live_root = Path(
            tempfile.mkdtemp(prefix=_LIVE_ROOT_PREFIX, dir=_live_root_parent())
        )
        try:
            _write_live_root_sentinel(live_root, self.experiment_dir)
            workspace = live_root / "workspace"
            workspace.mkdir()
            self._restore_last_scored_workspace(state, workspace)
            self._verify_live_instruction(workspace)
            manifest["live_workspace_dir"] = str(workspace)
            manifest["live_workspace_removed"] = False
            self._discard_solver_session(
                state,
                manifest,
                reason="live workspace was rebuilt from a sealed submission",
            )
        except BaseException:
            _remove_created_live_tree(live_root)
            raise
        self._append_event(
            {
                "event": "live_workspace_rebuilt",
                "submission_id": (
                    state.submission_ids[-1] if state.submission_ids else None
                ),
            }
        )
        return live_root, workspace

    def _discard_solver_session(
        self,
        state: _RevisionState,
        manifest: dict[str, object],
        *,
        reason: str,
    ) -> None:
        previous_session_id = state.session_id
        state.session_id = None
        state.effective_solver_model = None
        manifest["session_id"] = None
        manifest["effective_solver_model"] = None
        _write_json_atomic(self.experiment_dir / "manifest.json", manifest)
        self._write_state(state)
        if previous_session_id is not None:
            self._append_event(
                {
                    "event": "solver_session_discarded",
                    "session_id": previous_session_id,
                    "reason": reason,
                }
            )

    def _recover_failed_solver_boundary(
        self,
        state: _RevisionState,
        workspace: Path,
        manifest: dict[str, object],
    ) -> None:
        """Recover a solver interruption from the last sealed boundary."""
        turn_index = state.next_turn_index
        if not 0 <= turn_index < self.config.revision_rounds + 1:
            raise RuntimeError("failed revision state has an invalid turn index")
        expected_submission_ids = [f"s{index:03d}" for index in range(turn_index)]
        if (
            state.submission_ids != expected_submission_ids
            or len(state.scores) != turn_index
            or len(state.fixed_original_scores) != turn_index
            or set(state.judge_attempts) != set(state.submission_ids)
        ):
            raise RuntimeError("failed revision state boundary counts are inconsistent")
        self._validate_scored_boundaries(state)

        turn_dir = self.experiment_dir / "turns" / f"turn-{turn_index:03d}"
        expected_turns = [
            self.experiment_dir / "turns" / f"turn-{index:03d}"
            for index in range(1, turn_index + 1)
        ]
        if sorted((self.experiment_dir / "turns").glob("turn-*")) != expected_turns:
            raise RuntimeError("experiment contains an uncertain failed solver turn")
        prompt_path = turn_dir / "prompt.txt"
        if (
            prompt_path.is_symlink()
            or not prompt_path.is_file()
            or prompt_path.read_text() != state.next_prompt
        ):
            raise RuntimeError(
                "failed revision state prompt disagrees with the executed turn"
            )
        status_path = turn_dir / "status.json"
        trajectory_path = turn_dir / "trajectory.stream.jsonl"
        if (
            state.phase is _RevisionPhase.TURN_IN_PROGRESS
            and turn_index > 0
            and not os.path.lexists(status_path)
            and not os.path.lexists(trajectory_path)
            and not turn_dir.is_symlink()
            and turn_dir.is_dir()
            and set(path.name for path in turn_dir.iterdir())
            in ({"prompt.txt"}, {"attempts", "prompt.txt"})
            and (
                not os.path.lexists(turn_dir / "attempts")
                or (
                    not (turn_dir / "attempts").is_symlink()
                    and (turn_dir / "attempts").is_dir()
                )
            )
        ):
            if (
                manifest.get("session_id") != state.session_id
                or manifest.get("effective_solver_model")
                != state.effective_solver_model
            ):
                raise RuntimeError(
                    "interrupted revision state has inconsistent solver identity"
                )
            self._restore_last_scored_workspace(state, workspace)
            self._discard_solver_session(
                state,
                manifest,
                reason="solver interrupted before finalizing turn artifacts",
            )
            self._reset_uncertain_solver_turn(state, turn_dir, turn_index)
            return
        if (
            (state.session_id is None) != (state.effective_solver_model is None)
            or manifest.get("session_id") != state.session_id
            or manifest.get("effective_solver_model") != state.effective_solver_model
        ):
            raise RuntimeError("failed revision state has inconsistent solver identity")
        if (
            state.phase is _RevisionPhase.FAILED_TURN
            and not os.path.lexists(trajectory_path)
            and not turn_dir.is_symlink()
            and turn_dir.is_dir()
            and not status_path.is_symlink()
            and status_path.is_file()
        ):
            status = _read_json_object(status_path, "failed solver turn status")
            if (
                status.get("status") == "failed"
                and status.get("exit_code") == 1
                and tuple(status.get("validation_errors") or ())
                in {
                    ("controlled Codex configuration changed",),
                    ("codex did not report a session ID during resume",),
                }
            ):
                self._restore_last_scored_workspace(state, workspace)
                self._discard_solver_session(
                    state,
                    manifest,
                    reason=status["validation_errors"][0],
                )
                self._reset_uncertain_solver_turn(state, turn_dir, turn_index)
                return
        if (
            turn_dir.is_symlink()
            or not turn_dir.is_dir()
            or status_path.is_symlink()
            or not status_path.is_file()
            or trajectory_path.is_symlink()
            or not trajectory_path.is_file()
            or trajectory_path.stat().st_size == 0
        ):
            raise RuntimeError("failed solver turn artifacts are incomplete")

        status = _read_json_object(status_path, "failed solver turn status")
        attempts = status.get("attempts")
        retry_count = status.get("max_retries")
        common_attempt_boundary = (
            status.get("status") in {None, "failed"}
            and type(retry_count) is int
            and retry_count == self.config.agent.retries
            and isinstance(attempts, list)
            and bool(attempts)
            and status.get("attempt_count") == len(attempts)
            and all(
                isinstance(attempt, dict)
                and type(attempt.get("process_exit_code")) is int
                and attempt["process_exit_code"] == 0
                for attempt in attempts
            )
        )
        validation_errors = status.get("validation_errors")
        excluded_root_failure = (
            common_attempt_boundary
            and len(attempts) == 1
            and attempts[-1].get("stream_errors") == []
            and attempts[-1].get("output_errors") == []
            and isinstance(validation_errors, list)
            and len(validation_errors) == 1
            and isinstance(validation_errors[0], str)
            and validation_errors[0].startswith(
                "snapshot contains a non-regular file: "
            )
            and _is_excluded_solution_root(
                workspace
                / validation_errors[0].split(": ", 1)[1].split("/", 1)[0]
            )
        )
        interrupted_after_provider_success = (
            state.phase is _RevisionPhase.TURN_IN_PROGRESS
            and common_attempt_boundary
            and status.get("exit_code") == 0
            and attempts[-1].get("stream_errors") == []
            and attempts[-1].get("output_errors") == []
        )
        if not (excluded_root_failure or interrupted_after_provider_success):
            self._restore_last_scored_workspace(state, workspace)
            self._reset_uncertain_solver_turn(state, turn_dir, turn_index)
            return

        self._validate_submission_outputs(workspace)
        _solution_tree_sha256(workspace)
        submission_id = f"s{turn_index:03d}"
        submission_dir = self.experiment_dir / "submissions" / submission_id
        trajectories = [self.seed.submission_dir / "trajectory.stream.jsonl"] + [
            self.experiment_dir
            / "turns"
            / f"turn-{index:03d}"
            / "trajectory.stream.jsonl"
            for index in range(1, turn_index + 1)
        ]
        if os.path.lexists(submission_dir):
            self._verify_recovered_submission_snapshot(
                submission_dir,
                workspace,
                trajectories,
                state.session_id,
            )
        else:
            self._snapshot_submission(
                submission_id,
                workspace,
                trajectories,
                state.session_id,
            )

        turn_dir.chmod(stat.S_IMODE(os.lstat(turn_dir).st_mode) | stat.S_IRWXU)
        status_path.chmod(
            stat.S_IMODE(os.lstat(status_path).st_mode) | stat.S_IRUSR | stat.S_IWUSR
        )
        transport_exit_code = status.get("transport_exit_code")
        if type(transport_exit_code) is not int:
            provider_exit_code = status.get("provider_exit_code")
            transport_exit_code = (
                provider_exit_code if type(provider_exit_code) is int else 1
            )
        recovery_status = (
            "accepted_after_disposable_exclusion"
            if excluded_root_failure
            else "accepted_after_interrupted_boundary"
        )
        status.update(
            {
                "status": recovery_status,
                "exit_code": 0,
                "transport_exit_code": transport_exit_code,
                "recovered_on_resume": True,
            }
        )
        _write_json(status_path, status)
        _make_tree_read_only(turn_dir)
        state.submission_ids.append(submission_id)
        state.next_turn_index += 1
        state.phase = _RevisionPhase.READY_FOR_JUDGE
        self._write_state(state)
        self._append_event(
            {
                "event": "turn_recovered",
                "turn": turn_index,
                "session_id": state.session_id,
                "reason": (
                    "accepted workspace after excluding disposable run state"
                    if excluded_root_failure
                    else "accepted completed provider turn after interruption"
                ),
            }
        )

    def _restore_last_scored_workspace(
        self,
        state: _RevisionState,
        workspace: Path,
    ) -> None:
        restored = workspace.parent / "workspace-restore"
        if os.path.lexists(restored):
            raise RuntimeError(f"stale workspace restore path exists: {restored}")
        if state.submission_ids:
            source = (
                self.experiment_dir
                / "submissions"
                / state.submission_ids[-1]
                / "workspace"
            )
            _verify_submission_snapshot(source.parent)
            shutil.copytree(source, restored, copy_function=shutil.copyfile)
            _make_tree_owner_writable(restored)
            TaskWorkspace(self.task_dir, restored).restore_inputs()
        else:
            TaskWorkspace(self.task_dir, restored).create()
        _make_tree_owner_writable(workspace)
        shutil.rmtree(workspace)
        restored.rename(workspace)

    def _reset_uncertain_solver_turn(
        self,
        state: _RevisionState,
        turn_dir: Path,
        turn_index: int,
    ) -> None:
        for path in (self.experiment_dir, turn_dir.parent, turn_dir):
            path.chmod(stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IRWXU)
        archive_root = self.experiment_dir / "interrupted-turns"
        archive_root.mkdir(exist_ok=True)
        archive_root.chmod(
            stat.S_IMODE(os.lstat(archive_root).st_mode) | stat.S_IRWXU
        )
        archive = archive_root / f"turn-{turn_index:03d}"
        suffix = 1
        while os.path.lexists(archive):
            archive = archive_root / f"turn-{turn_index:03d}-{suffix:03d}"
            suffix += 1
        shutil.move(str(turn_dir), str(archive))
        state.phase = _RevisionPhase.READY_FOR_TURN
        self._write_state(state)
        self._append_event(
            {
                "event": "turn_reset_after_interruption",
                "turn": turn_index,
                "session_id": state.session_id,
                "archive": str(archive.relative_to(self.experiment_dir)),
            }
        )

    def _validate_resume_state(
        self,
        state: _RevisionState,
        workspace: Path | None,
        manifest: dict[str, object],
    ) -> None:
        if state.phase in {
            _RevisionPhase.TURN_IN_PROGRESS,
            _RevisionPhase.FAILED_TURN,
        }:
            raise RuntimeError(
                "experiment stopped during an uncertain or failed solver turn"
            )
        total = self.config.revision_rounds + 1
        if not 0 <= state.next_turn_index <= total:
            raise RuntimeError("revision state has an invalid turn index")
        if state.phase in {
            _RevisionPhase.READY_FOR_JUDGE,
            _RevisionPhase.JUDGE_IN_PROGRESS,
        }:
            valid_counts = (
                len(state.submission_ids) == state.next_turn_index
                and len(state.scores) == state.next_turn_index - 1
                and len(state.fixed_original_scores) == state.next_turn_index - 1
            )
        else:
            valid_counts = (
                len(state.submission_ids)
                == len(state.scores)
                == len(state.fixed_original_scores)
                == state.next_turn_index
            )
        if not valid_counts:
            raise RuntimeError("revision state boundary counts are inconsistent")
        expected_submission_ids = [
            f"s{index:03d}" for index in range(state.next_turn_index)
        ]
        if state.submission_ids != expected_submission_ids:
            raise RuntimeError("revision state has invalid submission identities")
        if state.phase is _RevisionPhase.COMPLETED and state.next_turn_index != total:
            raise RuntimeError("completed revision state has missing submissions")
        if workspace is None and state.phase is not _RevisionPhase.COMPLETED:
            raise RuntimeError(
                "live workspace is required for an incomplete experiment"
            )
        if state.phase is _RevisionPhase.READY_FOR_JUDGE:
            expected_judge_attempts = set(state.submission_ids[: len(state.scores)])
        else:
            expected_judge_attempts = set(state.submission_ids)
        if set(state.judge_attempts) != expected_judge_attempts or any(
            len(attempt_id) != 32
            or any(character not in "0123456789abcdef" for character in attempt_id)
            for attempt_id in state.judge_attempts.values()
        ):
            raise RuntimeError("revision state has invalid judge attempt identities")
        if (state.session_id is None) != (state.effective_solver_model is None):
            raise RuntimeError("revision state has partial solver identity")
        if manifest.get("session_id") != state.session_id:
            raise RuntimeError("manifest and revision state disagree on session ID")
        if manifest.get("effective_solver_model") != state.effective_solver_model:
            raise RuntimeError("manifest and revision state disagree on solver model")
        turn_dirs = sorted((self.experiment_dir / "turns").glob("turn-*"))
        expected_turns = [
            self.experiment_dir / "turns" / f"turn-{index:03d}"
            for index in range(1, state.next_turn_index)
        ]
        if turn_dirs != expected_turns:
            raise RuntimeError("experiment contains an uncertain solver turn")
        for submission_id in state.submission_ids:
            _verify_submission_snapshot(
                self.experiment_dir / "submissions" / submission_id
            )
        if state.submission_ids and workspace is not None:
            snapshot = _read_json_object(
                self.experiment_dir
                / "submissions"
                / state.submission_ids[-1]
                / "snapshot.json",
                "submission snapshot",
            )
            if snapshot.get("workspace_sha256") != _solution_tree_sha256(workspace):
                raise RuntimeError("live workspace changed after the last boundary")
        self._validate_rubric_generation_replay()
        self._validate_scored_boundaries(state)
        if manifest.get("initial_member_scoring_identity") != self.scoring_identity:
            raise RuntimeError("revision manifest has the wrong scoring identity")

    def _validate_rubric_generation_replay(self) -> None:
        """Replay every sealed proposal before any resumed dispatch."""

        proposal_root = self.experiment_dir / "rubric-generations"
        bank_root = self.experiment_dir / "rubric-banks"
        if self.bank_policy is RubricBankPolicy.FIXED:
            if os.path.lexists(proposal_root):
                raise RuntimeError("a fixed policy cannot contain rubric generations")
            if _numbered_bank_directories(
                bank_root,
                required=True,
                context="rubric bank",
            ) != [0]:
                raise RuntimeError("a fixed policy can contain only bank round 0")
            return

        maximum_generation = self.config.revision_rounds - 1
        _remove_owned_rubric_generation_residue(
            proposal_root,
            max_generation_round=maximum_generation,
        )
        proposal_rounds, ledger_rounds = _rubric_generation_entries(
            proposal_root
        )
        bank_rounds = _numbered_bank_directories(
            bank_root,
            required=True,
            context="rubric bank",
        )
        if not bank_rounds or bank_rounds[0] != 0:
            raise RuntimeError("rubric bank generations must start at round 0")
        elicitation_rounds = bank_rounds[1:]
        if elicitation_rounds != list(range(1, len(elicitation_rounds) + 1)):
            raise RuntimeError("rubric elicitation generations are not contiguous")
        if proposal_rounds != list(range(1, len(proposal_rounds) + 1)):
            raise RuntimeError("rubric proposal generations are not contiguous")
        if proposal_rounds[: len(elicitation_rounds)] != elicitation_rounds:
            raise RuntimeError(
                "a persisted rubric bank has no matching sealed proposal"
            )
        if len(proposal_rounds) not in {
            len(elicitation_rounds),
            len(elicitation_rounds) + 1,
        }:
            raise RuntimeError(
                "sealed rubric proposals are more than one bank ahead"
            )
        if proposal_rounds and proposal_rounds[-1] > maximum_generation:
            raise RuntimeError("rubric elicitation generation exceeds the study length")
        expected_ledger_rounds = list(range(1, len(ledger_rounds) + 1))
        if ledger_rounds != expected_ledger_rounds:
            raise RuntimeError("rubric provider attempt ledgers are not contiguous")
        terminal_ledgers = sorted(set(ledger_rounds) - set(proposal_rounds))
        if (
            len(terminal_ledgers) > 1
            or terminal_ledgers
            and terminal_ledgers[0] != len(proposal_rounds) + 1
            or ledger_rounds
            and ledger_rounds[-1] > maximum_generation
        ):
            raise RuntimeError("rubric provider attempt ledger schedule is invalid")

        proposer = self.dependencies.bank_proposer
        if proposer is None:
            raise RuntimeError("elicitation replay has no rubric proposer")
        instruction = (self.task_dir / "instruction.md").read_text(
            encoding="utf-8"
        )
        for generation_round in ledger_rounds:
            prior = load_rubric_bank(
                self.experiment_dir,
                generation_round - 1,
                expected_policy=self.bank_policy,
            )
            replayed = proposer.elicit_rubric(
                instruction=instruction,
                current_bank=prior.bank,
                policy=self.bank_policy,
                generation_round=generation_round,
                output_dir=proposal_root,
                contrasts=self._elicitation_contrasts(generation_round),
                source_boundary=(
                    generation_round
                    if self.bank_policy is RubricBankPolicy.ONLINE_ELICITATION
                    else None
                ),
            )
            if generation_round <= len(elicitation_rounds):
                persisted = load_rubric_bank(
                    self.experiment_dir,
                    generation_round,
                    expected_policy=self.bank_policy,
                )
                if replayed != persisted:
                    raise RuntimeError(
                        "rubric generation disagrees with the persisted bank"
                    )
            elif (
                generation_round in proposal_rounds
                or generation_round in terminal_ledgers
            ):
                persist_rubric_bank(
                    self.experiment_dir,
                    replayed,
                    self.bank_policy,
                )

    def _run_solver_turn(self, state: _RevisionState, workspace: Path) -> None:
        ensure_artifacts_dir(workspace)
        turn_index = state.next_turn_index
        state.phase = _RevisionPhase.TURN_IN_PROGRESS
        self._write_state(state)
        turn_dir = self.experiment_dir / "turns" / f"turn-{turn_index:03d}"
        turn_dir.mkdir(parents=True)
        (turn_dir / "prompt.txt").write_text(state.next_prompt)
        try:
            self._execute_solver_turn(state, workspace, turn_dir, turn_index)
        except BaseException as exc:
            if state.phase is not _RevisionPhase.FAILED_TURN:
                exit_code = exc.exit_code if isinstance(exc, _SolverTurnFailure) else 1
                reason = str(exc) or type(exc).__name__
                try:
                    self._mark_turn_failed(
                        state,
                        turn_dir,
                        turn_index,
                        reason,
                        exit_code,
                    )
                except Exception as record_error:
                    raise RuntimeError(
                        f"solver turn {turn_index} failed and could not be sealed"
                    ) from record_error
            raise

    def _execute_solver_turn(
        self,
        state: _RevisionState,
        workspace: Path,
        turn_dir: Path,
        turn_index: int,
    ) -> None:

        def record_early_session_id(session_id: str) -> None:
            if state.session_id not in {None, session_id}:
                raise RuntimeError("solver reported a different provider session")
            state.session_id = session_id
            self._record_session_id(session_id)
            self._write_state(state)

        if state.session_id is None:
            turn = self.dependencies.session.start(
                workspace,
                state.next_prompt,
                turn_dir,
                on_session_id=record_early_session_id,
            )
            record_early_session_id(turn.session_id)
        else:
            turn = self.dependencies.session.resume(
                workspace,
                state.next_prompt,
                turn_dir,
                state.session_id,
            )
            if turn.session_id != state.session_id:
                raise RuntimeError("solver resumed a different provider session")
        self._record_effective_solver_model(state, turn.model)
        if turn.exit_code != 0:
            raise _SolverTurnFailure(
                f"provider exited with code {turn.exit_code}", turn.exit_code
            )
        try:
            self._verify_live_instruction(workspace)
            self._validate_submission_outputs(workspace)
            _solution_tree_sha256(workspace)
        except (OSError, RuntimeError) as exc:
            raise _SolverTurnFailure(str(exc), 2) from exc
        _make_tree_read_only(turn_dir)
        submission_id = f"s{turn_index:03d}"
        trajectories = [self.seed.submission_dir / "trajectory.stream.jsonl"] + [
            self.experiment_dir
            / "turns"
            / f"turn-{index:03d}"
            / "trajectory.stream.jsonl"
            for index in range(1, turn_index + 1)
        ]
        self._snapshot_submission(
            submission_id,
            workspace,
            trajectories,
            state.session_id or "",
        )
        self._append_event(
            {
                "event": "turn_completed",
                "turn": turn_index,
                "session_id": state.session_id,
                "trajectory_sha256": _sha256_file(turn.trajectory_path),
            }
        )
        state.submission_ids.append(submission_id)
        state.next_turn_index += 1
        state.phase = _RevisionPhase.READY_FOR_JUDGE
        self._write_state(state)

    def _run_judge_boundary(self, state: _RevisionState) -> None:
        self._validate_scored_boundaries(state)
        submission_id = state.submission_ids[-1]
        turn_index = state.next_turn_index - 1
        attempt_id = state.judge_attempts.get(submission_id)
        if attempt_id is None:
            attempt_id = secrets.token_hex(16)
            state.judge_attempts[submission_id] = attempt_id
        state.phase = _RevisionPhase.JUDGE_IN_PROGRESS
        self._write_state(state)
        submission_dir = self.experiment_dir / "submissions" / submission_id
        _verify_submission_snapshot(submission_dir)
        self._verify_canonical_task_inputs()
        generation = self._active_bank_generation(turn_index)
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
            rubric, judge = self._bank_member_runtime(
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
            self._verify_round_scoring_identity(
                artifacts.score_validation_path,
                rubric,
                judge,
                seeded=seeded,
            )
            member_artifacts[item.rubric.content_sha256] = artifacts
        self._verify_canonical_task_inputs()
        _verify_submission_snapshot(submission_dir)
        feedback = self._project_boundary_feedback(
            artifacts=member_artifacts,
            bank=bank,
            submission_id=submission_id,
            generation_round=bank.generation_round,
            submission_dir=submission_dir,
            allow_generation=True,
        )
        bank_evaluation = self._bank_evaluation_record(
            bank,
            member_artifacts,
            submission_id,
            dispatch_preflight,
        )
        if bank_evaluation["weighted_score"] != feedback.score:
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
        fixed_original_score = self._fixed_original_score(
            submission_dir=submission_dir,
            submission_id=submission_id,
            turn_index=turn_index,
            on_policy_score=feedback.score,
        )
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
            self.bank_policy is not RubricBankPolicy.FIXED
            and 1 <= turn_index < self.config.revision_rounds
        ):
            assert self.dependencies.bank_proposer is not None
            next_generation = self.dependencies.bank_proposer.elicit_rubric(
                instruction=(self.task_dir / "instruction.md").read_text(),
                current_bank=bank,
                policy=self.bank_policy,
                generation_round=turn_index,
                contrasts=self._elicitation_contrasts(turn_index),
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
        self._write_state(state)
        self._publish_progress_report(state, submission_id)
        self._append_event(
            {
                "event": "submission_judged",
                "submission_id": submission_id,
                "turn": turn_index,
                "judge_attempt_id": attempt_id,
                "score": feedback.score,
                "on_policy_score": feedback.score,
                "fixed_original_score": fixed_original_score,
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

    def _bank_evaluation_record(
        self,
        bank: RubricBank,
        artifacts: dict[str, JudgeArtifacts],
        submission_id: str,
        dispatch_preflight: dict[str, object],
    ) -> dict[str, object]:
        if (
            dispatch_preflight.get("bank_sha256") != bank.content_sha256
            or dispatch_preflight.get("member_sha256s")
            != [item.rubric.content_sha256 for item in bank.items]
        ):
            raise RuntimeError("bank dispatch preflight has the wrong bank binding")
        members: dict[str, dict[str, object]] = {}
        scores: dict[str, float] = {}
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
            scores[rubric_hash] = float(score)
            members[rubric_hash] = {
                "weight": item.weight,
                "score": score,
                "score_validation_sha256": _sha256_file(
                    member.score_validation_path
                ),
                "evaluation_sha256": _sha256_file(member.evaluation_path),
            }
        return {
            "kind": "weighted-rubric-bank-evaluation",
            "submission_id": submission_id,
            "generation_round": bank.generation_round,
            "bank_sha256": bank.content_sha256,
            "dispatch_preflight": dispatch_preflight,
            "members": members,
            "weighted_score": bank.aggregate(scores),
        }

    def _project_boundary_feedback(
        self,
        *,
        artifacts: dict[str, JudgeArtifacts],
        bank: RubricBank,
        submission_id: str,
        generation_round: int,
        submission_dir: Path,
        allow_generation: bool,
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
            prompt_profile=self.config.prompt_profile,
            benchmark=self.config.benchmark,
        )

    def _publish_progress_report(
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
            self._append_event(
                {
                    "event": "report_publication_failed",
                    "submission_id": submission_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc) or type(exc).__name__,
                }
            )

    def _active_bank_generation(self, boundary: int) -> RubricBankGeneration:
        generation_round = (
            0
            if self.bank_policy is RubricBankPolicy.FIXED
            else max(0, boundary - 1)
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

    def _elicitation_contrasts(self, generation_round: int):
        """Return the exact three blinded pairs for one rubric update."""

        return build_elicitation_contrasts(
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
    def _frozen_bank_member(text: str, rubric_sha256: str) -> FrozenRubric:
        """Return the judge identity for one immutable bank member."""
        return FrozenRubric(
            text=text, sha256=rubric_sha256, source=RUBRIC_PATH_SOURCE,
            rubric_set_id=None, rubric_id=None,
            structured_rubric_sha256=None, manifest_sha256=None,
        )

    def _bank_member_runtime(
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
        rubric = self._frozen_bank_member(
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

    def _fixed_original_score(
        self,
        *,
        submission_dir: Path,
        submission_id: str,
        turn_index: int,
        on_policy_score: float,
    ) -> float:
        active_bank = self._active_bank_generation(turn_index).bank
        if turn_index == 0 and self.reuse_seed_master_judgment:
            validation_path, _, _ = self.seed.judgment
            self._verify_round_scoring_identity(
                validation_path,
                self.master_rubric,
                self.master_judge,
                seeded=True,
            )
            validation = _read_json_object(
                validation_path,
                "seeded master-rubric score validation",
            )
            score = validation.get("score")
            if (
                isinstance(score, bool)
                or not isinstance(score, Real)
                or not math.isfinite(float(score))
                or not 0 <= float(score) <= 100
            ):
                raise RuntimeError("seeded master-rubric score is invalid")
            return float(score)
        if (
            active_bank.rubric_count == 1
            and active_bank.items[0].rubric.content_sha256
            == self.master_rubric.sha256
            and (
                turn_index == 0
                or self.bank_policy is RubricBankPolicy.FIXED
            )
        ):
            return on_policy_score
        if self.judgment_reuse is not None:
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
            self._verify_round_scoring_identity(
                reused.artifacts.score_validation_path,
                self.master_rubric,
                self.master_judge,
            )
            validation = _read_json_object(
                reused.artifacts.score_validation_path,
                "shared fixed-original score validation",
            )
            score = validation.get("score")
            if (
                isinstance(score, bool)
                or not isinstance(score, Real)
                or not math.isfinite(float(score))
                or not 0 <= float(score) <= 100
            ):
                raise RuntimeError("shared fixed-original judgment has an invalid score")
            return float(score)
        attempt_id = fixed_original_attempt_id(
            self.config.assignment_id,
            submission_id,
            self.master_rubric.sha256,
        )
        artifacts = self.master_judge.evaluate(submission_dir, attempt_id)
        self._verify_round_scoring_identity(
            artifacts.score_validation_path,
            self.master_rubric,
            self.master_judge,
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
        return float(score)

    def _verify_round_scoring_identity(
        self,
        validation_path: Path,
        rubric: FrozenRubric,
        judge: object,
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
            reported = judge.scoring_identity()  # type: ignore[attr-defined]
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
            self._pin_or_verify_scoring_identity(validation_path)
            return
        validation = _read_json_object(validation_path, "optimizer score validation")
        identity = _extract_scoring_identity(
            validation, context="optimizer score validation"
        )
        reported = judge.scoring_identity()  # type: ignore[attr-defined]
        if identity != _extract_scoring_identity(reported, context="round judge"):
            raise RuntimeError("round scoring identity does not match rubric judge")
        if identity["rendered_rubric_sha256"] != rubric.sha256:
            raise RuntimeError("round score attests a different rubric")

    def _validate_scored_boundaries(self, state: _RevisionState) -> None:
        for index, score in enumerate(state.scores):
            submission_id = f"s{index:03d}"
            submission_dir = self.experiment_dir / "submissions" / submission_id
            _verify_submission_snapshot(submission_dir)
            attempt_id = state.judge_attempts.get(submission_id)
            if attempt_id is None:
                raise RuntimeError("scored submission has no judge attempt identity")
            bank = self._active_bank_generation(index).bank
            member_artifacts: dict[str, JudgeArtifacts] = {}
            for item in bank.items:
                rubric, judge = self._bank_member_runtime(
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
                self._verify_round_scoring_identity(
                    artifacts.score_validation_path,
                    rubric,
                    judge,
                    seeded=seeded,
                )
                member_artifacts[item.rubric.content_sha256] = artifacts
            projected = self._project_boundary_feedback(
                artifacts=member_artifacts,
                bank=bank,
                submission_id=submission_id,
                generation_round=bank.generation_round,
                submission_dir=submission_dir,
                allow_generation=False,
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
            expected_bank_evaluation = self._bank_evaluation_record(
                bank,
                member_artifacts,
                submission_id,
                preflight_bank_dispatch(
                    bank,
                    benchmark=self.config.benchmark,
                    review_text=review_text,
                    answer_text=answer_text,
                ),
            )
            if bank_evaluation != expected_bank_evaluation:
                raise RuntimeError(
                    "stored bank evaluation disagrees with member artifacts"
                )
            fixed_score = state.fixed_original_scores[index]
            if index == 0 and self.reuse_seed_master_judgment:
                master_validation_path, _, _ = self.seed.judgment
                self._verify_round_scoring_identity(
                    master_validation_path,
                    self.master_rubric,
                    self.master_judge,
                    seeded=True,
                )
                expected_fixed_score = _read_json_object(
                    master_validation_path,
                    "seeded master-rubric score validation",
                ).get("score")
            elif (
                bank.rubric_count == 1
                and bank.items[0].rubric.content_sha256
                == self.master_rubric.sha256
                and (
                    index == 0
                    or self.bank_policy is RubricBankPolicy.FIXED
                )
            ):
                expected_fixed_score = projected.score
            elif self.judgment_reuse is not None:
                review_text, answer_text = self.master_judge.review_inputs(
                    submission_dir
                )
                expected_request = exact_judgment_request(
                    task_id=self.task_dir.name,
                    replicate=self.config.replicate,
                    rubric_sha256=self.master_rubric.sha256,
                    review_text=review_text,
                    answer_text=answer_text,
                    scoring_identity=self.master_judge.scoring_identity(),
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
                    rubric_sha256=self.master_rubric.sha256,
                    expected_request=expected_request,
                )
                self._verify_round_scoring_identity(
                    reused.artifacts.score_validation_path,
                    self.master_rubric,
                    self.master_judge,
                )
                expected_fixed_score = _read_json_object(
                    reused.artifacts.score_validation_path,
                    "shared fixed-original score validation",
                ).get("score")
            else:
                fixed_attempt_id = fixed_original_attempt_id(
                    self.config.assignment_id,
                    submission_id,
                    self.master_rubric.sha256,
                )
                fixed_artifacts = self.master_judge.validate(
                    submission_dir,
                    fixed_attempt_id,
                )
                self._verify_round_scoring_identity(
                    fixed_artifacts.score_validation_path,
                    self.master_rubric,
                    self.master_judge,
                )
                fixed_validation = _read_json_object(
                    fixed_artifacts.score_validation_path,
                    "fixed-original score validation",
                )
                expected_fixed_score = fixed_validation.get("score")
            if expected_fixed_score != fixed_score:
                raise RuntimeError(
                    "stored fixed-original score disagrees with judge artifacts"
                )

    def _verify_recovered_submission_snapshot(
        self,
        submission_dir: Path,
        workspace: Path,
        trajectories: list[Path],
        session_id: str,
    ) -> None:
        """Validate a snapshot sealed before an interrupted state update."""

        _verify_submission_snapshot(submission_dir)
        snapshot = _read_json_object(
            submission_dir / "snapshot.json", "recovered submission snapshot"
        )
        status = _read_json_object(
            submission_dir / "status.json", "recovered submission status"
        )
        if (
            snapshot.get("session_id") != session_id
            or snapshot.get("workspace_sha256") != _solution_tree_sha256(workspace)
            or status.get("task") != self.task_dir.name
            or status.get("task_dir") != str(self.task_dir)
            or status.get("workspace_dir") != str(submission_dir / "workspace")
            or status.get("provider") != self.config.agent.provider
            or status.get("session_id") != session_id
            or status.get("submission_id") != submission_dir.name
            or status.get("exit_code") != 0
        ):
            raise RuntimeError(
                "existing recovered submission snapshot disagrees with the solver turn"
            )
        expected_trajectory = hashlib.sha256()
        for trajectory in trajectories:
            raw = trajectory.read_bytes()
            expected_trajectory.update(raw)
            if raw and not raw.endswith(b"\n"):
                expected_trajectory.update(b"\n")
        if snapshot.get("trajectory_sha256") != expected_trajectory.hexdigest():
            raise RuntimeError(
                "existing recovered submission trajectory disagrees with the solver turn"
            )

    def _compact_historical_submissions(
        self, state: _RevisionState
    ) -> tuple[int, int]:
        """Drop bulky derived files from scored non-final submissions.

        Completed state is written first, so this deliberately idempotent operation
        can finish repairing both sides of an interrupted compaction during resume.
        """
        if state.phase is not _RevisionPhase.COMPLETED:
            raise RuntimeError("historical snapshots may only be compacted when complete")
        removed_files = 0
        removed_logical_bytes = 0
        retained_names = self.benchmark.retained_workspace_names
        for submission_id in state.submission_ids[:-1]:
            submission_removed_files = 0
            submission_removed_logical_bytes = 0
            submission_dir = self.experiment_dir / "submissions" / submission_id
            attempt_id = state.judge_attempts[submission_id]
            submission_index = int(submission_id[1:])
            bank = self._active_bank_generation(submission_index).bank
            for item in bank.items:
                evaluation_workspace = (
                    self.experiment_dir
                    / "evaluations"
                    / submission_id
                    / item.rubric.content_sha256
                    / attempt_id
                    / "run"
                    / "workspace"
                )
                # Custom judges can keep caches outside the standard tree.
                if os.path.lexists(evaluation_workspace):
                    _compact_historical_workspace(
                        evaluation_workspace,
                        retained_names=retained_names,
                    )
            stats = _compact_historical_workspace(
                submission_dir / "workspace",
                retained_names=retained_names,
            )
            removed_files += stats.removed_files
            removed_logical_bytes += stats.removed_logical_bytes
            submission_removed_files += stats.removed_files
            submission_removed_logical_bytes += stats.removed_logical_bytes

            snapshot_path = submission_dir / "snapshot.json"
            snapshot = _read_json_object(snapshot_path, "submission snapshot")
            snapshot.update(
                {
                    "workspace_scope": "judge-inputs",
                    "workspace_sha256": _tree_sha256(submission_dir / "workspace"),
                    "historical_workspace_files_removed": snapshot.get(
                        "historical_workspace_files_removed", 0
                    )
                    + submission_removed_files,
                    "historical_workspace_logical_bytes_removed": snapshot.get(
                        "historical_workspace_logical_bytes_removed", 0
                    )
                    + submission_removed_logical_bytes,
                }
            )
            submission_dir.chmod(
                stat.S_IMODE(os.lstat(submission_dir).st_mode) | stat.S_IRWXU
            )
            if snapshot_path.exists():
                snapshot_path.chmod(
                    stat.S_IMODE(os.lstat(snapshot_path).st_mode) | stat.S_IWUSR
                )
            _write_json_atomic(snapshot_path, snapshot)
            _make_read_only(snapshot_path)
            _make_read_only(submission_dir)
        return removed_files, removed_logical_bytes

    def _persist_initial_bank(self) -> None:
        self.store.persist_initial_bank()

    def _verify_initial_bank(self) -> None:
        self.store.verify_initial_bank()

    def _write_state(self, state: _RevisionState) -> None:
        self.store.write_state(state)

    def _read_state(self) -> _RevisionState:
        return self.store.read_state()

    def _update_manifest(self, updates: dict[str, object]) -> None:
        self.store.update_manifest(updates)

    def _record_session_id(self, session_id: str) -> None:
        self.store.record_session_id(session_id)

    def _record_effective_solver_model(
        self, state: _RevisionState, model: str
    ) -> None:
        self.store.record_effective_solver_model(state, model)

    def _pin_or_verify_scoring_identity(self, validation_path: Path) -> None:
        self.store.verify_scoring_identity(validation_path)

    def _mark_turn_failed(
        self,
        state: _RevisionState,
        turn_dir: Path,
        turn_index: int,
        reason: str,
        exit_code: int,
    ) -> None:
        status_path = turn_dir / "status.json"
        if turn_dir.is_symlink() or not turn_dir.is_dir():
            raise RuntimeError("solver turn directory is invalid")
        turn_dir.chmod(stat.S_IMODE(os.lstat(turn_dir).st_mode) | stat.S_IRWXU)
        if status_path.is_symlink():
            raise RuntimeError("solver turn status is a symbolic link")
        if status_path.is_file():
            status_path.chmod(
                stat.S_IMODE(os.lstat(status_path).st_mode)
                | stat.S_IRUSR
                | stat.S_IWUSR
            )
        status = (
            _read_json_object(status_path, "solver turn status")
            if status_path.is_file()
            else {}
        )
        provider_exit_code = status.get("exit_code")
        status.update(
            {
                "status": "failed",
                "provider_exit_code": provider_exit_code,
                "exit_code": exit_code,
                "validation_errors": [reason],
            }
        )
        _write_json(status_path, status)
        state.phase = _RevisionPhase.FAILED_TURN
        self._write_state(state)
        self._append_event(
            {
                "event": "turn_failed",
                "turn": turn_index,
                "exit_code": exit_code,
                "session_id": state.session_id,
                "reason": reason,
            }
        )
        _make_tree_read_only(turn_dir)

    def _validate_submission_outputs(self, workspace: Path) -> None:
        errors = self.benchmark.output_errors(workspace)
        if errors:
            raise RuntimeError(
                "solver submission is missing or has invalid required outputs: "
                + ", ".join(errors)
            )

    def _verify_live_instruction(self, workspace: Path) -> None:
        if _sha256_file(workspace / "instruction.md") != self.instruction_sha256:
            raise RuntimeError("solver modified the task instruction")

    def _verify_canonical_task_inputs(self) -> None:
        if _sha256_file(self.task_dir / "instruction.md") != self.instruction_sha256:
            raise RuntimeError(
                "canonical task instruction changed during the experiment"
            )
        if _tree_sha256(self.task_dir / "environment" / "data") != self.data_sha256:
            raise RuntimeError("canonical task data changed during the experiment")

    def _snapshot_submission(
        self,
        submission_id: str,
        workspace: Path,
        trajectories: list[Path],
        session_id: str,
    ) -> Path:
        submission_dir = self.experiment_dir / "submissions" / submission_id
        snapshot_workspace = submission_dir / "workspace"
        submissions_root = self.experiment_dir / "submissions"
        submissions_root.mkdir(exist_ok=True)
        previous_workspaces = sorted(
            path / "workspace"
            for path in submissions_root.iterdir()
            if path.is_dir() and path.name < submission_id
        )
        previous_workspace = previous_workspaces[-1] if previous_workspaces else None
        submission_dir.mkdir(parents=True)
        copy_stats = _copy_solution_workspace(
            workspace,
            snapshot_workspace,
            previous=previous_workspace,
        )
        _make_tree_read_only(snapshot_workspace)

        cumulative = submission_dir / "trajectory.stream.jsonl"
        with cumulative.open("wb") as output:
            for trajectory in trajectories:
                raw = trajectory.read_bytes()
                output.write(raw)
                if raw and not raw.endswith(b"\n"):
                    output.write(b"\n")
        status_path = submission_dir / "status.json"
        _write_json(
            status_path,
            {
                "task": self.task_dir.name,
                "task_dir": str(self.task_dir),
                "workspace_dir": str(snapshot_workspace),
                "provider": self.config.agent.provider,
                "session_id": session_id,
                "submission_id": submission_id,
                "exit_code": 0,
            },
        )
        workspace_sha256 = _tree_sha256(snapshot_workspace)
        trajectory_sha256 = _sha256_file(cumulative)
        snapshot_path = submission_dir / "snapshot.json"
        _write_json(
            snapshot_path,
            {
                "submission_id": submission_id,
                "session_id": session_id,
                "workspace_sha256": workspace_sha256,
                "trajectory_sha256": trajectory_sha256,
                "workspace_logical_bytes": copy_stats.logical_bytes,
                "workspace_copied_bytes": copy_stats.copied_bytes,
                "workspace_deduplicated_bytes": copy_stats.linked_bytes,
                "workspace_copied_files": copy_stats.copied_files,
                "workspace_deduplicated_files": copy_stats.linked_files,
            },
        )
        for path in (cumulative, status_path, snapshot_path):
            _make_read_only(path)
        _make_read_only(submission_dir)
        self._append_event(
            {
                "event": "submission_snapshotted",
                "submission_id": submission_id,
                "workspace_sha256": workspace_sha256,
                "trajectory_sha256": trajectory_sha256,
                "workspace_logical_bytes": copy_stats.logical_bytes,
                "workspace_copied_bytes": copy_stats.copied_bytes,
                "workspace_deduplicated_bytes": copy_stats.linked_bytes,
            }
        )
        return submission_dir

    def _append_event(self, payload: dict[str, object]) -> None:
        self.store.append_event(payload)


def run_submission_revision(
    config: SubmissionRevisionConfig,
    *,
    judgment_reuse_root: Path | None = None,
) -> SubmissionRevisionResult:
    return SubmissionRevisionController(
        config,
        judgment_reuse_root=judgment_reuse_root,
    ).run()
