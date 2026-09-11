"""Create User-only v3 configs that reuse the completed v2.1 dev3 g1 pool."""
from pathlib import Path
import copy
import yaml


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
SOURCE_DIR = BUNDLE / "control-v21-compatible"
OUT = BUNDLE / "canonical-v3"
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/canonical-v3")
TASKS = ("da-3-4", "da-11-1", "da-18-1")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        source_path = SOURCE_DIR / f"{task}.yaml"
        value = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        value = copy.deepcopy(value)
        value["protocol"]["red_team_trace_version"] = "attack_defense_v3"
        value["execution_conditions"] = ["user-simulator-red-team-trace"]
        value["execution_audit_models"] = ["gpt-5.6-sol", "claude-opus-5"]
        value["dag"]["revise"]["output_dir"] = str(RUN / task / "study/{experiment_id}")
        value["dag"]["detect"]["output_dir"] = str(RUN / task / "audit/{experiment_id}")
        value["pretreatment_source"] = {
            "experiment": str(source_path),
            "experiment_id": "biomnibench-da-factorial-r10-" + {
                "da-3-4": "b8942d1fe720",
                "da-11-1": "8d0cbf6173e2",
                "da-18-1": "b47ff80a8453",
            }[task],
            "study_dir": str(RUN.parent / "control-v21-compatible" / task / "study" / ("biomnibench-da-factorial-r10-" + {
                "da-3-4": "b8942d1fe720",
                "da-11-1": "8d0cbf6173e2",
                "da-18-1": "b47ff80a8453",
            }[task])),
        }
        (OUT / f"{task}.yaml").write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        print(OUT / f"{task}.yaml")


if __name__ == "__main__":
    main()
