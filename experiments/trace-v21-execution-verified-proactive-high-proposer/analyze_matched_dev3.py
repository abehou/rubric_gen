"""Compare proactive Luna-high-proposer Dev3 with repaired Luna-low control."""

from __future__ import annotations

import argparse
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.detection.costs import request_cost, usage_tokens


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = (
    ROOT
    / "experiments/trace-v21-execution-verified-high-allocation"
    / "analyze_matched_dev3.py"
)
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def _base():
    spec = importlib.util.spec_from_file_location(
        "execution_verified_matched_analysis", BASE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load matched Dev3 analysis helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _luna_cost(model: str, usage: dict[str, object]) -> float:
    tokens = usage_tokens(
        SimpleNamespace(provider="openai", provider_metadata={"usage": usage})
    )
    if tokens is None:
        raise RuntimeError("saved Luna response has no usable token accounting")
    return request_cost(model, **tokens)


def _study_costs(study: Path) -> dict[str, object]:
    """Count unique saved Luna calls without charging cumulative threads twice."""

    structured: dict[str, dict[str, object]] = {}
    structured_stage: dict[str, str] = {}
    provider_failures_without_usage = 0

    def visit(value: object, *, stage: str | None, path: Path) -> None:
        if isinstance(value, dict):
            current_stage = value.get("stage") if isinstance(value.get("stage"), str) else stage
            response_id = value.get("response_id")
            requested_model = value.get("requested_model")
            provider = value.get("provider")
            if (
                isinstance(response_id, str)
                and requested_model == "gpt-5.6-luna"
                and provider == "openai"
            ):
                usage = value.get("usage")
                if not isinstance(usage, dict):
                    metadata = value.get("provider_metadata")
                    usage = metadata.get("usage") if isinstance(metadata, dict) else None
                if isinstance(usage, dict):
                    previous = structured.setdefault(response_id, value)
                    if previous != value:
                        previous_usage = previous.get("usage")
                        if not isinstance(previous_usage, dict):
                            previous_metadata = previous.get("provider_metadata")
                            previous_usage = (
                                previous_metadata.get("usage")
                                if isinstance(previous_metadata, dict)
                                else None
                            )
                        if previous_usage != usage:
                            raise RuntimeError(f"response usage differs across records: {response_id}")
                    structured_stage.setdefault(
                        response_id,
                        current_stage or ("rubric_judgment" if "shared-judgments" in path.parts else "structured_other"),
                    )
            for child in value.values():
                visit(child, stage=current_stage, path=path)
        elif isinstance(value, list):
            for child in value:
                visit(child, stage=stage, path=path)

    for root in (study / "experiments", study / "shared-judgments"):
        for path in root.rglob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                visit(value, stage=None, path=path)
                if path.name == "result.json" and isinstance(value, dict):
                    accounting = value.get("accounting")
                    if isinstance(accounting, dict):
                        provider_failures_without_usage += int(
                            accounting.get("provider_failures", 0)
                        )
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid saved JSON: {path}") from exc

    threads: dict[str, tuple[dict[str, object], str]] = {}
    for root, stage in (
        (study / "experiments", "terminal"),
    ):
        for path in root.rglob("trajectory.stream.jsonl"):
            if "attempts" in path.parts:
                continue
            path_stage = "solver" if "turns" in path.parts else (
                "attack" if "red-team" in path.parts else stage
            )
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "turn.completed" or event.get("status") != "completed":
                    continue
                thread_id = event.get("thread_id")
                usage = event.get("usage")
                if not isinstance(thread_id, str) or not isinstance(usage, dict):
                    continue
                previous = threads.get(thread_id)
                if previous is None or int(usage.get("total_tokens", 0)) > int(
                    previous[0].get("total_tokens", 0)
                ):
                    threads[thread_id] = (usage, path_stage)

    rows: list[dict[str, object]] = []
    for response_id, generation in structured.items():
        usage = generation.get("usage")
        if not isinstance(usage, dict):
            metadata = generation.get("provider_metadata")
            usage = metadata["usage"]
        request_parameters = generation.get("request_parameters")
        reasoning = None
        if isinstance(request_parameters, dict):
            reasoning_value = request_parameters.get("reasoning")
            if isinstance(reasoning_value, dict):
                reasoning = reasoning_value.get("effort")
            reasoning = reasoning or request_parameters.get("reasoning_effort")
        rows.append({
            "kind": "structured",
            "stage": structured_stage[response_id],
            "reasoning_effort": reasoning,
            "usage_based_usd": _luna_cost("gpt-5.6-luna", usage),
        })
    for usage, stage in threads.values():
        normalized = {
            "input_tokens": usage.get("input_tokens", 0),
            "input_tokens_details": {
                "cached_tokens": usage.get("cached_input_tokens", 0),
                "cache_write_tokens": usage.get("cache_write_input_tokens", 0),
            },
            "output_tokens": usage.get("output_tokens", 0),
        }
        rows.append({
            "kind": "terminal_thread",
            "stage": stage,
            "reasoning_effort": "low",
            "usage_based_usd": _luna_cost("gpt-5.6-luna", normalized),
        })

    grouped: dict[tuple[str, str, str | None], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[row["kind"], row["stage"], row["reasoning_effort"]].append(row)
    breakdown = [
        {
            "kind": kind,
            "stage": stage,
            "reasoning_effort": effort,
            "saved_calls_or_threads": len(values),
            "usage_based_usd": sum(float(value["usage_based_usd"]) for value in values),
        }
        for (kind, stage, effort), values in sorted(
            grouped.items(), key=lambda item: tuple(str(value) for value in item[0])
        )
    ]
    return {
        "saved_structured_responses": len(structured),
        "saved_terminal_threads": len(threads),
        "provider_failures_without_usage": provider_failures_without_usage,
        "usage_based_usd": sum(float(row["usage_based_usd"]) for row in rows),
        "breakdown": breakdown,
        "limitations": [
            "Usage-based estimates are not provider invoices.",
            "Terminal Codex usage is cumulative per thread, so only the largest saved usage record per thread is counted.",
            "Failed calls without returned usage have unknown cost.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-study", type=Path, required=True)
    parser.add_argument("--candidate-audit", type=Path, required=True)
    parser.add_argument("--control-study", type=Path, required=True)
    parser.add_argument("--control-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--kind",
        default="execution-verified-proactive-high-proposer-vs-repaired-low-dev3",
    )
    args = parser.parse_args()
    for path in (
        args.candidate_study,
        args.candidate_audit,
        args.control_study,
        args.control_audit,
        args.output,
    ):
        if not path.is_absolute() or path.is_symlink():
            raise RuntimeError("all paths must be absolute and non-symlinked")

    base = _base()
    candidate_coverage, candidate_rows = base.reconstruct(
        args.candidate_study,
        args.candidate_audit,
        PANEL,
        expected_holdouts=2,
    )

    control_coverage, control_rows = base.reconstruct(
        args.control_study,
        args.control_audit,
        PANEL,
        expected_holdouts=2,
    )

    assert candidate_coverage["assignment_count"] == 18
    assert control_coverage["assignment_count"] == 18
    assert len(candidate_rows) == len(control_rows) == 36

    output = {
        "kind": args.kind,
        "uncertainty_note": (
            "SD and SE use nine panel-averaged artifact values per arm. Wilson "
            "intervals over 18 auditor rows are descriptive only because the two "
            "auditors share each artifact and the nine artifacts occupy only three task clusters."
        ),
        "coverage": {
            "candidate": candidate_coverage,
            "control": control_coverage,
        },
        "conditions": {},
        "paired_candidate_minus_control": {},
        "cost": {
            "candidate_revision": _study_costs(args.candidate_study),
            "candidate_audit": base.semantic_costs(args.candidate_audit),
            "control_audit": base.semantic_costs(args.control_audit),
        },
    }
    for label, rows in (
        ("candidate", candidate_rows),
        ("control", control_rows),
    ):
        output["conditions"][label] = {
            arm_name: {
                "outcomes": base.outcome_summary(
                    [row for row in rows if base.arm(row) == arm_name]
                ),
                "rh": base.rh_summary(
                    [row for row in rows if base.arm(row) == arm_name]
                ),
            }
            for arm_name in ("full", "user")
        }
        output["conditions"][label]["mechanism"] = base.mechanism_summary(rows)

    for arm_name in ("full", "user"):
        candidate_arm = [
            row for row in candidate_rows if base.arm(row) == arm_name
        ]
        control_arm = [row for row in control_rows if base.arm(row) == arm_name]
        candidate_index = base.index_rows(candidate_arm)
        control_index = base.index_rows(control_arm)
        assert candidate_index.keys() == control_index.keys()
        for key in candidate_index:
            assert (
                candidate_index[key]["initial_submission_sha256"]
                == control_index[key]["initial_submission_sha256"]
            )
            assert (
                candidate_index[key]["selected_rubric_sha256"]
                == control_index[key]["selected_rubric_sha256"]
            )
        output["paired_candidate_minus_control"][arm_name] = base.paired_summary(
            candidate_arm, control_arm
        )

    write_json_atomic(args.output, output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "candidate_cost": output["cost"]["candidate_audit"][
                    "usage_based_usd"
                ],
                "control_cost": output["cost"]["control_audit"][
                    "usage_based_usd"
                ],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
