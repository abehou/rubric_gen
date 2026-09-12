"""Create the isolated User-only v3.1 stress configs from sealed v3 inputs."""
from __future__ import annotations

from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
TASKS = ("da-15-1", "da-13-6", "da-18-5")


def main() -> None:
    output = BUNDLE / "stress-v31"
    output.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        source = (BUNDLE / "stress" / f"v3-candidate-{task}.yaml").read_text(encoding="utf-8")
        text = source.replace(
            "trace-attack-defense-v3-20260911/stress-iter1/v3-candidate",
            "trace-attack-defense-v3-20260911/stress-iter2/v31-candidate",
        ).replace("red_team_trace_version: attack_defense_v3\n", "red_team_trace_version: attack_defense_v3.1\n")
        (output / f"v31-candidate-{task}.yaml").write_text(text, encoding="utf-8")
    print({"configs": 3, "output": str(output), "version": "attack_defense_v3.1"})


if __name__ == "__main__":
    main()
