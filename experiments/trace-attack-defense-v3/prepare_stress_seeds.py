"""Create current-contract dev3 seed inputs once for the matched stress arms."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json, os, socket, subprocess
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import SeedSetConfig, SeedSetRunner

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter1")
TASKS = ("da-15-1", "da-13-6", "da-18-5")

def one(task):
    exp = load_experiment(BUNDLE / "stress" / f"v21-control-{task}.yaml")
    result = SeedSetRunner(SeedSetConfig(exp, Path(exp.dag["seed"]["output_dir"]), 3)).run()
    if result:
        raise RuntimeError(f"seed generation failed for {task}: {result}")
    return {"task": task, "config": str(exp.path), "config_sha256": sha256_file(exp.path), "seed_root": exp.dag["seed"]["output_dir"], "experiment_id": exp.experiment_id}

def main():
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("stress seed preparation requires 32 CPUs")
    credentials = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    if not credentials.get("OPENAI_API_KEY"): raise RuntimeError("configured OpenAI credential absent")
    os.environ["OPENAI_API_KEY"] = str(credentials["OPENAI_API_KEY"])
    owner = RUN / "owners" / ("seeds-" + os.environ["SLURM_JOB_ID"]); owner.mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool: rows = list(pool.map(one, TASKS))
    receipt = {"kind": "trace_v3_stress_seed_preparation", "method": "dev3-only-current-contract", "job": os.environ["SLURM_JOB_ID"], "host": socket.gethostname(), "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "tasks": rows, "provider_calls_expected": 9, "prepared_at": datetime.now(timezone.utc).isoformat()}
    write_json_atomic(RUN / "seed-completion.json", receipt)
    print(json.dumps(receipt), flush=True)

if __name__ == "__main__": main()
