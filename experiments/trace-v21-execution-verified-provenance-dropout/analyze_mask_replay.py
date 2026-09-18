"""Replay 30%/50% masks over the completed provenance-control generations."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
)
from rubric_gen.submission_revision.rubric_dropout import (
    PROVENANCE_DROPOUT_VERSION,
    revision_dropout,
)
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
)


def _stable_ids(generation) -> dict[str, str]:
    levels = parse_rubric_levels_strict(generation.rubric.content)
    rubric_ids = tuple(
        sorted(levels, key=lambda value: int(value.removeprefix("criterion_")))
    )
    base_count = len(rubric_ids) - len(generation.elicited_criteria)
    stable = {criterion_id: criterion_id for criterion_id in rubric_ids[:base_count]}
    stable.update({
        criterion_id: criterion.criterion_id
        for criterion_id, criterion in zip(
            rubric_ids[base_count:], generation.elicited_criteria, strict=True,
        )
    })
    return stable


def replay(source_study: Path) -> dict[str, object]:
    experiments = source_study / "experiments"
    assignments: list[dict[str, object]] = []
    turns: list[dict[str, object]] = []
    for condition_dir in sorted(experiments.glob("*/*/luna/*")):
        if not condition_dir.is_dir():
            continue
        task, replicate, solver, condition = condition_dir.relative_to(
            experiments
        ).parts
        arm = "full" if condition.startswith("full-") else "user"
        condition_prefix = (
            "full" if arm == "full" else "user-simulator"
        )
        assignment_prefix = (
            f"{task}--{replicate}--solver-{solver}--{condition_prefix}-"
            "red-team-trace-execution-provenance-high-proposer-dropout-"
        )
        seen = {30: set(), 50: set()}
        universe: set[str] = set()
        assignment_turns = 0
        for generation_dir in sorted(
            (condition_dir / "rubric-generations").glob("generation-*")
        ):
            generation_round = int(generation_dir.name.rsplit("-", 1)[1])
            if generation_round < 2:
                continue
            generation = load_rubric_generation(
                condition_dir,
                generation_round,
                expected_policy=RubricPolicy.RED_TEAM_TRACE,
            )
            generation = replace(
                generation,
                red_team_trace_version=PROVENANCE_DROPOUT_VERSION,
            )
            revision_round = generation.source_checkpoint + 1
            stable = _stable_ids(generation)
            universe.update(stable.values())
            masks = {
                percent: revision_dropout(
                    generation,
                    rate=percent / 100,
                    seed=20260806,
                    assignment_id=assignment_prefix + str(percent),
                    revision_round=revision_round,
                )
                for percent in (30, 50)
            }
            mask30, mask50 = masks[30], masks[50]
            if mask30 is None or mask50 is None:
                raise RuntimeError("nonzero mask was not constructed")
            if not set(mask30.dropped_ids) <= set(mask50.dropped_ids):
                raise RuntimeError("30% mask is not nested within 50%")
            row: dict[str, object] = {
                "task": task,
                "replicate": replicate,
                "arm": arm,
                "revision_round": revision_round,
                "eligible_count": len(mask30.eligible_ids),
                "learned_count": len(generation.elicited_criteria),
            }
            for percent, mask in masks.items():
                retained = {stable[item] for item in mask.retained_ids}
                seen[percent].update(retained)
                row[str(percent)] = {
                    "drop_count": len(mask.dropped_ids),
                    "realized_fraction": mask.realized_fraction,
                    "dropped_learned_count": len(mask.dropped_learned_ids),
                    "cumulative_exposed_count": len(seen[percent]),
                    "cumulative_universe_count": len(universe),
                    "cumulative_exposure_fraction": (
                        len(seen[percent] & universe) / len(universe)
                    ),
                }
            turns.append(row)
            assignment_turns += 1
        assignments.append({
            "task": task,
            "replicate": replicate,
            "arm": arm,
            "turn_count": assignment_turns,
            "ever_universe_count": len(universe),
            **{
                f"ever_exposed_{percent}": len(seen[percent] & universe)
                for percent in (30, 50)
            },
            **{
                f"all_exposed_{percent}": universe <= seen[percent]
                for percent in (30, 50)
            },
        })

    result: dict[str, object] = {
        "kind": "provenance-dropout-control-mask-replay-v1",
        "source_study": str(source_study),
        "source_assignment_count": len(assignments),
        "turn_count": len(turns),
        "eligible_count_distribution": dict(sorted(Counter(
            int(row["eligible_count"]) for row in turns
        ).items())),
        "learned_count_distribution": dict(sorted(Counter(
            int(row["learned_count"]) for row in turns
        ).items())),
        "rates": {},
        "assignments": assignments,
        "turns": turns,
        "interpretation_limit": (
            "Masks are replayed on the completed 0% control generations. Real "
            "dropout can change artifacts and later learned-criterion sets."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    rates = result["rates"]
    assert isinstance(rates, dict)
    for percent in (30, 50):
        values = [row[str(percent)] for row in turns]
        rates[str(percent)] = {
            "drop_count_distribution": dict(sorted(Counter(
                int(value["drop_count"]) for value in values
            ).items())),
            "mean_realized_fraction": sum(
                float(value["realized_fraction"]) for value in values
            ) / len(values),
            "turns_dropping_learned": sum(
                int(value["dropped_learned_count"]) > 0 for value in values
            ),
            "learned_drops_total": sum(
                int(value["dropped_learned_count"]) for value in values
            ),
            "assignments_reconstructing_full_cumulative_universe": sum(
                bool(row[f"all_exposed_{percent}"]) for row in assignments
            ),
            "final_cumulative_exposure_fraction_mean": sum(
                int(row[f"ever_exposed_{percent}"])
                / int(row["ever_universe_count"])
                for row in assignments
            ) / len(assignments),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_study.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError("source study must be a non-symlinked directory")
    if output.is_symlink():
        raise RuntimeError("output must not be a symlink")
    value = replay(source)
    if value["source_assignment_count"] != 18 or value["turn_count"] != 123:
        raise RuntimeError("completed provenance-control scope changed")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output, value)
    print(output)


if __name__ == "__main__":
    main()
