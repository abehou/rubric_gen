"""Bounded provider-free inspection of the precommitted Results40 inputs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.seeds import resolve_seed

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
MEMBERSHIP = json.loads((BUNDLE / "membership.json").read_text())
TASKS = tuple(MEMBERSHIP["new20"])
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _old_bundle(task: str) -> Path:
    queue = "queue6" if task in TASKS[:10] else "queue7"
    return ROOT / "experiments" / "biomnibench-v21-to45" / queue


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("input inspection must run on a Slurm compute node")
    rows = []
    for task in TASKS:
        bundle = _old_bundle(task)
        experiment = load_experiment(bundle / "configs" / f"{task}.yaml")
        seed_root = Path(experiment.dag["seed"]["output_dir"])
        paraphrase_root = Path(experiment.dag["paraphrase"]["output_dir"])
        seed_rows = []
        for replicate in range(1, 4):
            try:
                seed = resolve_seed(
                    seed_root,
                    experiment.task_dir(task),
                    replicate,
                    seed_generator=experiment.seed_agent_config(),
                    prompt_profile=experiment.protocol["prompt"],
                    benchmark=experiment.benchmark,
                )
                seed_rows.append({
                    "replicate": replicate,
                    "valid": True,
                    "sha256": seed.sha256,
                    "manifest": str(seed_root / "tasks" / task / f"rep-{replicate:03d}" / "manifest.json"),
                })
            except Exception as error:  # inspection records native failure verbatim
                seed_rows.append({
                    "replicate": replicate,
                    "valid": False,
                    "error": f"{type(error).__name__}: {error}",
                })
        paraphrase_error = None
        variants = []
        try:
            validate_paraphrase_run(paraphrase_root, experiment)
            for index in range(5):
                path = paraphrase_root / "tasks" / task / f"variant-{index:03d}.txt"
                variants.append({"variant": index, "path": str(path), "sha256": _sha(path)})
        except Exception as error:
            paraphrase_error = f"{type(error).__name__}: {error}"

        study_parent = Path(experiment.dag["revise"]["output_dir"]).parent
        studies = []
        if study_parent.is_dir():
            for study in sorted(study_parent.iterdir()):
                ledger_path = study / "study.json"
                if not ledger_path.is_file():
                    continue
                ledger = json.loads(ledger_path.read_text())
                pool = study / "pretreatment-rubrics"
                studies.append({
                    "path": str(study),
                    "experiment_id": ledger.get("experiment_id"),
                    "status": ledger.get("status"),
                    "pretreatment_pool": str(pool),
                    "pretreatment_exists": pool.is_dir(),
                    "pretreatment_files": sum(1 for p in pool.rglob("*") if p.is_file()) if pool.is_dir() else 0,
                    "completed_records": sum(1 for r in ledger.get("records", []) if r.get("status") == "completed"),
                    "record_count": len(ledger.get("records", [])),
                })
        rows.append({
            "task_id": task,
            "source_config": str(experiment.path),
            "source_experiment_id_current": experiment.experiment_id,
            "task_dir": str(experiment.task_dir(task)),
            "seed_root": str(seed_root),
            "seeds": seed_rows,
            "paraphrase_root": str(paraphrase_root),
            "paraphrase_valid": paraphrase_error is None,
            "paraphrase_error": paraphrase_error,
            "variants": variants,
            "studies": studies,
        })
    receipt = {
        "job_id": os.environ["SLURM_JOB_ID"],
        "provider_calls": 0,
        "tasks": rows,
        "valid_seed_blocks": sum(s["valid"] for r in rows for s in r["seeds"]),
        "expected_seed_blocks": 60,
        "valid_paraphrase_tasks": sum(r["paraphrase_valid"] for r in rows),
    }
    local = BUNDLE / "receipts" / "input-lineage-inspection.json"
    write_json_atomic(local, receipt)
    RUN.mkdir(parents=True, exist_ok=True)
    write_json_atomic(RUN / "input-lineage-inspection.json", receipt)
    print(json.dumps({
        "valid_seed_blocks": receipt["valid_seed_blocks"],
        "expected_seed_blocks": 60,
        "valid_paraphrase_tasks": receipt["valid_paraphrase_tasks"],
    }), flush=True)


if __name__ == "__main__":
    main()
