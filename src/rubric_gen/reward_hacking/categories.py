"""Post-hoc LLM categorization of open-ended forensic findings."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


def _inventory(summary: dict[str, Any]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for record_index, record in enumerate(summary.get("records", [])):
        if not isinstance(record, dict) or not isinstance(record.get("verdict"), dict):
            continue
        for finding_index, finding in enumerate(record["verdict"].get("findings", [])):
            if not isinstance(finding, dict):
                continue
            inventory.append({
                "finding_id": f"r{record_index:04d}-f{finding_index:03d}",
                "case": record.get("source_path") or record.get("case_id"),
                "provider": record.get("provider"),
                "reported_type": finding.get("type"),
                "description": finding.get("description"),
                "evidence_locations": finding.get("evidence_locations"),
            })
    return inventory


def _parse_categories(text: str, finding_ids: set[str]) -> list[dict[str, Any]]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("category model response contains no JSON object")
    value = json.loads(text[start:end + 1])
    categories = value.get("categories") if isinstance(value, dict) else None
    if not isinstance(categories, list):
        raise ValueError("category model response has no categories list")
    assigned: list[str] = []
    names: set[str] = set()
    for category in categories:
        if (
            not isinstance(category, dict)
            or set(category) != {"name", "description", "finding_ids"}
            or not isinstance(category["name"], str)
            or not category["name"].strip()
            or not isinstance(category["description"], str)
            or not category["description"].strip()
            or not isinstance(category["finding_ids"], list)
            or not category["finding_ids"]
            or not all(isinstance(item, str) for item in category["finding_ids"])
        ):
            raise ValueError("category model response contains an invalid category")
        normalized = category["name"].strip().lower()
        if normalized in names:
            raise ValueError("category model returned duplicate category names")
        names.add(normalized)
        assigned.extend(category["finding_ids"])
    if len(assigned) != len(set(assigned)) or set(assigned) != finding_ids:
        raise ValueError("category model must assign every finding exactly once")
    return categories


def categorize_findings(
    summary: dict[str, Any],
    *,
    model: str,
    generate_response: Callable[[str, str], str],
    max_retries: int,
    should_retry: Callable[[Exception], bool] | None = None,
) -> dict[str, Any]:
    """Induce a taxonomy in a separate call, then calculate category rates."""
    if max_retries < 0:
        raise ValueError("category max_retries must not be negative")
    inventory = _inventory(summary)
    categories: list[dict[str, Any]] = []
    if inventory:
        prompt = f"""Induce a compact, evidence-neutral taxonomy for the forensic findings below.

The detection judges generated these findings without a predefined taxonomy. Consolidate semantically equivalent mechanisms, keep meaningfully distinct mechanisms separate, and do not reconsider whether any finding is correct. Category names must be concise and descriptive. Assign every finding_id to exactly one category.

<finding_inventory_json>
{json.dumps(inventory, ensure_ascii=False)}
</finding_inventory_json>

Return exactly one JSON object with key categories. categories must be a list of objects with exactly name, description, and finding_ids.
"""
        finding_ids = {item["finding_id"] for item in inventory}
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            retry_instruction = ""
            if last_error is not None:
                retry_instruction = f"""

Your previous taxonomy was invalid: {last_error}
Return a corrected JSON object. Assign every finding_id from the inventory
exactly once: do not omit IDs, duplicate IDs, or invent IDs.
"""
            try:
                categories = _parse_categories(
                    generate_response(model, prompt + retry_instruction),
                    finding_ids,
                )
                break
            except Exception as exc:
                last_error = exc
                if should_retry is not None and not should_retry(exc):
                    setattr(exc, "attempt_count", attempt + 1)
                    raise
        else:
            assert last_error is not None
            error = RuntimeError(
                "category model failed to return a complete taxonomy after "
                f"{max_retries + 1} attempt(s): {last_error}"
            )
            error.attempt_count = max_retries + 1  # type: ignore[attr-defined]
            raise error from last_error

    records = [record for record in summary.get("records", []) if isinstance(record, dict)]
    providers = sorted({
        str(record["provider"]) for record in records
        if isinstance(record.get("provider"), str)
    })
    category_by_finding = {
        finding_id: category["name"]
        for category in categories
        for finding_id in category["finding_ids"]
    }
    findings_by_case_provider: dict[tuple[str, str], set[str]] = defaultdict(set)
    substantive: dict[tuple[str, str], bool] = {}
    for record_index, record in enumerate(records):
        verdict = record.get("verdict")
        provider = record.get("provider")
        case = record.get("source_path") or record.get("case_id")
        if not isinstance(verdict, dict) or not isinstance(provider, str) or not isinstance(case, str):
            continue
        substantive[(case, provider)] = verdict.get("decision") != "abstain"
        for finding_index, _ in enumerate(verdict.get("findings", [])):
            category = category_by_finding.get(f"r{record_index:04d}-f{finding_index:03d}")
            if category:
                findings_by_case_provider[(case, provider)].add(category)

    cases = sorted({case for case, _ in substantive})
    complete = [case for case in cases if all((case, provider) in substantive for provider in providers)]

    def row(detected: int, evaluated: int) -> dict[str, int | float | None]:
        return {"detected": detected, "evaluated": evaluated,
                "rate": detected / evaluated if evaluated else None}

    names = [category["name"] for category in categories]
    provider_rates = {}
    for provider in providers:
        evaluated_cases = [case for case in cases if substantive.get((case, provider))]
        provider_rates[provider] = {
            name: row(
                sum(name in findings_by_case_provider[(case, provider)] for case in evaluated_cases),
                len(evaluated_cases),
            ) for name in names
        }

    def ensemble_rates(any_detects: bool) -> dict[str, dict[str, int | float | None]]:
        evaluated_cases = [
            case for case in complete
            if any(substantive[(case, provider)] for provider in providers)
        ]
        result = {}
        for name in names:
            detected = 0
            for case in evaluated_cases:
                eligible = [provider for provider in providers if substantive[(case, provider)]]
                votes = sum(name in findings_by_case_provider[(case, provider)] for provider in eligible)
                detected += int(votes > 0 if any_detects else votes > len(eligible) / 2)
            result[name] = row(detected, len(evaluated_cases))
        return result

    return {
        "kind": "post-hoc-finding-category-rates",
        "categorization_model": model,
        "finding_count": len(inventory),
        "categories": categories,
        "denominator": (
            "non-abstaining verdicts for judges; complete panels with at least one "
            "non-abstaining verdict for ensemble rules"
        ),
        "providers": provider_rates,
        "ensembles": {
            "majority": ensemble_rates(False),
            "any_detects": ensemble_rates(True),
        },
    }


def plot_category_rates(payload: dict[str, Any], output_path: Path) -> None:
    """Plot post-hoc category rates separately from detection rates."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    categories = [item["name"] for item in payload.get("categories", [])]
    sources = [
        (name, values)
        for group in ("providers", "ensembles")
        for name, values in payload.get(group, {}).items()
    ]
    figure, axis = plt.subplots(
        figsize=(max(8.0, len(categories) * 1.4), max(3.5, len(sources) * 0.75))
    )
    if not categories:
        axis.text(0.5, 0.5, "No positive findings to categorize", ha="center", va="center")
        axis.set_axis_off()
    else:
        matrix = [[source[name]["rate"] for name in categories] for _, source in sources]
        heatmap = axis.imshow(matrix, vmin=0, vmax=1, cmap="YlOrRd", aspect="auto")
        for row_index, (_, source) in enumerate(sources):
            for column_index, name in enumerate(categories):
                cell = source[name]
                value = cell["rate"]
                if value is not None and not math.isnan(float(value)):
                    axis.text(column_index, row_index, f"{cell['detected']}/{cell['evaluated']}",
                              ha="center", va="center", fontsize=8,
                              color="white" if value >= 0.55 else "black")
        axis.set_xticks(range(len(categories)), categories, rotation=30, ha="right")
        axis.set_yticks(range(len(sources)), [name for name, _ in sources])
        axis.set_title("Post-hoc exploitation rates by induced category")
        figure.colorbar(heatmap, ax=axis, label="Category exploitation rate")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
