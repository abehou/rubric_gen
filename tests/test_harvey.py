from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import rubric_gen.benchmarks.harvey_lab.designer as designer_module
from rubric_gen.benchmarks.harvey_lab.audits import prepare_reward_hacking_cases, run_quality_audit
from rubric_gen.benchmarks.harvey_lab.artifacts import tree_sha256
from rubric_gen.benchmarks.harvey_lab.config import (
    HarnessDesigner,
    HarveyBenchmark,
    HarveyExperiment,
    HarveyJudge,
    RewardHackingAudit,
    RubricEvolution,
    TaskAgent,
    load_experiment,
)
from rubric_gen.benchmarks.harvey_lab.controller import HarveyEvolutionController, build_ranking
from rubric_gen.benchmarks.harvey_lab.designer import DESIGNER_PROMPT, CodexHarnessDesigner, DesignedCandidate
from rubric_gen.benchmarks.harvey_lab.evaluator import CandidateEvaluation, HarveyEvaluator
from rubric_gen.benchmarks.harvey_lab.podman import (
    cache_image,
    configured_podman_environment,
    restore_cached_image,
)
from rubric_gen.benchmarks.harvey_lab.rubrics import TaskRubricProposer
from rubric_gen.runtime.llm import GenerationResult, request_parameters_for_model


def _task() -> dict[str, object]:
    return {
        "title": "Review",
        "instructions": "Review the agreement.",
        "deliverables": {"memo.md": "A memo"},
        "criteria": [
            {
                "id": "C-001",
                "title": "Identifies the issue",
                "deliverables": ["memo.md"],
                "match_criteria": "PASS if the memo identifies the issue. FAIL otherwise.",
            },
            {
                "id": "C-002",
                "title": "Gives advice",
                "deliverables": ["memo.md"],
                "match_criteria": "PASS if the memo gives advice. FAIL otherwise.",
            },
        ],
    }


def _config_text(tmp_path: Path, *, mode: str = "prospective") -> str:
    proposer = (
        "  proposer_model: gpt-5.6-sol\n  proposer_base_url: null\n"
        if mode == "prospective"
        else ""
    )
    return f"""kind: rubric-gen-harvey-harness-evolution-experiment
experiment_id: harvey-test
output_dir: output
cache_dir: cache
benchmark:
  checkout: checkout
  revision: {'a' * 40}
  development_tasks: [area/task]
  held_out_tasks: []
task_agent:
  model: gpt-5.6-luna
  credential_env: [OPENAI_API_KEY]
judge:
  model: claude-sonnet-4-6
  credential_env: [ANTHROPIC_API_KEY]
designer:
  model: gpt-5.6-sol
  rounds: 2
rubric:
  mode: {mode}
{proposer}  max_changes_per_task: 3
  max_output_tokens: 4096
audit:
  models: [gpt-5.6-sol]
"""


def test_load_harvey_experiment_resolves_paths_and_modes(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")

    experiment = load_experiment(path)

    assert experiment.output_dir == tmp_path / "output"
    assert experiment.cache_dir == tmp_path / "cache"
    assert experiment.benchmark.checkout == tmp_path / "checkout"
    assert experiment.rubric.mode == "prospective"
    assert experiment.designer.rounds == 2
    assert experiment.task_agent.model == "gpt-5.6-luna"
    assert experiment.audit.max_cost_usd is None


def test_static_harvey_experiment_rejects_proposer(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    text = _config_text(tmp_path, mode="static").replace(
        "  max_changes_per_task: 3",
        "  proposer_model: gpt-5.6-sol\n  max_changes_per_task: 3",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="must not configure a proposer"):
        load_experiment(path)


def test_harvey_experiment_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    text = _config_text(tmp_path).replace(
        "audit:\n  models: [gpt-5.6-sol]\n",
        "audit:\n"
        "  models: [gpt-5.6-sol]\n"
        "  models: [claude-opus-4-8]\n",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate YAML key: models"):
        load_experiment(path)


def test_task_rubric_proposer_preserves_ids_and_deliverables(tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps(_task()), encoding="utf-8")

    def generate(model: str, request: object) -> GenerationResult:
        assert model == "gpt-5.6-sol"
        text = json.dumps(
            {
                "summary": "Make the issue test more precise.",
                "changes": [
                    {
                        "criterion_id": "C-001",
                        "title": "Identifies the controlling issue",
                        "match_criteria": "PASS if the memo identifies the controlling issue and cites the clause. FAIL otherwise.",
                        "reason": "The old test accepted an unsupported label.",
                    }
                ],
            }
        )
        return GenerationResult(
            text=text,
            provider="openai",
            requested_model=model,
            effective_model=model,
            response_id="response-test",
            request_parameters=request_parameters_for_model(model),
        )

    result = TaskRubricProposer(
        "gpt-5.6-sol",
        base_url=None,
        max_changes=2,
        max_output_tokens=4096,
        generate_response=generate,  # type: ignore[arg-type]
    ).propose(task_file, {"score": 0.5})

    criteria = result.task["criteria"]
    assert isinstance(criteria, list)
    assert criteria[0]["id"] == "C-001"
    assert criteria[0]["deliverables"] == ["memo.md"]
    assert criteria[0]["title"] == "Identifies the controlling issue"
    assert criteria[1] == _task()["criteria"][1]


def test_current_ranking_keeps_nondominated_candidates_without_selecting_parent() -> None:
    evaluations = {
        "h0000": CandidateEvaluation("h0000", {}, 0.8, 0.5),
        "h0001": CandidateEvaluation("h0001", {}, 0.7, 0.8),
        "h0002": CandidateEvaluation("h0002", {}, 0.6, 0.4),
    }

    ranking = build_ranking("r0002", evaluations)

    assert ranking["pareto_frontier"] == ["h0000", "h0001"]
    assert [item["candidate_id"] for item in ranking["ranking"]] == [
        "h0000",
        "h0001",
        "h0002",
    ]
    assert "selected_parent" not in ranking


def test_tree_hash_rejects_symbolic_links(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "value.txt").write_text("value", encoding="utf-8")
    (root / "link").symlink_to(root / "value.txt")

    with pytest.raises(ValueError, match="link or special file"):
        tree_sha256(root)


def test_designer_parent_contract_uses_candidate_id_without_history_prefix(
    tmp_path: Path,
) -> None:
    assert "such as `h0000`" in DESIGNER_PROMPT
    assert "do not include the `history/` prefix" in DESIGNER_PROMPT
    workspace = tmp_path / "workspace"
    parent = tmp_path / "parent"
    harness = workspace / "candidate" / "harness"
    for root in (parent, harness):
        root.mkdir(parents=True)
        for name in ("run.py", "system_prompt.md", "agent_loop.py", "tools.py"):
            (root / name).write_text(name, encoding="utf-8")
    (harness / "run.py").write_text("changed", encoding="utf-8")
    (workspace / "proposal.json").write_text(
        json.dumps(
            {
                "parent_harness": "history/h0000",
                "hypothesis": "Improve review.",
                "mechanism": "Add an audit.",
                "expected_effect": "Find omissions.",
                "risks": ["More tokens."],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="without a history/ prefix"):
        CodexHarnessDesigner._validate_artifacts(
            workspace, {"h0000": parent}
        )


def test_designer_retries_semantically_invalid_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    for name in ("run.py", "system_prompt.md", "agent_loop.py", "tools.py"):
        (parent / name).write_text(name, encoding="utf-8")
    current = tmp_path / "current"
    current.mkdir()
    (current / "ranking.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    designer = CodexHarnessDesigner(
        HarnessDesigner("gpt-5.6-sol", 1, "high", "priority", 60, 1)
    )
    input_hash = designer.prepare_workspace(
        workspace,
        candidate_harnesses={"h0000": parent},
        canonical_evaluations={},
        current_dir=current,
    )
    prompts: list[str] = []

    class FakeRunner:
        def __init__(self, config, *, prompt: str, output_errors) -> None:
            prompts.append(prompt)
            assert output_errors.names == ("proposal.json",)

        def ensure_executable(self) -> None:
            return None

        def stream(self, paths) -> int:
            harness = workspace / "candidate" / "harness"
            if not harness.exists():
                shutil.copytree(parent, harness)
                (harness / "run.py").write_text("changed", encoding="utf-8")
            proposal = {
                "parent_harness": "history/h0000" if len(prompts) == 1 else "h0000",
                "hypothesis": "Improve review.",
                "mechanism": "Add an audit.",
                "expected_effect": "Find omissions.",
                "risks": ["More tokens."],
            }
            (workspace / "proposal.json").write_text(
                json.dumps(proposal), encoding="utf-8"
            )
            paths.stream_path.write_text(
                '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',
                encoding="utf-8",
            )
            return 0

        @staticmethod
        def trajectory_errors(path: Path) -> list[str]:
            return []

    monkeypatch.setattr(designer_module, "AgentRunner", FakeRunner)

    result = designer.run(
        workspace,
        tmp_path / "agent",
        expected_input_sha256=input_hash,
        candidate_harnesses={"h0000": parent},
    )

    assert result.parent_id == "h0000"
    assert len(prompts) == 2
    assert "without a history/ prefix" in prompts[1]


def test_podman_environment_uses_local_storage_and_shared_cache(
    tmp_path: Path,
) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    podman = commands / "podman"
    podman.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$HOME\" \"$XDG_CONFIG_HOME\" \"$@\"\n",
        encoding="utf-8",
    )
    podman.chmod(0o700)
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.write_text("other:100000:65536\n", encoding="utf-8")
    subgid.write_text("other:100000:65536\n", encoding="utf-8")

    environment = configured_podman_environment(
        {
            "PATH": str(commands),
            "XDG_RUNTIME_DIR": "/run/user/does-not-exist",
        },
        cache_root=tmp_path / "shared",
        temporary_root=tmp_path / "worker",
        uid=1234,
        username="researcher",
        subuid_path=subuid,
        subgid_path=subgid,
        cgroup_limits_available=False,
    )
    environment = configured_podman_environment(
        environment,
        cache_root=tmp_path / "shared",
        temporary_root=tmp_path / "worker",
        uid=1234,
        username="researcher",
        subuid_path=subuid,
        subgid_path=subgid,
        cgroup_limits_available=False,
    )

    assert environment["XDG_RUNTIME_DIR"].endswith(
        "rubric-gen-podman-1234/runtime"
    )
    assert environment["XDG_DATA_HOME"].endswith("rubric-gen-podman-1234/data")
    assert environment["UV_CACHE_DIR"] == str(
        tmp_path / "shared" / "user-1234" / "uv"
    )
    storage = Path(environment["CONTAINERS_STORAGE_CONF"])
    assert 'ignore_chown_errors = "true"' in storage.read_text(encoding="utf-8")
    assert str(tmp_path / "worker") in storage.read_text(encoding="utf-8")
    assert storage.stat().st_mode & 0o777 == 0o600
    home = Path(environment["XDG_CONFIG_HOME"]).parent
    policy = home / ".config" / "containers" / "policy.json"
    assert json.loads(policy.read_text(encoding="utf-8")) == {
        "default": [{"type": "insecureAcceptAnything"}]
    }
    wrapper = Path(environment["PATH"].split(os.pathsep, 1)[0]) / "podman"
    wrapper_text = wrapper.read_text(encoding="utf-8")
    assert f"export HOME={home}" in wrapper_text
    assert f"export XDG_CONFIG_HOME={home / '.config'}" in wrapper_text
    assert f"--signature-policy={policy}" in wrapper_text
    assert f'exec {podman} "$@"' in wrapper_text
    invocation = subprocess.run(
        [wrapper, "build", "-t", "sandbox", "."],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert invocation == [
        str(home),
        str(home / ".config"),
        "build",
        f"--signature-policy={policy}",
        "-t",
        "sandbox",
        ".",
    ]
    cached_pull = subprocess.run(
        [wrapper, "pull", "registry.example/sandbox:latest"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert cached_pull == [
        str(home),
        str(home / ".config"),
        "image",
        "exists",
        "registry.example/sandbox:latest",
    ]
    limited_run = subprocess.run(
        [
            wrapper,
            "run",
            "--cpus=2",
            "--memory=2g",
            "--pids-limit=256",
            "sandbox",
            "true",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert limited_run == [
        str(home),
        str(home / ".config"),
        "run",
        "sandbox",
        "true",
    ]


def test_shared_image_cache_saves_and_restores_oci_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = "lab-sandbox:latest"
    image_id = "sha256:harvey-image"
    local = True
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal local
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0 if local else 1,
                image_id + "\n" if local else "",
                "",
            )
        if command[1] == "save":
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b"oci archive")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1] == "load":
            local = True
            return subprocess.CompletedProcess(command, 0, "loaded", "")
        raise AssertionError(command)

    monkeypatch.setattr("rubric_gen.benchmarks.harvey_lab.podman.subprocess.run", run)
    cache_root = tmp_path / "shared"
    environment = {"PATH": "/usr/bin"}

    archive = cache_image(
        environment,
        cache_root=cache_root,
        image=image,
        uid=1234,
    )
    assert archive.read_bytes() == b"oci archive"
    assert sum(command[1] == "save" for command in calls) == 1

    local = False
    assert restore_cached_image(
        environment,
        cache_root=cache_root,
        image=image,
        uid=1234,
    )
    assert sum(command[1] == "load" for command in calls) == 1
    assert Path(calls[-2][calls[-2].index("--input") + 1]) == archive


def test_shared_image_cache_miss_does_not_pull(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[1:3] == ["image", "inspect"]
        return subprocess.CompletedProcess(command, 1, "", "missing")

    monkeypatch.setattr("rubric_gen.benchmarks.harvey_lab.podman.subprocess.run", run)

    assert not restore_cached_image(
        {"PATH": "/usr/bin"},
        cache_root=tmp_path / "shared",
        image="lab-sandbox:latest",
        uid=1234,
    )


def test_podman_environment_does_not_squash_users_when_subids_exist(
    tmp_path: Path,
) -> None:
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.write_text("researcher:100000:65536\n", encoding="utf-8")
    subgid.write_text("1234:200000:65536\n", encoding="utf-8")

    environment = configured_podman_environment(
        {},
        cache_root=tmp_path / "shared",
        temporary_root=tmp_path / "worker",
        uid=1234,
        username="researcher",
        subuid_path=subuid,
        subgid_path=subgid,
    )

    assert "CONTAINERS_STORAGE_CONF" not in environment


class _FakeEvaluator:
    def evaluate(
        self,
        identifier: str,
        harness: Path,
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation:
        value = 0.25 if identifier == "h0000" else 0.75
        scores = {}
        for task_id in task_files:
            score = {
                "n_passed": int(value * 4),
                "n_criteria": 4,
                "all_pass": value == 1,
            }
            scores[task_id] = score
            result = destination / "tasks" / task_id / "result"
            (result / "output").mkdir(parents=True)
            (result / "output" / "memo.md").write_text("memo", encoding="utf-8")
            (result / "scores.json").write_text(json.dumps(score), encoding="utf-8")
            (result / "metrics.json").write_text("{}", encoding="utf-8")
            (result / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
        evaluation = CandidateEvaluation(identifier, scores, value, 0.0)
        self._summary(destination, evaluation)
        return evaluation

    def rescore(
        self,
        identifier: str,
        source_results: dict[str, Path],
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation:
        scores = {
            task_id: {"n_passed": 2, "n_criteria": 4, "all_pass": False}
            for task_id in task_files
        }
        evaluation = CandidateEvaluation(identifier, scores, 0.5, 0.0)
        self._summary(destination, evaluation)
        return evaluation

    @staticmethod
    def _summary(destination: Path, evaluation: CandidateEvaluation) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "summary.json").write_text(
            json.dumps(
                {
                    "candidate_id": evaluation.candidate_id,
                    "tasks": evaluation.task_scores,
                    "mean_criterion_pass": evaluation.mean_criterion_pass,
                    "mean_all_pass": evaluation.mean_all_pass,
                }
            ),
            encoding="utf-8",
        )


class _FakeDesigner:
    def prepare_workspace(
        self,
        workspace: Path,
        *,
        candidate_harnesses: dict[str, Path],
        canonical_evaluations: dict[str, Path],
        current_dir: Path,
    ) -> str:
        workspace.mkdir(parents=True)
        (workspace / "instruction.md").write_text("instruction", encoding="utf-8")
        (workspace / "current").mkdir()
        shutil.copy2(current_dir / "ranking.json", workspace / "current" / "ranking.json")
        self.parent = candidate_harnesses["h0000"]
        return "inputs"

    def run(
        self,
        workspace: Path,
        run_dir: Path,
        *,
        expected_input_sha256: str,
        candidate_harnesses: dict[str, Path],
    ) -> DesignedCandidate:
        harness = workspace / "candidate" / "harness"
        shutil.copytree(self.parent, harness)
        for path in [harness, *harness.rglob("*")]:
            path.chmod(path.stat().st_mode | 0o700)
        (harness / "system_prompt.md").write_text("changed", encoding="utf-8")
        run_dir.mkdir(parents=True)
        trajectory = run_dir / "trajectory.stream.jsonl"
        trajectory.write_text("{}\n", encoding="utf-8")
        proposal = {
            "parent_harness": "h0000",
            "hypothesis": "A clearer prompt helps.",
            "mechanism": "Change the system prompt.",
            "expected_effect": "More complete work.",
            "risks": ["The prompt can be too long."],
        }
        return DesignedCandidate(
            "h0000", harness, proposal, tree_sha256(harness), trajectory, {}
        )


def _fake_checkout(root: Path) -> str:
    for name, content in {
        "harness/run.py": "# run\n",
        "harness/system_prompt.md": "stock\n",
        "harness/agent_loop.py": "# loop\n",
        "harness/tools.py": "# tools\n",
        "evaluation/run_eval.py": "# eval\n",
        "sandbox/sandbox.py": "# sandbox\n",
        "utils/__init__.py": "",
        "pyproject.toml": "[project]\nname='fake'\nversion='0.0.0'\n",
        "tasks/area/task/task.json": json.dumps(_task()),
        "tasks/area/task/documents/source.txt": "source",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_controller_runs_linear_round_with_free_parent_record_and_resumes(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "harvey"
    revision = _fake_checkout(checkout)
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(checkout, revision, ("area/task",), ()),
        task_agent=TaskAgent("gpt-5.5", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, 0, 1.0, "majority"),
    )
    controller = HarveyEvolutionController(
        experiment,
        evaluator=_FakeEvaluator(),
        designer=_FakeDesigner(),
    )

    assert controller.run() == 0
    assert controller.run(resume=True) == 0

    candidate = json.loads(
        (experiment.output_dir / "candidates" / "h0001" / "candidate.json").read_text()
    )
    ranking = json.loads(
        (experiment.output_dir / "rounds" / "r0001" / "current" / "ranking.json").read_text()
    )
    assert candidate["parent_harness"] == "h0000"
    assert [item["candidate_id"] for item in ranking["ranking"]] == ["h0001", "h0000"]
    assert run_quality_audit(experiment, evaluator=_FakeEvaluator()) == 0  # type: ignore[arg-type]
    quality = json.loads(
        (experiment.output_dir / "audits" / "quality-transfer" / "summary.json").read_text()
    )
    assert quality["candidates"]["h0001"]["active_minus_original"] == 0.25
    cases = prepare_reward_hacking_cases(experiment)
    assert [path.name for path in cases] == ["h0001"]
    transcript = json.loads((cases[0] / "transcript.json").read_text())
    assert any(
        message.get("name") == "accepted_harness_patch"
        for message in transcript["messages"]
    )


def test_production_evaluator_uses_runtime_modules_and_rescores_read_only_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "harvey"
    revision = _fake_checkout(checkout)
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(checkout, revision, ("area/task",), ()),
        task_agent=TaskAgent("gpt-5.5", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, 0, 1.0, "majority"),
    )
    calls: list[list[str]] = []

    def execute(
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        calls.append(command)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(label, encoding="utf-8")
        run_id = command[command.index("--run-id") + 1]
        result = runtime / "results" / run_id
        result.mkdir(parents=True, exist_ok=True)
        if label == "task agent":
            assert command[4:7] == ["python", "-m", "harness.run"]
            (result / "output").mkdir()
            (result / "output" / "memo.md").write_text("memo", encoding="utf-8")
            (result / "metrics.json").write_text("{}", encoding="utf-8")
            (result / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
        else:
            assert command[4:7] == ["python", "-m", "evaluation.run_eval"]
            (result / "scores.json").write_text(
                json.dumps({"n_passed": 1, "n_criteria": 2, "all_pass": False}),
                encoding="utf-8",
            )

    monkeypatch.setattr(HarveyEvaluator, "_execute", staticmethod(execute))
    evaluator = HarveyEvaluator(experiment, uv_executable="uv-test")
    active = {"area/task": checkout / "tasks" / "area" / "task" / "task.json"}
    canonical = tmp_path / "canonical"

    result = evaluator.evaluate("h0000", checkout / "harness", active, canonical)
    crossed = evaluator.rescore(
        "h0000",
        {"area/task": canonical / "tasks" / "area" / "task" / "result"},
        active,
        tmp_path / "crossed",
    )

    assert result.mean_criterion_pass == 0.5
    assert crossed.mean_criterion_pass == 0.5
    assert len(calls) == 3
