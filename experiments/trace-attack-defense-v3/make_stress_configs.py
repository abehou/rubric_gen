"""Create isolated User v2.1/v3 stress configs from sealed v2.1 inputs."""
from pathlib import Path
import copy
import yaml


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
SOURCE_CONFIG = ROOT / "experiments/trace-attack-defense-v21/result20.yaml"
SOURCE_STUDY = "/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/study/biomnibench-da-factorial-r10-5115fffdd1c0"
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter1")
SEED_ROOT = RUN / "inputs" / "seeds"
TASKS = ("da-15-1", "da-13-6", "da-18-5")


def main() -> None:
    source = yaml.safe_load(SOURCE_CONFIG.read_text(encoding="utf-8"))
    out = BUNDLE / "stress"
    out.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        for flavor, version in (("v21-control", "attack_defense_v2.1"), ("v3-candidate", "attack_defense_v3")):
            value = copy.deepcopy(source)
            value["tasks"] = [task]
            value["execution_conditions"] = ["user-simulator-red-team-trace"]
            value["execution_audit_models"] = ["gpt-5.6-sol", "claude-opus-5"]
            value["protocol"]["red_team_trace_version"] = version
            value["dag"]["seed"]["output_dir"] = str(SEED_ROOT / task)
            value["dag"]["revise"]["output_dir"] = str(RUN / flavor / task / "study/{experiment_id}")
            value["dag"]["detect"]["output_dir"] = str(RUN / flavor / task / "audit/{experiment_id}")
            if flavor == "v21-control":
                # This arm is the dev3 producer of the shared offline g1 pool.
                # Its seed/paraphrase bytes remain the frozen Result20 inputs;
                # only the incompatible historical producer identity is avoided.
                value.pop("pretreatment_source", None)
            else:
                # finalize_stress_configs.py binds this to the completed v2.1
                # producer after loading the current native identity.
                value["pretreatment_source"] = {
                    "experiment": str(out / f"v21-control-{task}.yaml"),
                    "experiment_id": "TO_BE_BOUND",
                    "study_dir": str(RUN / "v21-control" / task / "study" / "{experiment_id}"),
                }
            path = out / f"{flavor}-{task}.yaml"
            path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
            print(path)


if __name__ == "__main__":
    main()
