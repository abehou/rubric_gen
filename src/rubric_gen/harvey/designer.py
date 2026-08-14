"""Codex harness designer with free parent selection from complete history."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.biomnibench.agent.costs import RunCost
from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.agent.runners import AgentRunner
from rubric_gen.harvey.artifacts import (
    copy_regular_tree,
    file_sha256,
    make_tree_read_only,
    read_json_object,
    tree_sha256,
    validate_regular_tree,
)
from rubric_gen.harvey.config import HarnessDesigner


DESIGNER_PROMPT = """You are the harness designer in a Harvey LAB experiment.

Read instruction.md and then work autonomously. You can inspect every file below
history/ and current/, including prior harnesses, task-agent trajectories,
deliverables, metrics, active task rubrics, and the current crossed ranking.
Choose any prior harness as the parent. Copy that complete harness directory to
candidate/harness and make the copied tree writable before you edit it (use
`chmod -R u+w candidate/harness`). Make one coherent design change. You can change code,
prompts, tools, and skills inside candidate/harness. Do not edit history/ or
current/. The canonical evaluator is controller-owned and is not available in
this workspace.

Before you stop, write proposal.json with exactly these fields:
schema_version, parent_harness, hypothesis, mechanism, expected_effect, risks.
schema_version must be 1. parent_harness must be only the candidate ID from one
history directory, such as `h0000`; do not include the `history/` prefix.
The four explanation fields must be non-empty strings, except risks, which must
be a non-empty list of non-empty strings. Do not ask the user a question.
"""


INSTRUCTION = """# Harvey LAB harness-design round

Your objective is to design a harness that performs well on the Harvey LAB
development tasks under the active task rubrics and that transfers to unseen
tasks and reasonable rubric revisions.

The score table in `current/ranking.json` compares every existing candidate
under the current rubric version. Historical scores from different rubric
versions are not directly comparable. The listed frontier and ranking are
descriptive only. You are free to use a regressed or non-frontier candidate as
your parent. Hidden original-rubric scores, held-out tasks, and reward-hacking
audits do not appear in this workspace.

Use the trajectories and outputs to form a causal hypothesis. Avoid changes that
only match task IDs, criterion wording, document names, or observed answers.
Such changes can raise the visible score but fail the transfer audit.
"""


@dataclass(frozen=True)
class DesignedCandidate:
    parent_id: str
    harness: Path
    proposal: dict[str, object]
    harness_sha256: str
    trajectory: Path
    cost: dict[str, float | str | None]


class CodexHarnessDesigner:
    def __init__(self, config: HarnessDesigner) -> None:
        self.config = config

    def prepare_workspace(
        self,
        workspace: Path,
        *,
        candidate_harnesses: dict[str, Path],
        canonical_evaluations: dict[str, Path],
        current_dir: Path,
    ) -> str:
        if workspace.exists():
            raise FileExistsError(f"designer workspace exists: {workspace}")
        workspace.mkdir(parents=True)
        (workspace / "instruction.md").write_text(INSTRUCTION, encoding="utf-8")
        for candidate_id, harness in sorted(candidate_harnesses.items()):
            root = workspace / "history" / candidate_id
            root.mkdir(parents=True)
            copy_regular_tree(harness, root / "harness")
            evaluation = canonical_evaluations.get(candidate_id)
            if evaluation is not None:
                copy_regular_tree(evaluation, root / "canonical_evaluation")
        copy_regular_tree(current_dir, workspace / "current")
        (workspace / "instruction.md").chmod(0o444)
        make_tree_read_only(workspace / "history")
        make_tree_read_only(workspace / "current")
        return (
            file_sha256(workspace / "instruction.md")
            + tree_sha256(workspace / "history")
            + tree_sha256(workspace / "current")
        )

    def run(
        self,
        workspace: Path,
        run_dir: Path,
        *,
        expected_input_sha256: str,
        candidate_harnesses: dict[str, Path],
    ) -> DesignedCandidate:
        run_dir.mkdir(parents=True, exist_ok=True)
        attempt_streams: list[Path] = []
        attempt_records: list[dict[str, object]] = []
        exit_code = 1
        validation_error: str | None = None
        for attempt in range(1, self.config.retries + 2):
            attempt_dir = run_dir / "attempts" / f"attempt-{attempt:03d}"
            attempt_dir.mkdir(parents=True)
            prompt = DESIGNER_PROMPT if attempt == 1 else (
                "Continue the harness-design task in this workspace. The prior "
                "attempt did not leave valid final artifacts. Correct this validation "
                f"error: {validation_error or 'missing proposal.json or candidate/harness'}. "
                "Finish proposal.json and candidate/harness now without asking questions."
            )
            paths = RunPaths(
                provider="codex",
                run_dir=attempt_dir,
                workspace_dir=workspace,
                prompt_path=attempt_dir / "prompt.txt",
                policy_path=attempt_dir / "no-web-policy.toml",
                stream_path=attempt_dir / "trajectory.stream.jsonl",
                status_path=attempt_dir / "status.json",
            )
            runner = AgentRunner(
                AgentRunConfig(
                    provider="codex",
                    model=self.config.model,
                    reasoning_effort=self.config.reasoning_effort,
                    service_tier=self.config.service_tier,
                    retries=0,
                    timeout_seconds=self.config.timeout_seconds,
                    quiet=False,
                ),
                prompt=prompt,
                required_outputs=("proposal.json",),
            )
            runner.ensure_executable()
            process_exit = runner.stream(paths)
            errors = runner.trajectory_errors(paths.stream_path)
            output_error = not (workspace / "proposal.json").is_file() or not (
                workspace / "candidate" / "harness"
            ).is_dir()
            exit_code = process_exit or (1 if errors or output_error else 0)
            validation_error = None
            if exit_code == 0:
                try:
                    self._validate_artifacts(workspace, candidate_harnesses)
                except ValueError as exc:
                    validation_error = str(exc)
                    exit_code = 1
            attempt_streams.append(paths.stream_path)
            attempt_records.append(
                {
                    "attempt": attempt,
                    "process_exit_code": process_exit,
                    "exit_code": exit_code,
                    "trajectory_errors": errors,
                    "output_error": output_error,
                    "validation_error": validation_error,
                }
            )
            if exit_code == 0:
                break
        trajectory = run_dir / "trajectory.stream.jsonl"
        with trajectory.open("wb") as combined:
            for path in attempt_streams:
                combined.write(path.read_bytes())
        current_input_sha = (
            file_sha256(workspace / "instruction.md")
            + tree_sha256(workspace / "history")
            + tree_sha256(workspace / "current")
        )
        if current_input_sha != expected_input_sha256:
            raise RuntimeError("Codex changed a controller-owned visible input")
        if exit_code != 0:
            raise RuntimeError(f"Codex did not produce a valid harness candidate; see {run_dir}")
        designed = self._validate(workspace, candidate_harnesses, trajectory)
        status = {
            "schema_version": 1,
            "kind": "harvey-harness-design-turn",
            "model": self.config.model,
            "reasoning_effort": self.config.reasoning_effort,
            "service_tier": self.config.service_tier,
            "exit_code": exit_code,
            "attempts": attempt_records,
            "parent_harness": designed.parent_id,
            "harness_sha256": designed.harness_sha256,
            **designed.cost,
        }
        (run_dir / "status.json").write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return designed

    def _validate(
        self,
        workspace: Path,
        candidates: dict[str, Path],
        trajectory: Path,
    ) -> DesignedCandidate:
        parent, harness, proposal, digest = self._validate_artifacts(
            workspace, candidates
        )
        cost = RunCost.from_stream(
            trajectory,
            model=self.config.model,
            service_tier=self.config.service_tier,
        ).fields()
        return DesignedCandidate(parent, harness, proposal, digest, trajectory, cost)

    @staticmethod
    def _validate_artifacts(
        workspace: Path,
        candidates: dict[str, Path],
    ) -> tuple[str, Path, dict[str, object], str]:
        proposal = read_json_object(workspace / "proposal.json", "harness proposal")
        required = {
            "schema_version", "parent_harness", "hypothesis", "mechanism",
            "expected_effect", "risks",
        }
        if set(proposal) != required or proposal.get("schema_version") != 1:
            raise ValueError("harness proposal has invalid fields")
        parent = proposal.get("parent_harness")
        if type(parent) is not str or parent not in candidates:
            available = ", ".join(sorted(candidates))
            raise ValueError(
                "harness proposal parent_harness must be a candidate ID without "
                f"a history/ prefix; available IDs: {available}"
            )
        for key in ("hypothesis", "mechanism", "expected_effect"):
            if type(proposal.get(key)) is not str or not str(proposal[key]).strip():
                raise ValueError(f"harness proposal has invalid {key}")
        risks = proposal.get("risks")
        if not isinstance(risks, list) or not risks or any(type(value) is not str or not value.strip() for value in risks):
            raise ValueError("harness proposal has invalid risks")
        harness = workspace / "candidate" / "harness"
        validate_regular_tree(harness, "proposed harness")
        required_files = ("run.py", "system_prompt.md", "agent_loop.py", "tools.py")
        if any(not (harness / name).is_file() for name in required_files):
            raise ValueError("proposed harness is incomplete")
        files = [path for path in harness.rglob("*") if path.is_file()]
        total_bytes = sum(os.lstat(path).st_size for path in files)
        if len(files) > 1_000 or total_bytes > 20_000_000:
            raise ValueError("proposed harness exceeds the artifact size limit")
        digest = tree_sha256(harness)
        if digest == tree_sha256(candidates[parent]):
            raise ValueError("proposed harness is identical to its parent")
        return parent, harness, proposal, digest


def copy_designed_candidate(designed: DesignedCandidate, destination: Path) -> None:
    destination.mkdir(parents=True)
    copy_regular_tree(designed.harness, destination / "harness")
    record = {
        "schema_version": 1,
        "kind": "harvey-harness-candidate",
        "parent_harness": designed.parent_id,
        "harness_sha256": designed.harness_sha256,
        "proposal": designed.proposal,
        "designer_cost": designed.cost,
    }
    (destination / "candidate.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    make_tree_read_only(destination)
