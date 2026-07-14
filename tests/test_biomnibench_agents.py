import argparse
import io
import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SCRIPT = ROOT / "scripts" / "run_biomnibench_agents.py"
SRC = ROOT / "src"


class BiomniBenchAgentTests(unittest.TestCase):
    def test_pyproject_exposes_uv_console_command(self):
        data = tomllib.loads(PYPROJECT.read_text())
        self.assertEqual(data["project"]["requires-python"], ">=3.11")
        self.assertEqual(
            data["project"]["scripts"]["biomnibench-agent"],
            "rubric_gen.biomnibench.cli:main",
        )

    def test_script_entrypoint_exists(self):
        text = SCRIPT.read_text()
        self.assertIn("uv run --script", text)
        self.assertIn("rubric_gen.biomnibench.cli", text)

    def import_core(self):
        import sys

        sys.path.insert(0, str(SRC))
        try:
            from rubric_gen import biomnibench
        finally:
            sys.path.pop(0)
        return biomnibench

    def test_console_command_target_imports(self):
        core = self.import_core()
        self.assertTrue(callable(core.main))
        self.assertIn("uv venv", core.PROMPT)

    def test_prompt_instructs_agent_to_use_uv_env(self):
        core = self.import_core()
        prompt = core.PROMPT
        self.assertIn("uv venv", prompt)
        self.assertIn(".venv", prompt)
        self.assertIn("Do not use web search, web fetch, or browser tools", prompt)
        self.assertIn("Keep trace.md concise", prompt)

    def test_progress_bar_format_shows_remaining_time(self):
        core = self.import_core()
        self.assertIn("{remaining} remaining", core.PROGRESS_BAR_FORMAT)

    def test_provider_registry_exposes_supported_agents(self):
        core = self.import_core()
        self.assertEqual(
            core.AgentAdapterRegistry().names,
            ("claude", "codex", "gemini"),
        )

    def test_facade_reexports_split_modules(self):
        core = self.import_core()
        from rubric_gen.biomnibench import adapters
        from rubric_gen.biomnibench import cli
        from rubric_gen.biomnibench import common
        from rubric_gen.biomnibench import runners

        self.assertIs(core.AgentRunConfig, common.AgentRunConfig)
        self.assertIs(core.GeminiAdapter, adapters.GeminiAdapter)
        self.assertIs(core.AgentRunner, runners.AgentRunner)
        self.assertIs(core.main, cli.main)

    def test_no_web_policy_denies_gemini_web_tools(self):
        core = self.import_core()
        policy = tomllib.loads(core.NO_WEB_POLICY)
        denied_tools = {
            rule["toolName"] for rule in policy["rule"] if rule["decision"] == "deny"
        }
        self.assertEqual(denied_tools, {"google_web_search", "web_fetch"})

    def test_cost_is_extracted_from_stream_json(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            stream = Path(tmp) / "trajectory.stream.jsonl"
            stream.write_text(
                "\n".join(
                    [
                        '{"type": "assistant", "message": "working"}',
                        '{"type": "result", "total_cost_usd": 0.0123}',
                        '{"type": "result", "usage": {"cost_usd": 0.0456}}',
                    ]
                )
                + "\n"
            )

            self.assertEqual(core.RunCost.from_stream(stream).cost_usd, 0.0456)

    def test_missing_cost_stream_returns_none(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            stream = Path(tmp) / "trajectory.stream.jsonl"
            stream.write_text('{"type": "result", "stats": {"total_tokens": 10}}\n')

            self.assertIsNone(core.RunCost.from_stream(stream).cost_usd)

    def test_gemini_cost_is_estimated_from_token_stats(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            stream = Path(tmp) / "trajectory.stream.jsonl"
            stream.write_text(
                json.dumps(
                    {
                        "type": "result",
                        "stats": {
                            "models": {
                                "gemini-3.5-flash": {
                                    "input": 1_000_000,
                                    "cached": 1_000_000,
                                    "output_tokens": 1_000_000,
                                },
                                "gemini-3.1-flash-lite": {
                                    "input": 1_000_000,
                                    "cached": 1_000_000,
                                    "output_tokens": 1_000_000,
                                },
                                "gemini-3-flash-preview": {
                                    "input": 1_000_000,
                                    "cached": 1_000_000,
                                    "output_tokens": 1_000_000,
                                },
                            }
                        },
                    }
                )
                + "\n"
            )

            cost = core.RunCost.from_stream(stream)
            self.assertIsNone(cost.cost_usd)
            self.assertEqual(cost.estimated_cost_usd, 15.975)
            self.assertEqual(cost.source, "estimated_google_gemini_api_standard")

    def test_default_command_uses_no_web_policy(self):
        core = self.import_core()
        config = core.AgentRunConfig.from_namespace(
            argparse.Namespace(
                provider="gemini",
                model=None,
                skip_trust=True,
                allow_web=False,
                approval_mode=None,
                sandbox=False,
                executable=None,
                extra_agent_arg=[],
            )
        )
        paths = core.RunPaths.for_task(
            task_dir=Path("/tmp/da-1-1"),
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            stamp="20260101-000000",
        )
        cmd = core.AgentRunner(config=config).build_command(paths)
        self.assertIn("--approval-mode", cmd)
        self.assertIn("yolo", cmd)
        self.assertIn("--policy", cmd)
        self.assertIn(str(paths.policy_path), cmd)

    def test_task_runner_builds_default_command(self):
        core = self.import_core()
        runner = core.AgentRunner(
            config=core.AgentRunConfig(provider="gemini", skip_trust=True),
        )
        paths = core.RunPaths.for_task(
            task_dir=Path("/tmp/da-1-1"),
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            stamp="20260101-000000",
        )
        cmd = runner.build_command(paths)

        self.assertIn("--approval-mode", cmd)
        self.assertIn("yolo", cmd)
        self.assertIn("--skip-trust", cmd)
        self.assertIn("--policy", cmd)
        self.assertIn(str(paths.policy_path), cmd)

    def test_allow_web_command_omits_no_web_policy(self):
        core = self.import_core()
        paths = core.RunPaths.for_task(
            task_dir=Path("/tmp/da-1-1"),
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            stamp="20260101-000000",
        )
        cmd = core.AgentRunner(
            config=core.AgentRunConfig(provider="gemini", allow_web=True),
        ).build_command(paths)
        self.assertNotIn("--policy", cmd)

    def test_sandbox_flag_is_forwarded(self):
        core = self.import_core()
        paths = core.RunPaths.for_task(
            task_dir=Path("/tmp/da-1-1"),
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            stamp="20260101-000000",
        )
        cmd = core.AgentRunner(
            config=core.AgentRunConfig(provider="gemini", sandbox=True),
        ).build_command(paths)
        self.assertIn("--sandbox", cmd)

    def test_claude_command_uses_headless_stream_json(self):
        core = self.import_core()
        paths = core.RunPaths.for_task(
            task_dir=Path("/tmp/da-1-1"),
            runs_dir=Path("/tmp/runs"),
            provider="claude",
            stamp="20260101-000000",
        )
        cmd = core.AgentRunner(
            config=core.AgentRunConfig(provider="claude", model="sonnet"),
        ).build_command(paths)

        self.assertEqual(cmd[0], "claude")
        self.assertIn("--print", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--permission-mode", cmd)
        self.assertIn("bypassPermissions", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("sonnet", cmd)
        self.assertIn("--disallowed-tools", cmd)

    def test_codex_command_uses_exec_json_and_workspace_sandbox(self):
        core = self.import_core()
        paths = core.RunPaths.for_task(
            task_dir=Path("/tmp/da-1-1"),
            runs_dir=Path("/tmp/runs"),
            provider="codex",
            stamp="20260101-000000",
        )
        cmd = core.AgentRunner(
            config=core.AgentRunConfig(provider="codex", model="gpt-5.1-codex"),
        ).build_command(paths)

        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertIn("--json", cmd)
        self.assertIn("--ask-for-approval", cmd)
        self.assertIn("never", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("workspace-write", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("gpt-5.1-codex", cmd)

    def test_prepare_workspace_hides_runner_metadata(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "da-1-1"
            data_dir = task_dir / "environment" / "data"
            data_dir.mkdir(parents=True)
            (task_dir / "instruction.md").write_text("task")
            (task_dir / "task.toml").write_text("verifier = true")
            (data_dir / "input.txt").write_text("data")
            workspace_dir = root / "run" / "workspace"

            core.TaskWorkspace(task_dir, workspace_dir).prepare()

            self.assertTrue((workspace_dir / "instruction.md").is_file())
            self.assertTrue((workspace_dir / "data" / "input.txt").is_file())
            self.assertFalse((workspace_dir / "task.toml").exists())
            self.assertFalse((workspace_dir / "prompt.txt").exists())
            self.assertFalse((workspace_dir / "no-web-policy.toml").exists())

    def test_run_paths_keep_metadata_outside_workspace(self):
        core = self.import_core()
        paths = core.RunPaths.for_task(
            task_dir=Path("/tmp/da-1-1"),
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            stamp="20260101-000000",
        )

        self.assertEqual(
            paths.workspace_dir,
            Path("/tmp/runs/_workspaces/da-1-1-gemini-20260101-000000"),
        )
        self.assertEqual(paths.provider, "gemini")
        self.assertEqual(paths.prompt_path.parent, paths.run_dir)
        self.assertEqual(paths.policy_path.parent, paths.run_dir)
        self.assertEqual(paths.stream_path.parent, paths.run_dir)
        self.assertNotEqual(paths.workspace_dir.parent, paths.run_dir)
        self.assertNotEqual(paths.prompt_path.parent, paths.workspace_dir)
        self.assertNotEqual(paths.policy_path.parent, paths.workspace_dir)

    def test_all_runner_discovers_tasks_and_skips_completed(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("da-2-1", "da-1-1"):
                task_data = root / "data" / name / "environment" / "data"
                task_data.mkdir(parents=True)
                (root / "data" / name / "instruction.md").write_text(name)

            tasks = core.TaskCatalog(root / "data").tasks()
            self.assertEqual([task.name for task in tasks], ["da-1-1", "da-2-1"])

            batch = root / "runs" / "all-gemini-20260101-000000"
            runner = core.BiomniBenchBatchRunner(
                config=core.BatchRunConfig(
                    tasks_dir=root / "data",
                    runs_dir=root / "runs",
                    provider="gemini",
                    resume_run=batch,
                )
            )
            self.assertEqual(
                [task.name for task in runner.discover_tasks()],
                ["da-1-1", "da-2-1"],
            )

            run = batch / "tasks" / "da-1-1"
            workspace = batch / "workspaces" / "da-1-1"
            workspace.mkdir(parents=True)
            (workspace / "trace.md").write_text("trace")
            (workspace / "answer.txt").write_text("answer")
            run.mkdir(parents=True)
            (run / "status.json").write_text(
                json.dumps(
                    {
                        "provider": "gemini",
                        "exit_code": 0,
                        "workspace_dir": str(workspace),
                    }
                )
            )

            completed = runner.completed_run("da-1-1")
            self.assertEqual(completed, run)
            self.assertEqual(runner.completed_run("da-1-1"), run)

            run2 = batch / "tasks" / "da-2-1"
            workspace2 = batch / "workspaces" / "da-2-1"
            workspace2.mkdir(parents=True)
            (workspace2 / "trace.md").write_text("trace")
            (workspace2 / "answer.txt").write_text("answer")
            (run2).mkdir(parents=True)
            (run2 / "status.json").write_text(
                json.dumps(
                    {
                        "provider": "gemini",
                        "exit_code": 0,
                        "workspace_dir": str(workspace2),
                    }
                )
            )

            completed2 = runner.completed_run("da-2-1")
            self.assertEqual(completed2, run2)

    def test_batch_paths_group_tasks_under_all_run_folder(self):
        core = self.import_core()

        paths = core.BatchRunPaths.create(
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            stamp="20260101-000000",
        )
        task_paths = paths.task_paths(Path("/tmp/data/da-1-1"))

        self.assertEqual(paths.batch_dir, Path("/tmp/runs/all-gemini-20260101-000000"))
        self.assertEqual(paths.summary_path, paths.batch_dir / "all-runs-summary.jsonl")
        self.assertEqual(paths.progress_path, paths.batch_dir / "progress.jsonl")
        self.assertEqual(task_paths.run_dir, paths.batch_dir / "tasks" / "da-1-1")
        self.assertEqual(
            task_paths.workspace_dir, paths.batch_dir / "workspaces" / "da-1-1"
        )

    def test_batch_config_can_resume_existing_all_run_folder(self):
        core = self.import_core()

        config = core.BatchRunConfig(
            tasks_dir=Path("/tmp/data"),
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            resume_run=Path("/tmp/runs/all-gemini-old"),
        )
        runner = core.BiomniBenchBatchRunner(config=config)

        self.assertEqual(runner.batch_paths.batch_dir, Path("/tmp/runs/all-gemini-old"))
        self.assertTrue(runner.batch_paths.is_resume)

    def test_all_runner_respects_max_concurrency(self):
        core = self.import_core()

        class FakeAgentRunner:
            def __init__(self):
                self.calls = []

            def run(self, task_dir, paths):
                self.calls.append(task_dir.name)
                paths.run_dir.mkdir(parents=True, exist_ok=True)
                paths.workspace_dir.mkdir(parents=True, exist_ok=True)
                paths.stream_path.write_text("{}\n")
                (paths.workspace_dir / "trace.md").write_text("trace")
                (paths.workspace_dir / "answer.txt").write_text("answer")
                paths.status_path.write_text(
                    json.dumps(
                        {
                            "provider": "gemini",
                            "process_exit_code": 0,
                            "exit_code": 0,
                            "validation_errors": [],
                            "suspicious_files": [],
                        }
                    )
                    + "\n"
                )
                return 0, paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("da-1-1", "da-2-1"):
                task_dir = root / "data" / name
                (task_dir / "environment" / "data").mkdir(parents=True)
                (task_dir / "instruction.md").write_text(name)

            fake = FakeAgentRunner()
            runner = core.BiomniBenchBatchRunner(
                config=core.BatchRunConfig(
                    tasks_dir=root / "data",
                    runs_dir=root / "runs",
                    provider="gemini",
                    max_concurrency=2,
                ),
                agent_runner=fake,
            )

            exit_code = runner.run()
            records = [
                json.loads(line)
                for line in runner.summary_path.read_text().splitlines()
            ]
            status = json.loads(runner.batch_paths.status_path.read_text())

            self.assertEqual(exit_code, 0)
            self.assertEqual(sorted(fake.calls), ["da-1-1", "da-2-1"])
            self.assertEqual(
                sorted(record["task"] for record in records), ["da-1-1", "da-2-1"]
            )
            self.assertEqual(status["max_concurrency"], 2)

    def test_batch_agent_config_is_quiet_for_progress_bar_only(self):
        core = self.import_core()

        config = core.BatchRunConfig(
            tasks_dir=Path("/tmp/data"),
            runs_dir=Path("/tmp/runs"),
            provider="gemini",
            raw=True,
        ).agent_config()

        self.assertTrue(config.quiet)
        self.assertTrue(config.raw)

    def test_single_agent_config_is_not_quiet_by_default(self):
        core = self.import_core()

        config = core.AgentRunConfig.from_namespace(
            argparse.Namespace(
                provider="gemini",
                model=None,
                raw=False,
                skip_trust=False,
                allow_web=False,
                approval_mode=None,
                sandbox=False,
                executable=None,
                extra_agent_arg=[],
            )
        )

        self.assertFalse(config.quiet)

    def test_quiet_runner_logs_stream_without_printing_agent_lines(self):
        core = self.import_core()

        runner = core.AgentRunner(
            config=core.AgentRunConfig(provider="gemini", quiet=True)
        )
        printed = []
        runner.adapter.print_line = lambda line, raw=False: printed.append((line, raw))
        log = io.StringIO()

        runner._tee_stream(
            io.StringIO('{"type": "message", "content": "hidden"}\n'), log
        )

        self.assertEqual(log.getvalue(), '{"type": "message", "content": "hidden"}\n')
        self.assertEqual(printed, [])

    def test_runner_validation_fails_when_required_outputs_are_missing(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.RunPaths.for_task(
                task_dir=root / "da-1-1",
                runs_dir=root / "runs",
                provider="gemini",
                stamp="20260101-000000",
            )
            paths.run_dir.mkdir(parents=True)
            paths.workspace_dir.mkdir(parents=True)
            (paths.workspace_dir / "trace.md").write_text("trace")

            validation = core.AgentRunner().validate_outputs(paths)

            self.assertFalse(validation.ok)
            self.assertIn("missing_or_empty: answer.txt", validation.errors)

    def test_runner_validation_records_sibling_run_path_leaks_without_failing(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.BatchRunPaths.create(
                runs_dir=root / "runs",
                provider="gemini",
                stamp="20260101-000000",
            ).task_paths(root / "data" / "da-1-1")
            paths.run_dir.mkdir(parents=True)
            paths.workspace_dir.mkdir(parents=True)
            (paths.workspace_dir / "trace.md").write_text("trace")
            (paths.workspace_dir / "answer.txt").write_text("answer")
            leak = root / "runs" / "_workspaces" / "da-1-1-gemini-old" / "trace.md"
            (paths.workspace_dir / "read_other_trace.py").write_text(
                f'open("{leak}")\n'
            )

            validation = core.AgentRunner().validate_outputs(paths)

            self.assertTrue(validation.ok)
            self.assertEqual(len(validation.suspicious_files), 1)
            self.assertIn("read_other_trace.py", validation.suspicious_files[0])

    def test_runner_validation_flags_error_events_in_trajectory(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.RunPaths.for_task(
                task_dir=root / "da-1-1",
                runs_dir=root / "runs",
                provider="gemini",
                stamp="20260101-000000",
            )
            paths.run_dir.mkdir(parents=True)
            paths.workspace_dir.mkdir(parents=True)
            (paths.workspace_dir / "trace.md").write_text("trace")
            (paths.workspace_dir / "answer.txt").write_text("answer")
            paths.stream_path.write_text(
                '{"type": "error", "message": "Invalid stream"}\n'
                '{"type": "result", "status": "error"}\n'
            )

            validation = core.AgentRunner().validate_outputs(paths)

            self.assertFalse(validation.ok)
            self.assertIn("trajectory_error: Invalid stream", validation.errors)
            self.assertIn("trajectory_result_status: error", validation.errors)

    def test_runner_retries_transient_stream_failures_and_preserves_attempt_log(self):
        core = self.import_core()

        class RetryRunner(core.AgentRunner):
            def __init__(self):
                super().__init__(
                    config=core.AgentRunConfig(provider="gemini", retries=1)
                )
                self.stream_calls = 0

            def ensure_executable(self):
                return None

            def stream(self, paths):
                self.stream_calls += 1
                paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
                if self.stream_calls == 1:
                    paths.stream_path.write_text(
                        '{"type": "error", "message": "Invalid stream"}\n'
                        '{"type": "result", "status": "error"}\n'
                    )
                    (paths.workspace_dir / "trace.md").write_text("trace")
                    return 0

                paths.stream_path.write_text(
                    '{"type": "result", "status": "success"}\n'
                )
                (paths.workspace_dir / "trace.md").write_text("trace")
                (paths.workspace_dir / "answer.txt").write_text("answer")
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "environment" / "data").mkdir(parents=True)
            (task_dir / "instruction.md").write_text("task")
            paths = core.RunPaths.for_task(
                task_dir=task_dir,
                runs_dir=root / "runs",
                provider="gemini",
                stamp="20260101-000000",
            )
            runner = RetryRunner()

            exit_code, _ = runner.run(task_dir, paths=paths)
            status = json.loads(paths.status_path.read_text())

            self.assertEqual(exit_code, 0)
            self.assertEqual(runner.stream_calls, 2)
            self.assertEqual(status["attempt_count"], 2)
            self.assertEqual(status["process_exit_code"], 0)
            self.assertEqual(status["exit_code"], 0)
            self.assertTrue(
                (
                    paths.run_dir / "attempts" / "attempt-1.trajectory.stream.jsonl"
                ).is_file()
            )

    def test_cli_exposes_resume_run_for_all_tasks(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "all",
                "--provider",
                "gemini",
                "--resume-run",
                "runs/biomnibench-agents/all-gemini-old",
            ]
        )

        self.assertEqual(args.resume_run, "runs/biomnibench-agents/all-gemini-old")

    def test_cli_exposes_max_concurrency_for_all_tasks(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "all",
                "--provider",
                "gemini",
                "--tasks-dir",
                "data/biomnibench-da",
                "--max-concurrency",
                "3",
            ]
        )

        self.assertEqual(args.max_concurrency, 3)
        config = core.BatchRunConfig.from_namespace(args)
        self.assertEqual(config.max_concurrency, 3)

    def test_cli_exposes_judge_review_modes(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "judge",
                "--run-dir",
                "runs/biomnibench-agents/all-gemini-old",
                "--review",
                "trajectory",
                "--resume",
                "--dry-run",
                "--max-concurrency",
                "4",
                "--repeats",
                "5",
                "--rubric",
                "process_rubric.txt",
            ]
        )

        self.assertEqual(args.command, "judge")
        self.assertEqual(args.review, "trajectory")
        self.assertTrue(args.resume)
        self.assertTrue(args.dry_run)
        self.assertEqual(args.max_concurrency, 4)
        self.assertEqual(args.repeats, 5)
        self.assertEqual(args.rubric, "process_rubric.txt")

        config = core.JudgeRunConfig.from_namespace(args)
        self.assertEqual(config.rubric_name, "process_rubric.txt")
        self.assertEqual(config.max_concurrency, 4)

    def test_cli_rejects_old_judge_jobs_flag(self):
        core = self.import_core()

        parser = core.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "judge",
                    "--run-dir",
                    "runs/biomnibench-agents/all-gemini-old",
                    "--jobs",
                    "4",
                ]
            )

    def test_cli_exposes_llm_perturb_command(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "perturb",
                "--base-run",
                "runs/biomnibench-agents/all-gemini-old",
                "--tasks",
                "da-26-4,da-10-1",
                "--out-dir",
                "runs/biomnibench-perturbations/pilot",
                "--dry-run",
            ]
        )

        self.assertEqual(args.command, "perturb")
        self.assertEqual(args.perturber_model, "gemini-3.5-flash")
        self.assertEqual(args.levels, "C,L0,L1,L2,L3,L4,L5")
        self.assertEqual(args.tasks, "da-26-4,da-10-1")
        self.assertTrue(args.dry_run)

        config = core.PerturbationRunConfig.from_namespace(args)
        self.assertEqual(config.model, "gemini-3.5-flash")
        self.assertEqual(config.api_key_env, "GEMINI_API_KEY")
        self.assertEqual(config.levels, ("C", "L0", "L1", "L2", "L3", "L4", "L5"))
        self.assertEqual(config.tasks, ("da-26-4", "da-10-1"))
        self.assertFalse(config.resume)
        self.assertEqual(config.max_concurrency, 30)

        resume_args = parser.parse_args(
            [
                "perturb",
                "--base-run",
                "runs/biomnibench-agents/all-gemini-old",
                "--out-dir",
                "runs/biomnibench-perturbations/pilot",
                "--resume",
                "--dry-run",
            ]
        )
        self.assertTrue(core.PerturbationRunConfig.from_namespace(resume_args).resume)

        concurrency_args = parser.parse_args(
            [
                "perturb",
                "--base-run",
                "runs/biomnibench-agents/all-gemini-old",
                "--out-dir",
                "runs/biomnibench-perturbations/pilot",
                "--max-concurrency",
                "7",
                "--api-key-env",
                "GOOGLE_API_KEY",
                "--dry-run",
            ]
        )
        concurrency_config = core.PerturbationRunConfig.from_namespace(concurrency_args)
        self.assertEqual(concurrency_config.max_concurrency, 7)
        self.assertEqual(concurrency_config.api_key_env, "GOOGLE_API_KEY")

    def test_cli_perturb_defaults_to_all_discovered_tasks(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "perturb",
                "--base-run",
                "runs/biomnibench-agents/all-gemini-old",
                "--out-dir",
                "runs/biomnibench-perturbations/all-pilot",
                "--dry-run",
            ]
        )

        self.assertIsNone(args.tasks)
        config = core.PerturbationRunConfig.from_namespace(args)
        self.assertEqual(config.tasks, ())

    def test_cli_exposes_llm_process_rubrics_command(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "process-rubrics",
                "--tasks-dir",
                "data/biomnibench-da",
                "--run-dir",
                "runs/biomnibench-agents/all-gemini-old",
                "--model",
                "gemini-test",
                "--max-concurrency",
                "6",
                "--max-retries",
                "4",
                "--resume",
            ]
        )

        self.assertEqual(args.command, "process-rubrics")
        self.assertEqual(args.model, "gemini-test")
        self.assertEqual(args.max_concurrency, 6)
        self.assertEqual(args.max_retries, 4)
        self.assertTrue(args.resume)

        config = core.ProcessRubricConfig.from_namespace(args)
        self.assertEqual(config.model, "gemini-test")
        self.assertEqual(config.max_concurrency, 6)
        self.assertEqual(config.max_retries, 4)
        self.assertTrue(config.resume)

    def test_cli_rejects_removed_process_rubric_modes(self):
        core = self.import_core()

        parser = core.build_parser()
        for removed_flag in ("--dry-run", "--check", "--template-only"):
            with self.assertRaises(SystemExit):
                parser.parse_args(["process-rubrics", removed_flag])

    def test_process_rubric_runner_uses_llm_rewriter(self):
        core = self.import_core()

        class FakeRewriter:
            def __init__(self):
                self.requests = []

            def rewrite(self, request):
                self.requests.append(request)
                return request.deterministic_draft_txt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "biomnibench-da" / "da-1-1"
            tests_dir = task_dir / "tests"
            tests_dir.mkdir(parents=True)
            (task_dir / "instruction.md").write_text(
                "## Question\nCompare treated and control samples.\n\n## Data Files\n- `data/counts.csv`\n"
            )
            (tests_dir / "rubric.txt").write_text(
                "Criterion 1: Correct comparison\n"
                "Description: Compares treated and control samples.\n"
                "Levels: A=100 B=50 C=0\n"
            )

            run_dir = root / "runs" / "all-gemini"
            task_run = run_dir / "tasks" / "da-1-1"
            workspace = run_dir / "workspaces" / "da-1-1"
            task_run.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (task_run / "trajectory.stream.jsonl").write_text(
                '{"type": "tool_use", "tool_name": "shell", "parameters": {"command": "python analyze.py"}}\n'
            )
            (workspace / "trace.md").write_text(
                "# Objective\nCompare groups\n# Results\nSome result"
            )
            (workspace / "answer.txt").write_text("treated differs from control")

            rewriter = FakeRewriter()
            runner = core.ProcessRubricGenerator(
                core.ProcessRubricConfig(
                    tasks_dir=root / "data" / "biomnibench-da",
                    run_dir=run_dir,
                    expected_tasks=1,
                ),
                rewriter=rewriter,
            )

            self.assertEqual(runner.run(), 0)
            output = tests_dir / "process_rubric.txt"
            self.assertTrue(output.is_file())
            self.assertIn("PROCESS RUBRIC: DA-1-1", output.read_text())
            self.assertEqual(len(rewriter.requests), 1)
            self.assertIn(
                "Compare treated and control", rewriter.requests[0].instruction_md
            )
            self.assertIn(
                "Correct comparison", rewriter.requests[0].original_rubric_txt
            )

    def test_process_rubric_runner_uses_existing_rubrics_as_examples(self):
        core = self.import_core()
        import sys

        sys.path.insert(0, str(SRC))
        try:
            from rubric_gen.biomnibench.process_rubrics import (
                build_rubric,
                discover_bundles,
            )
        finally:
            sys.path.pop(0)

        class CapturingRewriter:
            def __init__(self):
                self.requests = []

            def rewrite(self, request):
                self.requests.append(request)
                return request.deterministic_draft_txt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_dir = root / "data" / "biomnibench-da"
            run_dir = root / "runs" / "all-gemini"
            for task_id in ("da-1-1", "da-2-1"):
                task_dir = tasks_dir / task_id
                tests_dir = task_dir / "tests"
                tests_dir.mkdir(parents=True)
                (task_dir / "instruction.md").write_text(
                    f"## Question\nAnalyze {task_id}.\n\n## Data Files\n- `data/counts.csv`\n"
                )
                (tests_dir / "rubric.txt").write_text(
                    "Criterion 1: Correct answer\n"
                    "Description: Answers the task.\n"
                    "Levels: A=100 B=50 C=0\n"
                )
                task_run = run_dir / "tasks" / task_id
                workspace = run_dir / "workspaces" / task_id
                task_run.mkdir(parents=True)
                workspace.mkdir(parents=True)
                (task_run / "trajectory.stream.jsonl").write_text(
                    '{"type": "tool_use", "tool_name": "shell", "parameters": {"command": "python analyze.py"}}\n'
                )
                (workspace / "trace.md").write_text(
                    "# Objective\nAnalyze\n# Results\nSome result"
                )
                (workspace / "answer.txt").write_text("answer")

            bundles = discover_bundles(tasks_dir, run_dir)
            (tasks_dir / "da-1-1" / "tests" / "process_rubric.txt").write_text(
                build_rubric(bundles[0])
            )

            rewriter = CapturingRewriter()
            runner = core.ProcessRubricGenerator(
                core.ProcessRubricConfig(
                    tasks_dir=tasks_dir,
                    run_dir=run_dir,
                    expected_tasks=2,
                    example_task_ids=("da-1-1",),
                ),
                rewriter=rewriter,
            )

            self.assertEqual(runner.run(), 0)
            self.assertEqual(len(rewriter.requests), 1)
            self.assertEqual(rewriter.requests[0].task_id, "da-2-1")
            self.assertIn(
                "### Example da-1-1", rewriter.requests[0].example_process_rubrics_txt
            )
            self.assertTrue(
                (tasks_dir / "da-1-1" / "tests" / "process_rubric.txt").is_file()
            )
            self.assertTrue(
                (tasks_dir / "da-2-1" / "tests" / "process_rubric.txt").is_file()
            )

    def test_process_rubric_resume_requires_success_marker(self):
        core = self.import_core()
        import sys

        sys.path.insert(0, str(SRC))
        try:
            from rubric_gen.biomnibench.process_rubrics import (
                build_rubric,
                discover_bundles,
            )
        finally:
            sys.path.pop(0)

        class CapturingRewriter:
            def __init__(self):
                self.requests = []

            def rewrite(self, request):
                self.requests.append(request)
                return request.deterministic_draft_txt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_dir = root / "data" / "biomnibench-da"
            run_dir = root / "runs" / "all-gemini"
            task_dir = tasks_dir / "da-1-1"
            tests_dir = task_dir / "tests"
            tests_dir.mkdir(parents=True)
            (task_dir / "instruction.md").write_text(
                "## Question\nAnalyze task.\n\n## Data Files\n- `data/counts.csv`\n"
            )
            (tests_dir / "rubric.txt").write_text(
                "Criterion 1: Correct answer\n"
                "Description: Answers the task.\n"
                "Levels: A=100 B=50 C=0\n"
            )
            task_run = run_dir / "tasks" / "da-1-1"
            workspace = run_dir / "workspaces" / "da-1-1"
            task_run.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (task_run / "trajectory.stream.jsonl").write_text(
                '{"type": "tool_use", "tool_name": "shell", "parameters": {"command": "python analyze.py"}}\n'
            )
            (workspace / "trace.md").write_text(
                "# Objective\nAnalyze\n# Results\nSome result"
            )
            (workspace / "answer.txt").write_text("answer")

            bundle = discover_bundles(tasks_dir, run_dir)[0]
            (tests_dir / "process_rubric.txt").write_text(build_rubric(bundle))
            rewriter = CapturingRewriter()
            runner = core.ProcessRubricGenerator(
                core.ProcessRubricConfig(
                    tasks_dir=tasks_dir,
                    run_dir=run_dir,
                    expected_tasks=1,
                    resume=True,
                    example_task_ids=(),
                ),
                rewriter=rewriter,
            )

            self.assertEqual(runner.run(), 0)
            self.assertEqual(len(rewriter.requests), 1)
            self.assertTrue(
                (run_dir / "process-rubrics" / "da-1-1" / "success.json").is_file()
            )

            self.assertEqual(runner.run(), 0)
            self.assertEqual(len(rewriter.requests), 1)

    def test_process_rubric_runner_continues_after_invalid_llm_output(self):
        core = self.import_core()

        class PartlyBadRewriter:
            def rewrite(self, request):
                if request.task_id == "da-1-1":
                    return "too short\n"
                return request.deterministic_draft_txt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_dir = root / "data" / "biomnibench-da"
            run_dir = root / "runs" / "all-gemini"
            for task_id in ("da-1-1", "da-2-1"):
                task_dir = tasks_dir / task_id
                tests_dir = task_dir / "tests"
                tests_dir.mkdir(parents=True)
                (task_dir / "instruction.md").write_text(
                    f"## Question\nAnalyze {task_id}.\n\n## Data Files\n- `data/counts.csv`\n"
                )
                (tests_dir / "rubric.txt").write_text(
                    "Criterion 1: Correct answer\n"
                    "Description: Answers the task.\n"
                    "Levels: A=100 B=50 C=0\n"
                )
                task_run = run_dir / "tasks" / task_id
                workspace = run_dir / "workspaces" / task_id
                task_run.mkdir(parents=True)
                workspace.mkdir(parents=True)
                (task_run / "trajectory.stream.jsonl").write_text(
                    '{"type": "tool_use", "tool_name": "shell", "parameters": {"command": "python analyze.py"}}\n'
                )
                (workspace / "trace.md").write_text(
                    "# Objective\nAnalyze\n# Results\nSome result"
                )
                (workspace / "answer.txt").write_text("answer")

            runner = core.ProcessRubricGenerator(
                core.ProcessRubricConfig(
                    tasks_dir=tasks_dir,
                    run_dir=run_dir,
                    expected_tasks=2,
                    max_retries=1,
                    max_concurrency=2,
                ),
                rewriter=PartlyBadRewriter(),
            )

            self.assertEqual(runner.run(), 1)
            self.assertFalse(
                (tasks_dir / "da-1-1" / "tests" / "process_rubric.txt").exists()
            )
            self.assertTrue(
                (tasks_dir / "da-2-1" / "tests" / "process_rubric.txt").is_file()
            )
            self.assertTrue(
                (
                    run_dir / "process-rubrics" / "da-1-1" / "attempt-01-error.txt"
                ).is_file()
            )
            self.assertTrue(
                (
                    run_dir / "process-rubrics" / "da-1-1" / "attempt-02-error.txt"
                ).is_file()
            )

    def test_process_rubric_validation_rejects_outline_without_level_descriptions(self):
        import sys

        sys.path.insert(0, str(SRC))
        try:
            from rubric_gen.biomnibench.process_rubrics import validate_rubric_text
        finally:
            sys.path.pop(0)

        criteria = []
        for index in range(1, 7):
            criteria.append(
                f"Criterion {index}: Outline Criterion\n"
                "Description: This criterion has a description but no bracketed level descriptions.\n"
                "Levels: A=10 B=5 C=0\n"
            )
        outline = (
            "PROCESS RUBRIC: DA-1-1\n\nTotal Points: 100/100\n\nEvidence-gated scoring rules:\n"
            + "\n".join(criteria)
        )

        errors = validate_rubric_text("da-1-1", outline, "original")

        self.assertTrue(
            any("missing [A] level description" in error for error in errors)
        )

    def test_llm_perturb_runner_writes_judge_compatible_levels(self):
        core = self.import_core()

        class FakePerturber:
            def perturb(self, request):
                return core.PerturbationResult(
                    level=request.level,
                    intent="make the run less useful",
                    trace_md=f"perturbed {request.level} trace",
                    answer_txt=f"perturbed {request.level} answer",
                    trajectory_stream_jsonl='{"type": "message", "content": "perturbed"}\n',
                    preserved_claims=("main claim",),
                    perturbation_notes=("mock perturbation",),
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "instruction.md").write_text("Solve this local task.\n")
            (task_dir / "tests" / "rubric.txt").write_text(
                "OUTCOME RUBRIC SHOULD NOT BE READ\n"
            )
            (task_dir / "tests" / "process_rubric.txt").write_text(
                "PROCESS RUBRIC SHOULD NOT BE READ\n"
            )

            base = root / "runs" / "all-gemini-20260101-000000"
            run_dir = base / "tasks" / "da-1-1"
            workspace = base / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (run_dir / "trajectory.stream.jsonl").write_text(
                '{"type": "message", "content": "original"}\n'
            )
            (workspace / "trace.md").write_text("original trace")
            (workspace / "answer.txt").write_text("original answer")
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            out_dir = root / "perturbed"
            runner = core.BiomniBenchPerturbationRunner(
                core.PerturbationRunConfig(
                    base_run=base,
                    out_dir=out_dir,
                    tasks=("da-1-1",),
                    levels=("C", "L0"),
                ),
                perturber=FakePerturber(),
            )

            exit_code = runner.run()
            manifest = json.loads((out_dir / "perturbation_manifest.json").read_text())

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                (out_dir / "C" / "workspaces" / "da-1-1" / "trace.md").read_text(),
                "original trace",
            )
            self.assertEqual(
                (out_dir / "L0" / "workspaces" / "da-1-1" / "trace.md").read_text(),
                "perturbed L0 trace",
            )
            self.assertTrue(
                (out_dir / "L0" / "tasks" / "da-1-1" / "status.json").is_file()
            )
            self.assertTrue(
                (
                    out_dir / "L0" / "tasks" / "da-1-1" / "trajectory.stream.jsonl"
                ).is_file()
            )
            complete = json.loads(
                (
                    out_dir / "L0" / "tasks" / "da-1-1" / "perturbation_complete.json"
                ).read_text()
            )
            self.assertEqual(complete["status"], "complete")
            self.assertEqual(complete["level"], "L0")
            self.assertEqual(manifest["model"], "gemini-3.5-flash")
            self.assertEqual(
                [record["level"] for record in manifest["records"]], ["C", "L0"]
            )
            self.assertEqual(
                manifest["records"][1]["perturbation_notes"], ["mock perturbation"]
            )

    def test_perturb_runner_normalizes_invalid_generated_trajectory_jsonl(self):
        core = self.import_core()

        class BadTrajectoryPerturber:
            def perturb(self, request):
                return core.PerturbationResult(
                    level=request.level,
                    intent="make a cosmetic edit",
                    trace_md="perturbed trace",
                    answer_txt="perturbed answer",
                    trajectory_stream_jsonl=(
                        '{"type": "message", "content": "ok"}\n'
                        '{"type": "message", "content": "bad \\escape"}\n'
                        '{"type": "message", "content": "unterminated}\n'
                    ),
                    perturbation_notes=("mock bad trajectory",),
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "instruction.md").write_text("Solve this local task.\n")

            base = root / "runs" / "all-gemini-20260101-000000"
            run_dir = base / "tasks" / "da-1-1"
            workspace = base / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (run_dir / "trajectory.stream.jsonl").write_text(
                '{"type": "message", "content": "original"}\n'
            )
            (workspace / "trace.md").write_text("original trace")
            (workspace / "answer.txt").write_text("original answer")
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            out_dir = root / "perturbed"
            runner = core.BiomniBenchPerturbationRunner(
                core.PerturbationRunConfig(
                    base_run=base,
                    out_dir=out_dir,
                    tasks=("da-1-1",),
                    levels=("L1",),
                ),
                perturber=BadTrajectoryPerturber(),
            )

            self.assertEqual(runner.run(), 0)
            trajectory = (
                out_dir / "L1" / "tasks" / "da-1-1" / "trajectory.stream.jsonl"
            ).read_text()
            events = [json.loads(line) for line in trajectory.splitlines()]
            self.assertEqual(events[0]["type"], "message")
            self.assertEqual(events[1]["type"], "perturbed_invalid_json_line")
            self.assertEqual(events[2]["type"], "perturbed_invalid_json_line")
            manifest = json.loads((out_dir / "perturbation_manifest.json").read_text())
            self.assertIn(
                "normalized 2 invalid", manifest["records"][0]["perturbation_notes"][-1]
            )

    def test_perturb_runner_overwrites_existing_output_by_default(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "instruction.md").write_text("Solve this local task.\n")

            base = root / "runs" / "all-gemini-20260101-000000"
            run_dir = base / "tasks" / "da-1-1"
            workspace = base / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (run_dir / "trajectory.stream.jsonl").write_text(
                '{"type": "message", "content": "original"}\n'
            )
            (workspace / "trace.md").write_text("fresh trace")
            (workspace / "answer.txt").write_text("fresh answer")
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            out_dir = root / "perturbed"
            out_dir.mkdir()
            (out_dir / "stale.txt").write_text("old")

            runner = core.BiomniBenchPerturbationRunner(
                core.PerturbationRunConfig(
                    base_run=base,
                    out_dir=out_dir,
                    levels=("C",),
                )
            )

            self.assertEqual(runner.run(), 0)
            self.assertFalse((out_dir / "stale.txt").exists())
            self.assertEqual(
                (out_dir / "C" / "workspaces" / "da-1-1" / "trace.md").read_text(),
                "fresh trace",
            )

    def test_perturb_runner_resume_preserves_existing_level_outputs(self):
        core = self.import_core()

        class RaisingPerturber:
            def perturb(self, request):
                raise AssertionError(
                    "resume should not call perturber for complete outputs"
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "instruction.md").write_text("Solve this local task.\n")

            base = root / "runs" / "all-gemini-20260101-000000"
            run_dir = base / "tasks" / "da-1-1"
            workspace = base / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (run_dir / "trajectory.stream.jsonl").write_text(
                '{"type": "message", "content": "original"}\n'
            )
            (workspace / "trace.md").write_text("fresh trace")
            (workspace / "answer.txt").write_text("fresh answer")
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            out_dir = root / "perturbed"
            existing_run = out_dir / "L0" / "tasks" / "da-1-1"
            existing_workspace = out_dir / "L0" / "workspaces" / "da-1-1"
            existing_run.mkdir(parents=True)
            existing_workspace.mkdir(parents=True)
            (existing_run / "trajectory.stream.jsonl").write_text(
                '{"type": "message", "content": "old"}\n'
            )
            (existing_run / "status.json").write_text("{}\n")
            (existing_run / "perturbation_complete.json").write_text(
                json.dumps({"status": "complete", "task": "da-1-1", "level": "L0"})
                + "\n"
            )
            (existing_workspace / "trace.md").write_text("old trace")
            (existing_workspace / "answer.txt").write_text("old answer")

            runner = core.BiomniBenchPerturbationRunner(
                core.PerturbationRunConfig(
                    base_run=base,
                    out_dir=out_dir,
                    levels=("L0",),
                    resume=True,
                ),
                perturber=RaisingPerturber(),
            )

            self.assertEqual(runner.run(), 0)
            self.assertEqual((existing_workspace / "trace.md").read_text(), "old trace")
            manifest = json.loads((out_dir / "perturbation_manifest.json").read_text())
            self.assertEqual(manifest["records"][0]["status"], "resumed")

    def test_perturb_runner_resume_reruns_outputs_without_completion_marker(self):
        core = self.import_core()

        class FakePerturber:
            def perturb(self, request):
                return core.PerturbationResult(
                    level=request.level,
                    intent="rerun incomplete output",
                    trace_md="new trace",
                    answer_txt="new answer",
                    trajectory_stream_jsonl='{"type": "message", "content": "new"}\n',
                    perturbation_notes=("reran missing marker",),
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "instruction.md").write_text("Solve this local task.\n")

            base = root / "runs" / "all-gemini-20260101-000000"
            run_dir = base / "tasks" / "da-1-1"
            workspace = base / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (run_dir / "trajectory.stream.jsonl").write_text(
                '{"type": "message", "content": "original"}\n'
            )
            (workspace / "trace.md").write_text("fresh trace")
            (workspace / "answer.txt").write_text("fresh answer")
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            out_dir = root / "perturbed"
            existing_run = out_dir / "L0" / "tasks" / "da-1-1"
            existing_workspace = out_dir / "L0" / "workspaces" / "da-1-1"
            existing_run.mkdir(parents=True)
            existing_workspace.mkdir(parents=True)
            (existing_run / "trajectory.stream.jsonl").write_text(
                '{"type": "message", "content": "old"}\n'
            )
            (existing_run / "status.json").write_text("{}\n")
            (existing_workspace / "trace.md").write_text("old trace")
            (existing_workspace / "answer.txt").write_text("old answer")

            runner = core.BiomniBenchPerturbationRunner(
                core.PerturbationRunConfig(
                    base_run=base,
                    out_dir=out_dir,
                    levels=("L0",),
                    resume=True,
                ),
                perturber=FakePerturber(),
            )

            self.assertEqual(runner.run(), 0)
            self.assertEqual((existing_workspace / "trace.md").read_text(), "new trace")
            manifest = json.loads((out_dir / "perturbation_manifest.json").read_text())
            self.assertEqual(manifest["records"][0]["status"], "written")

    def test_perturber_prompt_is_rubric_blind(self):
        core = self.import_core()

        request = core.PerturbationRequest(
            task="da-1-1",
            level="L0",
            level_intent=core.PERTURBATION_LEVELS["L0"],
            instruction_md="instruction",
            trace_md="trace",
            answer_txt="answer",
            trajectory_stream_jsonl='{"type": "message"}\n',
        )

        prompt = core.GeminiPerturber(model="gemini-3.5-flash").build_prompt(request)

        self.assertIn("instruction", prompt)
        self.assertIn("trace", prompt)
        self.assertIn("answer", prompt)
        self.assertNotIn("rubric.txt", prompt)
        self.assertNotIn("process_rubric.txt", prompt)
        self.assertNotIn("Criterion", prompt)

    def test_gemini_perturber_generates_artifacts_with_plain_text_api_calls(self):
        core = self.import_core()

        request = core.PerturbationRequest(
            task="da-1-1",
            level="L1",
            level_intent=core.PERTURBATION_LEVELS["L1"],
            instruction_md="instruction",
            trace_md="trace",
            answer_txt="answer",
            trajectory_stream_jsonl='{"type": "message"}\n',
        )
        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return None

            def read(self):
                response_index = len(calls)
                texts = {
                    1: "perturbed trace",
                    2: "perturbed answer",
                    3: '{"type": "message", "content": "perturbed"}\n',
                }
                payload = {
                    "candidates": [
                        {"content": {"parts": [{"text": texts[response_index]}]}}
                    ]
                }
                return json.dumps(payload).encode()

        def fake_urlopen(request_obj, timeout):
            calls.append((request_obj, timeout))
            return FakeResponse()

        import unittest.mock

        with unittest.mock.patch.dict(
            "os.environ", {"GEMINI_API_KEY": "secret"}, clear=True
        ):
            with unittest.mock.patch(
                "rubric_gen.biomnibench.gemini_client.urllib.request.urlopen",
                fake_urlopen,
            ):
                result = core.GeminiPerturber(model="gemini-3.5-flash").perturb(request)

        self.assertEqual(len(calls), 3)
        self.assertEqual(result.trace_md, "perturbed trace")
        self.assertEqual(result.answer_txt, "perturbed answer")
        self.assertEqual(
            result.trajectory_stream_jsonl,
            '{"type": "message", "content": "perturbed"}\n',
        )
        for request_obj, timeout in calls:
            self.assertIn(
                "models/gemini-3.5-flash:generateContent", request_obj.full_url
            )
            self.assertIn("key=secret", request_obj.full_url)
            self.assertEqual(timeout, 600)
            body = json.loads(request_obj.data.decode())
            self.assertIn("contents", body)
            self.assertNotIn("responseMimeType", body["generationConfig"])
            self.assertIn("instruction", body["contents"][0]["parts"][0]["text"])

    def test_gemini_perturber_requires_api_key(self):
        core = self.import_core()

        request = core.PerturbationRequest(
            task="da-1-1",
            level="L1",
            level_intent=core.PERTURBATION_LEVELS["L1"],
            instruction_md="instruction",
            trace_md="trace",
            answer_txt="answer",
            trajectory_stream_jsonl='{"type": "message"}\n',
        )

        import unittest.mock

        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                core.GeminiPerturber(model="gemini-3.5-flash").perturb(request)

    def test_cli_accepts_multiple_judge_run_dirs(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "judge",
                "--run-dir",
                "runs/all/tasks/da-1-1",
                "runs/all/tasks/da-2-1",
                "--dry-run",
            ]
        )

        config = core.JudgeRunConfig.from_namespace(args)
        self.assertEqual(config.run_dir, Path("runs/all/tasks/da-1-1").resolve())
        self.assertEqual(
            config.extra_run_dirs, (Path("runs/all/tasks/da-2-1").resolve(),)
        )
        self.assertEqual(config.run_dirs, (config.run_dir, *config.extra_run_dirs))

    def test_cli_accepts_repeated_judge_run_dir_flags(self):
        core = self.import_core()

        parser = core.build_parser()
        args = parser.parse_args(
            [
                "judge",
                "--run-dir",
                "runs/all/tasks/da-1-1",
                "--run-dir",
                "runs/all/tasks/da-2-1",
                "--dry-run",
            ]
        )

        config = core.JudgeRunConfig.from_namespace(args)
        self.assertEqual(
            config.run_dirs,
            (
                Path("runs/all/tasks/da-1-1").resolve(),
                Path("runs/all/tasks/da-2-1").resolve(),
            ),
        )

    def test_task_judge_supports_rubric_defined_level_letters(self):
        judge_path = (
            ROOT / "data" / "biomnibench-da" / "da-10-1" / "tests" / "llm_judge.py"
        )
        if not judge_path.is_file():
            self.skipTest("external BiomniBench judge fixture is not available")
        text = judge_path.read_text()
        self.assertIn("choose ONE of the level letters defined", text)
        self.assertIn("allowed_level_letters", text)

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "biomnibench_llm_judge", judge_path
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        levels = module.parse_rubric_levels(
            "Criterion 1:\nLevels: A=10 B=8 C=4 D=1 E=0\n"
        )
        self.assertEqual(
            levels["criterion_1"], {"A": 10, "B": 8, "C": 4, "D": 1, "E": 0}
        )

    def test_judge_runner_discovers_batch_without_writing_dry_run_inputs(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "instruction.md").write_text("task")
            (task_dir / "environment" / "data").mkdir(parents=True)
            (task_dir / "tests" / "rubric.txt").write_text(
                "Criterion 1:\nLevels: A=100 B=50 C=0\n"
            )
            (task_dir / "tests" / "llm_judge.py").write_text("print('judge')\n")

            batch = root / "runs" / "all-gemini-20260101-000000"
            run_dir = batch / "tasks" / "da-1-1"
            workspace = batch / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (workspace / "trace.md").write_text("clean trace")
            (workspace / "answer.txt").write_text("answer")
            (run_dir / "trajectory.stream.jsonl").write_text('{"type": "message"}\n')
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=batch,
                    tasks_dir=root / "data",
                    review="trace",
                    dry_run=True,
                )
            )

            exit_code = runner.run()
            summary = json.loads(runner.scores_path.read_text())
            judge_input = batch / "judges" / "trace" / "da-1-1" / "judge_input_trace.md"

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["tasks"][0]["status"], "planned")
            self.assertIsNone(summary["average_score"])
            self.assertFalse((batch / "judge-trace-summary.jsonl").exists())
            self.assertFalse((batch / "judge-trace-progress.jsonl").exists())
            self.assertFalse(judge_input.exists())

    def test_judge_runner_discovers_multiple_single_run_dirs(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "runs" / "all-gemini-20260101-000000"
            task_dirs = []
            run_dirs = []
            for name in ("da-1-1", "da-2-1"):
                task_dir = root / "data" / name
                (task_dir / "tests").mkdir(parents=True)
                (task_dir / "instruction.md").write_text("task")
                (task_dir / "environment" / "data").mkdir(parents=True)
                (task_dir / "tests" / "rubric.txt").write_text(
                    "Criterion 1:\nLevels: A=100 B=50 C=0\n"
                )
                (task_dir / "tests" / "llm_judge.py").write_text("print('judge')\n")
                task_dirs.append(task_dir)

                run_dir = batch / "tasks" / name
                workspace = batch / "workspaces" / name
                run_dir.mkdir(parents=True)
                workspace.mkdir(parents=True)
                (workspace / "trace.md").write_text(f"{name} trace")
                (workspace / "answer.txt").write_text(f"{name} answer")
                (run_dir / "trajectory.stream.jsonl").write_text(
                    '{"type": "message"}\n'
                )
                (run_dir / "status.json").write_text(
                    json.dumps(
                        {
                            "task": name,
                            "task_dir": str(task_dir),
                            "workspace_dir": str(workspace),
                        }
                    )
                )
                run_dirs.append(run_dir)

            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=run_dirs[0],
                    extra_run_dirs=(run_dirs[1],),
                    tasks_dir=root / "data",
                    review="trace",
                    dry_run=True,
                )
            )

            exit_code = runner.run()
            summary = json.loads(runner.scores_path.read_text())

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                [task["task"] for task in summary["tasks"]], ["da-1-1", "da-2-1"]
            )
            self.assertEqual(summary["total_attempts"], 2)
            self.assertFalse((run_dirs[0] / "judges" / "trace" / "da-1-1").exists())
            self.assertFalse((run_dirs[1] / "judges" / "trace" / "da-2-1").exists())

    def test_judge_runner_can_select_rubric_file(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            tests_dir = task_dir / "tests"
            tests_dir.mkdir(parents=True)
            (tests_dir / "rubric.txt").write_text("DEFAULT RUBRIC\n")
            process_rubric = "Criterion 1: Process rubric\nLevels: A=100 B=50 C=0\n"
            (tests_dir / "process_rubric.txt").write_text(process_rubric)
            (tests_dir / "llm_judge.py").write_text("print('judge')\n")

            output_dir = root / "judge-output"
            output_dir.mkdir()
            run_dir = root / "run"
            workspace_dir = run_dir / "workspace"
            run_dir.mkdir()
            workspace_dir.mkdir()

            def fake_run(cmd, cwd, env, text, stdout, stderr, check):
                self.assertEqual(
                    Path(cwd, "tests", "rubric.txt").read_text(), process_rubric
                )
                logs = Path(cwd, "logs", "verifier")
                logs.mkdir(parents=True, exist_ok=True)
                (logs / "reward.json").write_text(json.dumps({"score": 100}))
                (logs / "evaluation.json").write_text(
                    json.dumps({"criteria": {"criterion_1": {"level": "A"}}})
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=root / "run",
                    tasks_dir=root / "data",
                    review="trace",
                    rubric_name="process_rubric.txt",
                )
            )
            target = core.JudgeTarget(
                task="da-1-1",
                task_dir=task_dir,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
                trajectory_path=run_dir / "trajectory.stream.jsonl",
                output_root=root,
            )
            from rubric_gen.biomnibench.judges import JudgeAttempt

            import unittest.mock

            with unittest.mock.patch(
                "rubric_gen.biomnibench.judges.subprocess.run", fake_run
            ):
                result = runner.execute_judge(
                    tests_dir / "llm_judge.py",
                    tests_dir / "process_rubric.txt",
                    output_dir,
                    "trace",
                    "answer",
                    attempt=JudgeAttempt(target, 1),
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["score"], 100)

    def test_judge_runner_can_prepare_raw_trajectory_review(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "tests" / "rubric.txt").write_text(
                "Criterion 1:\nLevels: A=100 B=50 C=0\n"
            )
            (task_dir / "tests" / "llm_judge.py").write_text("print('judge')\n")

            run_dir = root / "runs" / "da-1-1-gemini-20260101-000000"
            workspace = root / "runs" / "_workspaces" / "da-1-1-gemini-20260101-000000"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (workspace / "trace.md").write_text("clean trace")
            (workspace / "answer.txt").write_text("answer")
            (run_dir / "trajectory.stream.jsonl").write_text(
                '{"type": "tool_use", "command": "python x.py"}\n'
            )
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=run_dir,
                    tasks_dir=root / "data",
                    review="trajectory",
                    dry_run=True,
                )
            )
            review_text = runner.review_text(runner.discover_targets()[0])

            exit_code = runner.run()
            judge_input = (
                run_dir / "judges" / "trajectory" / "da-1-1" / "judge_input_trace.md"
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("# Raw Agent Trajectory", review_text)
            self.assertIn('"type": "tool_use"', review_text)
            self.assertFalse(judge_input.exists())

    def test_judge_score_summary_reports_average(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=Path(tmp),
                    tasks_dir=Path(tmp) / "data",
                    review="trace",
                )
            )

            summary = runner.score_summary(
                [
                    {"task": "da-1-1", "status": "completed", "score": 100},
                    {"task": "da-1-2", "status": "completed", "score": 50},
                    {"task": "da-1-3", "status": "failed", "score": None},
                ]
            )

            self.assertEqual(summary["total_tasks"], 3)
            self.assertEqual(summary["scored_tasks"], 2)
            self.assertEqual(summary["average_score"], 75.0)
            self.assertEqual(summary["tasks"][1]["score"], 50)

    def test_judge_score_summary_reports_repeat_variance(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=Path(tmp),
                    tasks_dir=Path(tmp) / "data",
                    review="trace",
                    repeats=3,
                )
            )

            summary = runner.score_summary(
                [
                    {
                        "task": "da-1-1",
                        "status": "completed",
                        "score": 100,
                        "repeat_index": 1,
                    },
                    {
                        "task": "da-1-1",
                        "status": "completed",
                        "score": 80,
                        "repeat_index": 2,
                    },
                    {
                        "task": "da-1-1",
                        "status": "completed",
                        "score": 60,
                        "repeat_index": 3,
                    },
                    {
                        "task": "da-1-2",
                        "status": "completed",
                        "score": 50,
                        "repeat_index": 1,
                    },
                    {
                        "task": "da-1-2",
                        "status": "failed",
                        "score": None,
                        "repeat_index": 2,
                    },
                ]
            )

            self.assertEqual(summary["total_tasks"], 2)
            self.assertEqual(summary["total_attempts"], 5)
            self.assertEqual(summary["scored_attempts"], 4)
            self.assertEqual(summary["average_score"], 72.5)
            self.assertEqual(summary["tasks"][0]["scores"], [100, 80, 60])
            self.assertEqual(summary["tasks"][0]["mean_score"], 80.0)
            self.assertEqual(summary["tasks"][0]["min_score"], 60)
            self.assertEqual(summary["tasks"][0]["max_score"], 100)
            self.assertGreater(summary["tasks"][0]["score_stddev"], 0)

    def test_judge_runner_supplies_default_model_name(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=Path(tmp),
                    tasks_dir=Path(tmp) / "data",
                    review="trace",
                )
            )
            explicit = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=Path(tmp),
                    tasks_dir=Path(tmp) / "data",
                    review="trace",
                    model="gemini-test-model",
                )
            )

            self.assertTrue(runner.judge_model({}).startswith("gemini"))
            self.assertEqual(
                runner.judge_model({"MODEL_NAME": "gemini-env-model"}),
                "gemini-env-model",
            )
            self.assertEqual(
                explicit.judge_model({"MODEL_NAME": "gemini-env-model"}),
                "gemini-test-model",
            )

    def test_judge_repeats_use_separate_output_dirs(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "tests" / "rubric.txt").write_text(
                "Criterion 1:\nLevels: A=100 B=50 C=0\n"
            )
            (task_dir / "tests" / "llm_judge.py").write_text("print('judge')\n")

            batch = root / "runs" / "all-gemini-20260101-000000"
            run_dir = batch / "tasks" / "da-1-1"
            workspace = batch / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (workspace / "trace.md").write_text("clean trace")
            (workspace / "answer.txt").write_text("answer")
            (run_dir / "trajectory.stream.jsonl").write_text('{"type": "message"}\n')
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )

            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=batch,
                    tasks_dir=root / "data",
                    review="trace",
                    dry_run=True,
                    max_concurrency=2,
                    repeats=2,
                )
            )

            exit_code = runner.run()
            summary = json.loads(runner.scores_path.read_text())

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["total_attempts"], 2)
            self.assertFalse(
                (batch / "judges" / "trace" / "da-1-1" / "repeat-01").exists()
            )
            self.assertFalse(
                (batch / "judges" / "trace" / "da-1-1" / "repeat-02").exists()
            )

    def test_judge_resume_rejects_unattested_scored_output(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "data" / "da-1-1"
            (task_dir / "tests").mkdir(parents=True)
            (task_dir / "tests" / "rubric.txt").write_text(
                "Criterion 1:\nLevels: A=100 B=50 C=0\n"
            )
            (task_dir / "tests" / "llm_judge.py").write_text("print('judge')\n")

            batch = root / "runs" / "all-gemini-20260101-000000"
            run_dir = batch / "tasks" / "da-1-1"
            workspace = batch / "workspaces" / "da-1-1"
            run_dir.mkdir(parents=True)
            workspace.mkdir(parents=True)
            (workspace / "trace.md").write_text("clean trace")
            (workspace / "answer.txt").write_text("answer")
            (run_dir / "trajectory.stream.jsonl").write_text('{"type": "message"}\n')
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "task": "da-1-1",
                        "task_dir": str(task_dir),
                        "workspace_dir": str(workspace),
                    }
                )
            )
            judge_output = batch / "judges" / "trace" / "da-1-1"
            judge_output.mkdir(parents=True)
            (judge_output / "reward.json").write_text(json.dumps({"score": 88}))
            (judge_output / "evaluation.json").write_text("{}")
            (judge_output / "stdout.txt").write_text("previous judge output")

            runner = core.BiomniBenchJudgeRunner(
                core.JudgeRunConfig(
                    run_dir=batch,
                    tasks_dir=root / "data",
                    review="trace",
                    resume=True,
                )
            )

            target = runner.discover_targets()[0]
            from rubric_gen.biomnibench.judges import JudgeAttempt

            self.assertIsNone(runner.completed_record(JudgeAttempt(target, 1)))

    def test_result_record_includes_run_cost(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.RunPaths.for_task(
                task_dir=root / "da-1-1",
                runs_dir=root / "runs",
                provider="claude",
                stamp="20260101-000000",
            )
            paths.run_dir.mkdir(parents=True)
            paths.stream_path.write_text(
                '{"type": "result", "total_cost_usd": 0.0789}\n'
            )
            runner = core.BiomniBenchBatchRunner(
                config=core.BatchRunConfig(
                    tasks_dir=root / "data",
                    runs_dir=root / "runs",
                    provider="claude",
                )
            )

            record = runner.result_record(root / "da-1-1", 0, paths)
            self.assertEqual(record["cost_usd"], 0.0789)
            self.assertIsNone(record["estimated_cost_usd"])

    def test_result_record_marks_validation_errors_as_failed(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.RunPaths.for_task(
                task_dir=root / "da-1-1",
                runs_dir=root / "runs",
                provider="gemini",
                stamp="20260101-000000",
            )
            paths.run_dir.mkdir(parents=True)
            paths.workspace_dir.mkdir(parents=True)
            paths.stream_path.write_text("{}\n")
            (paths.workspace_dir / "trace.md").write_text("trace")
            validation = core.AgentRunner().validate_outputs(paths)
            runner = core.BiomniBenchBatchRunner(
                config=core.BatchRunConfig(
                    tasks_dir=root / "data",
                    runs_dir=root / "runs",
                    provider="gemini",
                )
            )

            record = runner.result_record(root / "da-1-1", 0, paths, validation)

            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["exit_code"], 1)
            self.assertEqual(record["process_exit_code"], 0)
            self.assertIn("missing_or_empty: answer.txt", record["validation_errors"])

    def test_result_record_uses_process_exit_code_from_status(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.RunPaths.for_task(
                task_dir=root / "da-1-1",
                runs_dir=root / "runs",
                provider="gemini",
                stamp="20260101-000000",
            )
            paths.run_dir.mkdir(parents=True)
            paths.workspace_dir.mkdir(parents=True)
            paths.stream_path.write_text("{}\n")
            paths.status_path.write_text(
                json.dumps(
                    {
                        "provider": "gemini",
                        "process_exit_code": 0,
                        "exit_code": 1,
                        "validation_errors": ["missing_or_empty: answer.txt"],
                        "suspicious_files": [],
                    }
                )
            )
            (paths.workspace_dir / "trace.md").write_text("trace")
            runner = core.BiomniBenchBatchRunner(
                config=core.BatchRunConfig(
                    tasks_dir=root / "data",
                    runs_dir=root / "runs",
                    provider="gemini",
                )
            )

            record = runner.result_record(root / "da-1-1", 1, paths)

            self.assertEqual(record["process_exit_code"], 0)
            self.assertEqual(record["exit_code"], 1)

    def test_result_record_includes_estimated_gemini_cost(self):
        core = self.import_core()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.RunPaths.for_task(
                task_dir=root / "da-1-1",
                runs_dir=root / "runs",
                provider="gemini",
                stamp="20260101-000000",
            )
            paths.run_dir.mkdir(parents=True)
            paths.stream_path.write_text(
                json.dumps(
                    {
                        "type": "result",
                        "stats": {
                            "models": {
                                "gemini-3-flash-preview": {
                                    "input": 1_000_000,
                                    "cached": 0,
                                    "output_tokens": 1_000_000,
                                }
                            }
                        },
                    }
                )
                + "\n"
            )
            runner = core.BiomniBenchBatchRunner(
                config=core.BatchRunConfig(
                    tasks_dir=root / "data",
                    runs_dir=root / "runs",
                    provider="gemini",
                )
            )

            record = runner.result_record(root / "da-1-1", 0, paths)
            self.assertIsNone(record["cost_usd"])
            self.assertEqual(record["estimated_cost_usd"], 3.5)
            self.assertEqual(
                record["cost_source"], "estimated_google_gemini_api_standard"
            )


if __name__ == "__main__":
    unittest.main()
