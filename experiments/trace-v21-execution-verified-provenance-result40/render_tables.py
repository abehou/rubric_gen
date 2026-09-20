"""Render the three requested compact gap/RH Results40 tables."""
from __future__ import annotations

import json
from pathlib import Path

from make_configs import ROOT


REPORT = ROOT / "docs/reports/2026-09-18/trace-v21-execution-verified-provenance-result40"
PANELS = (
    ("sol_opus", "GPT-5.6 Sol + Claude Opus 5"),
    ("sol", "GPT-5.6 Sol"),
    ("opus", "Claude Opus 5"),
    ("gemini", "Gemini 3.8 Flash"),
    ("sol_opus_gemini", "GPT-5.6 Sol + Claude Opus 5 + Gemini 3.8 Flash"),
)
POPULATIONS = (("new20", "Newly added 20"), ("cumulative40", "Cumulative 40"))
GAPS = (
    ("W_minus_S", "W−S"),
    ("S_minus_H", "S−H"),
    ("H_minus_A", "H−A"),
    ("W_minus_A", "W−A"),
)
WINDOWS = (
    ("full_trajectory", "RH full"),
    ("post_update", "RH post"),
    ("final_artifact", "RH artifact"),
    ("final_revision", "RH revision"),
)


def number(value: float) -> str:
    return f"{float(value):.2f}"


def condition_row(
    analysis: dict,
    population: str,
    panel: str,
    arm: str,
    condition: str,
) -> list[str]:
    cohort = f"{'current' if condition == 'Promoted RTT' else 'static'}_{arm}"
    summary = analysis["cohorts"][population][panel][cohort]
    values = [number(summary["metrics"][key]["mean"]) for key, _ in GAPS]
    values.extend(
        number(summary["rh"][window]["confirmed_positive_percent"])
        for window, _ in WINDOWS
    )
    return [population, arm.title(), condition, *values]


def delta_row(analysis: dict, population: str, panel: str, arm: str) -> list[str]:
    comparison = analysis["paired_comparisons"][population][panel][arm]
    values = [number(comparison["metrics"][key]["mean"]) for key, _ in GAPS]
    values.extend(number(comparison["rh"][window]["mean"]) for window, _ in WINDOWS)
    return [population, arm.title(), "RTT − static", *values]


def render() -> str:
    analysis = json.loads((REPORT / "analysis.json").read_text())
    columns = ["Population", "Arm", "Condition", *(label for _, label in GAPS), *(label for _, label in WINDOWS)]
    lines = [
        "# Results40 compact gap and RH tables",
        "",
        "Gap cells are score points. RH cells are confirmed-positive auditor-row percentages; abstentions remain in each denominator. Delta rows are promoted RTT minus matched static, in points and percentage points respectively.",
    ]
    for panel, title in PANELS:
        lines.extend(("", f"## {title}", "", "| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)))
        for population, label in POPULATIONS:
            for arm in ("full", "user"):
                rows = (
                    condition_row(analysis, population, panel, arm, "Static"),
                    condition_row(analysis, population, panel, arm, "Promoted RTT"),
                    delta_row(analysis, population, panel, arm),
                )
                for row in rows:
                    row[0] = label
                    lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "comparison-tables.md").write_text(render())


if __name__ == "__main__":
    main()
