from __future__ import annotations

from pathlib import Path

import yaml

from rubric_gen.benchmarks.paperbench_code_dev.dataset import (
    PAPERBENCH_DEV_PAPERS,
    PAPERBENCH_RESULTS_PAPERS,
)


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"
FEEDBACK_POLICIES = {
    "full": "full",
    "semi": "semi",
    "score-only": "score_only",
    "user-simulator": "user_simulator",
}
RUBRIC_POLICIES = {
    "static": "fixed",
    "offline-rubric": "offline_elicitation",
    "online-rubric": "online_elicitation",
}
BIO_DEV_TASKS = (
    "da-3-4",
    "da-11-1",
    "da-18-1",
)
BIO_RESULTS_TASKS = (
    "da-10-1",
    "da-10-3",
    "da-12-2",
    "da-12-4",
    "da-13-1",
    "da-13-3",
    "da-13-5",
    "da-13-6",
    "da-14-1",
    "da-14-3",
    "da-14-8",
    "da-15-1",
    "da-15-2",
    "da-15-7",
    "da-15-8",
    "da-16-1",
    "da-18-5",
    "da-18-7",
    "da-19-1",
    "da-19-6",
)


def _yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _expected_conditions() -> list[dict[str, str]]:
    return [
        {
            "condition_id": f"{feedback_slug}-{rubric_slug}",
            "feedback_policy": feedback_policy,
            "rubric_policy": rubric_policy,
        }
        for feedback_slug, feedback_policy in FEEDBACK_POLICIES.items()
        for rubric_slug, rubric_policy in RUBRIC_POLICIES.items()
    ]


def test_biomni_and_paperbench_use_one_exact_factorial_per_tier() -> None:
    tiers = {
        "biomnibench-dev3.yaml": (BIO_DEV_TASKS, 108, 1_105_920, 2_592),
        "biomnibench-results20.yaml": (
            BIO_RESULTS_TASKS, 720, 7_372_800, 17_280,
        ),
        "paperbench-dev3.yaml": (PAPERBENCH_DEV_PAPERS, 108, 92_160, 2_592),
        "paperbench-results20.yaml": (
            PAPERBENCH_RESULTS_PAPERS, 720, 614_400, 17_280,
        ),
    }
    expected_conditions = _expected_conditions()

    for filename, (
        tasks,
        assignment_count,
        mechanistic_calls,
        holistic_calls,
    ) in tiers.items():
        payload = _yaml(EXPERIMENTS / filename)
        assert payload["tasks"] == list(tasks)
        assert payload["conditions"] == expected_conditions
        assert payload["randomization"]["replicates"] == 3
        assert len(tasks) * 3 * len(expected_conditions) == assignment_count
        protocol = payload["protocol"]
        assert protocol["revision_rounds"] == 6
        assert protocol["prompt"] == "base"
        assert set(protocol["feedback_simulator"]) == {
            "model", "max_output_tokens", "max_aspects", "max_retries",
        }
        assert protocol["rubric_proposer_max_retries"] == 5
        assert protocol["solver"]["reasoning_effort"] == "low"
        assert protocol["judge_model"] == "gpt-5.6-luna"
        assert protocol["rubric_proposer_model"] == "gpt-5.6-luna"
        assert protocol["rubric_semantic_judge_model"] == "gpt-5.6-luna"
        assert payload["outcome_audit"]["models"] == [
            "gpt-5.6-sol", "claude-opus-5", "gemini-3.6-flash",
        ]
        assert payload["outcome_audit"]["primary_rule"] == "any_detect"
        assert payload["outcome_audit"]["direct_detector_max_cost_usd"] == 6_000
        assert payload["outcome_audit"]["mechanistic_max_calls"] == mechanistic_calls
        assert payload["outcome_audit"]["holistic_max_calls"] == holistic_calls
        benchmark_slug = "paperbench" if filename.startswith("paperbench") else "biomnibench"
        tier_slug = "luna-dev3" if "dev3" in filename else "luna-results20"
        assert payload["dag"] == {
            "seed": {
                "depends_on": [],
                "output_dir": f"../seeds/{benchmark_slug}/{tier_slug}",
            },
            "paraphrase": {
                "depends_on": [],
                "output_dir": (
                    f"../runs/rubric-paraphrases/{benchmark_slug}/{tier_slug}"
                ),
            },
            "revise": {
                "depends_on": ["seed", "paraphrase"],
                "output_dir": "../runs/studies/{experiment_id}",
            },
            "detect": {
                "depends_on": ["revise", "paraphrase"],
                "output_dir": "../runs/detections/{experiment_id}",
            },
        }

    assert not set(BIO_DEV_TASKS) & set(BIO_RESULTS_TASKS)
    assert not set(PAPERBENCH_DEV_PAPERS) & set(PAPERBENCH_RESULTS_PAPERS)


def test_only_current_tier_configs_exist() -> None:
    assert {
        path.name for path in EXPERIMENTS.glob("*.yaml")
    } == {
        "biomnibench-dev3.yaml",
        "biomnibench-results20.yaml",
        "paperbench-dev3.yaml",
        "paperbench-results20.yaml",
        "harvey-harness-evolution-dev3.yaml",
        "harvey-harness-evolution-results20.yaml",
    }


def test_harvey_has_distinct_three_and_twenty_task_tiers() -> None:
    development = _yaml(EXPERIMENTS / "harvey-harness-evolution-dev3.yaml")
    results = _yaml(EXPERIMENTS / "harvey-harness-evolution-results20.yaml")
    development_tasks = development["benchmark"]["development_tasks"]
    results_tasks = results["benchmark"]["development_tasks"]
    held_out_tasks = results["benchmark"]["held_out_tasks"]

    assert len(development_tasks) == 3
    assert len(results_tasks) == 20
    assert len({task.split("/", 1)[0] for task in results_tasks}) == 20
    assert not set(development_tasks) & set(results_tasks)
    assert not set(results_tasks) & set(held_out_tasks)
    assert development["audit"]["primary_rule"] == "any_detect"
    assert results["audit"]["primary_rule"] == "any_detect"
