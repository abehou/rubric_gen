"""Provider-free native validation of scale seed blocks.

The earlier inventory only inspected nested status files and therefore treated an
intentionally excluded adversarial attempt (included=false) as a missing seed.
This diagnostic delegates validity to the same resolve_seed contract used by the
revision pipeline and never contacts a provider or mutates the output roots.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed


def inspect_config(path: Path) -> dict[str, object]:
    experiment = load_experiment(path)
    seed_root = Path(str(experiment.dag["seed"]["output_dir"]))
    agent = experiment.seed_agent_config(quiet=True)
    rows: list[dict[str, object]] = []
    for task_id in experiment.task_ids:
        task_dir = experiment.task_dir(task_id)
        for replicate in range(1, experiment.replicates + 1):
            try:
                seed = resolve_seed(
                    seed_root,
                    task_dir,
                    replicate,
                    seed_generator=agent,
                    prompt_profile=str(experiment.protocol["prompt"]),
                    benchmark=experiment.benchmark,
                )
            except Exception as error:  # diagnostic output, never a retry signal
                rows.append({
                    "task": task_id,
                    "replicate": replicate,
                    "valid": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                })
            else:
                rows.append({
                    "task": task_id,
                    "replicate": replicate,
                    "valid": True,
                    "seed_sha256": seed.manifest.get("seed_sha256"),
                })
    return {
        "config": str(path),
        "experiment_id": experiment.experiment_id,
        "seed_root": str(seed_root),
        "expected": len(rows),
        "valid": sum(bool(row["valid"]) for row in rows),
        "invalid": sum(not bool(row["valid"]) for row in rows),
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: native_seed_integrity_check.py CONFIG ...")
    paths: list[Path] = []
    for arg in argv[1:]:
        path = Path(arg).resolve()
        paths.extend(sorted(path.glob("*.yaml")) if path.is_dir() else [path])
    reports = [inspect_config(path) for path in paths]
    print(json.dumps(reports, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
