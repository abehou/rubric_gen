"""Bind canonical v3 consumers to the current-code v2.1 control studies.

This is provider-free identity plumbing.  The canonical control outputs and
their seed/paraphrase inputs are already sealed; the only repair is replacing
stale producer IDs in the v3 consumer declarations.
"""
from datetime import datetime, timezone
import json
import os
import subprocess
from pathlib import Path

import yaml

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment


BUNDLE = Path(__file__).resolve().parent
TASKS = ("da-3-4", "da-11-1", "da-18-1")


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("compute-only canonical config finalization")
    rows = []
    for task in TASKS:
        producer_path = BUNDLE / "control-v21-compatible" / f"{task}.yaml"
        consumer_path = BUNDLE / "canonical-v3" / f"{task}.yaml"
        producer = load_experiment(producer_path)
        raw = yaml.safe_load(consumer_path.read_text(encoding="utf-8"))
        source = raw.get("pretreatment_source")
        if not isinstance(source, dict):
            raise ValueError(f"missing pretreatment source in {consumer_path}")
        source["experiment_id"] = producer.experiment_id
        source["study_dir"] = str(
            Path(producer.dag["revise"]["output_dir"].format(experiment_id=producer.experiment_id))
        )
        consumer_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        consumer = load_experiment(consumer_path)
        rows.append(
            {
                "task": task,
                "producer_id": producer.experiment_id,
                "consumer_id": consumer.experiment_id,
                "producer_config_sha256": sha256_file(producer_path),
                "consumer_config_sha256": sha256_file(consumer_path),
                "study_dir": source["study_dir"],
            }
        )
    receipt = {
        "kind": "canonical_v3_config_identity_binding",
        "job": os.environ["SLURM_JOB_ID"],
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=BUNDLE.parents[1], text=True
        ).strip(),
        "tasks": rows,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(BUNDLE / "canonical-v3-config-finalization.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
