from __future__ import annotations

import json
from pathlib import Path

from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.revision.rubric_free import (
    DIMENSIONS,
    RubricFreeConfig,
    RubricFreeRunner,
)


def _experiment(tmp_path: Path) -> Path:
    task = tmp_path / "tasks" / "da-1-1"
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("Produce a sound scientific answer.")
    experiment = tmp_path / "revision"
    for submission, answer in (("s000", "INITIAL"), ("s002", "FINAL")):
        workspace = experiment / "submissions" / submission / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "answer.txt").write_text(answer)
    (experiment / "manifest.json").write_text(json.dumps({
        "task_id": "da-1-1", "task_dir": str(task),
    }))
    return experiment


def test_rubric_free_runner_position_flips_and_aggregates(tmp_path: Path) -> None:
    experiment = _experiment(tmp_path)
    calls = []

    def generate(model: str, prompt: str, base_url: str | None) -> str:
        calls.append((model, prompt))
        assert base_url is None
        final_is_a = prompt.index("FINAL") < prompt.index("INITIAL")

        def response(score: int) -> dict[str, object]:
            return {
                dimension: {"score": score, "justification": "Evidence-based."}
                for dimension in DIMENSIONS
            }

        return json.dumps({
            "response_A": response(7 if final_is_a else 3),
            "response_B": response(3 if final_is_a else 7),
            "comparative_explanation": "The final response is stronger.",
        })

    output = tmp_path / "out"
    runner = RubricFreeRunner(
        RubricFreeConfig(
            experiment_dirs=(experiment,), output_dir=output,
            models=("one", "two", "three"), max_concurrency=2,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    assert len(calls) == 6
    summary = json.loads((output / "summary.json").read_text())
    result = summary["experiments"][str(experiment)]
    assert result["majority_winner"] == "final"
    assert result["consensus_winner"] == "final"
    assert result["judges"]["one"]["overall_delta"] == 4
    assert summary["protocol"]["position_flipped"] is True

    resumed_calls = []
    resumed = RubricFreeRunner(
        RubricFreeConfig(
            experiment_dirs=(experiment,), output_dir=output,
            models=("one", "two", "three"), max_concurrency=2, resume=True,
        ),
        generate_response=(
            lambda model, prompt, base_url:
            resumed_calls.append((model, prompt, base_url))
        ),
    )
    assert resumed.run() == 0
    assert resumed_calls == []


def test_rubric_free_cli_accepts_an_explicit_model_panel() -> None:
    args = build_parser().parse_args([
        "judge", "--run-dir", "revision", "--output-dir", "out",
        "--models", "a", "b", "c"
    ])
    assert args.models == ["a", "b", "c"]


def test_rubric_free_routes_two_vllm_judges(tmp_path: Path) -> None:
    experiment = _experiment(tmp_path)
    urls = {
        "Qwen/Qwen3.6-27B": "http://qwen27:43117/v1",
        "Qwen/Qwen3.6-35B-A3B": "http://qwen35:43583/v1",
    }
    observed: list[tuple[str, str | None]] = []

    def generate(model: str, prompt: str, base_url: str | None) -> str:
        observed.append((model, base_url))
        score = {
            dimension: {"score": 4, "justification": "Equivalent."}
            for dimension in DIMENSIONS
        }
        return json.dumps({
            "response_A": score,
            "response_B": score,
            "comparative_explanation": "Equivalent responses.",
        })

    runner = RubricFreeRunner(
        RubricFreeConfig(
            experiment_dirs=(experiment,),
            output_dir=tmp_path / "out-vllm",
            models=tuple(urls),
            base_urls=urls,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    assert sorted(observed) == sorted([
        (model, url) for model, url in urls.items() for _ in range(2)
    ])
