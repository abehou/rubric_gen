"""Bind v3 stress consumers to the current-code v2.1 producer identities."""
from datetime import datetime, timezone
import json, os, subprocess
from pathlib import Path
import yaml
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment

BUNDLE = Path(__file__).resolve().parent
OUT = BUNDLE / "stress"
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter1")
TASKS = ("da-15-1", "da-13-6", "da-18-5")

def main():
    if not os.environ.get("SLURM_JOB_ID"): raise RuntimeError("compute-only config finalization")
    rows = []
    for task in TASKS:
        producer_path = OUT / f"v21-control-{task}.yaml"
        producer = load_experiment(producer_path)
        raw = yaml.safe_load((OUT / f"v3-candidate-{task}.yaml").read_text(encoding="utf-8"))
        raw["pretreatment_source"]["experiment_id"] = producer.experiment_id
        raw["pretreatment_source"]["study_dir"] = str(RUN / "v21-control" / task / "study" / producer.experiment_id)
        consumer_path = OUT / f"v3-candidate-{task}.yaml"
        consumer_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        # Loading again verifies the producer/consumer identity and all static
        # config invariants without touching any experiment output.
        consumer = load_experiment(consumer_path)
        rows.append({"task": task, "producer_id": producer.experiment_id, "consumer_id": consumer.experiment_id, "producer_config_sha256": sha256_file(producer_path), "consumer_config_sha256": sha256_file(consumer_path)})
    receipt = {"kind": "stress_config_identity_binding", "job": os.environ["SLURM_JOB_ID"], "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BUNDLE.parents[1], text=True).strip(), "tasks": rows, "time": datetime.now(timezone.utc).isoformat()}
    write_json_atomic(BUNDLE / "stress-config-finalization.json", receipt)
    print(json.dumps(receipt), flush=True)

if __name__ == "__main__": main()
