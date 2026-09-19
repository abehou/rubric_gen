"""Operational audit scopes for the Results40 three-auditor extension.

The saved revision experiments keep their original semantic identities.  Only
the execution-time auditor subset and the destination audit directory change.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from rubric_gen.submission_revision.experiment import Experiment, load_experiment

from make_configs import ROOT, RUN, SHARDS, config_path


SOL_OPUS_PANEL = ("gpt-5.6-sol", "claude-opus-5")
GEMINI_PANEL = ("gemini-3.8-flash",)
THREE_MODEL_PANEL = (*SOL_OPUS_PANEL, *GEMINI_PANEL)

# Historical static configs are loaded from the exact paths recorded by their
# completed study ledgers.  Current code derives a different ID for those old
# YAMLs, so their completed ledgers remain the authoritative native identity.
AUTHORITATIVE_CHECKOUT = Path("/home/aydanh/repos/rubric_gen")
OLD20_SOURCES = {
    "static-full": AUTHORITATIVE_CHECKOUT / "runs/babel-code/result20-current/experiments/babel/biomnibench-result20-current-full-static.yaml",
    "static-user": AUTHORITATIVE_CHECKOUT / "investigation/result20-cue-contrast-20260908/static-results20.yaml",
    "current": ROOT / "experiments/trace-v21-execution-verified-provenance-result20/result20.yaml",
}
EXPECTED_OLD20_IDS = {
    "static-full": "biomnibench-da-factorial-r10-bfbdd0f9833c",
    "static-user": "biomnibench-da-factorial-r10-f0203f5d69f3",
    "current": "biomnibench-da-factorial-r10-682343156c5d",
}
OLD20_STUDIES = {
    "static-full": AUTHORITATIVE_CHECKOUT / "runs/babel-result20-current-20260908/full-static/study/biomnibench-da-factorial-r10-bfbdd0f9833c",
    "static-user": AUTHORITATIVE_CHECKOUT / "runs/babel-result20-cue-contrast-20260908/static/study/biomnibench-da-factorial-r10-f0203f5d69f3",
}


def scoped_experiment(
    source: Path,
    *,
    models: tuple[str, ...],
    output_dir: Path,
) -> Experiment:
    """Return an in-memory execution scope without changing semantic identity."""

    original = load_experiment(source)
    payload = deepcopy(original.payload)
    payload["execution_audit_models"] = list(models)
    payload["dag"]["detect"]["output_dir"] = str(output_dir)
    scoped = replace(original, payload=payload)
    if scoped.experiment_id != original.experiment_id:
        raise RuntimeError("audit execution scope changed the experiment identity")
    if scoped.dag["revise"]["output_dir"] != original.dag["revise"]["output_dir"]:
        raise RuntimeError("audit execution scope changed the revision source")
    if tuple(scoped.outcome_audit["models"]) != models:
        raise RuntimeError("audit execution scope did not select the requested models")
    return scoped


def completed_historical_experiment(name: str) -> Experiment:
    """Load one completed old static study from its authoritative receipt."""

    source = OLD20_SOURCES[name]
    study = OLD20_STUDIES[name]
    loaded = load_experiment(source)
    ledger = json.loads((study / "study.json").read_text())
    expected_id = EXPECTED_OLD20_IDS[name]
    if ledger.get("experiment_path") != str(source):
        raise RuntimeError(f"old20 {name} source path differs from completed study")
    if ledger.get("experiment_id") != expected_id:
        raise RuntimeError(f"old20 {name} completed experiment identity changed")
    expected_assignments = [row.assignment_id for row in loaded.execution_assignments]
    if [row.get("assignment_id") for row in ledger.get("records", ())] != expected_assignments:
        raise RuntimeError(f"old20 {name} assignment ledger changed")
    payload = deepcopy(loaded.payload)
    payload["experiment_id"] = expected_id
    payload["dag"]["revise"]["output_dir"] = str(study)
    payload["dag"]["seed"]["output_dir"] = str(ledger["seed_run_dir"])
    payload["dag"]["paraphrase"]["output_dir"] = str(ledger["paraphrase_run_dir"])
    return replace(loaded, payload=payload)


def new20_sol_opus_scopes() -> tuple[tuple[str, Experiment], ...]:
    return tuple(
        (
            f"new20-{task}-{kind}-sol-opus",
            scoped_experiment(
                config_path(task, kind),
                models=SOL_OPUS_PANEL,
                output_dir=RUN / "audit" / task / kind /
                load_experiment(config_path(task, kind)).experiment_id,
            ),
        )
        for task, kind in SHARDS
    )


def new20_gemini_scopes() -> tuple[tuple[str, Experiment], ...]:
    return tuple(
        (
            f"new20-{task}-{kind}-gemini",
            scoped_experiment(
                config_path(task, kind),
                models=GEMINI_PANEL,
                output_dir=RUN / "audit-gemini" / "new20" / task / kind /
                load_experiment(config_path(task, kind)).experiment_id,
            ),
        )
        for task, kind in SHARDS
    )


def old20_gemini_scopes() -> tuple[tuple[str, Experiment], ...]:
    rows = []
    for name, source in OLD20_SOURCES.items():
        original = (
            completed_historical_experiment(name)
            if name in OLD20_STUDIES
            else load_experiment(source)
        )
        if original.experiment_id != EXPECTED_OLD20_IDS[name]:
            raise RuntimeError(f"old20 {name} experiment identity changed")
        rows.append((
            f"old20-{name}-gemini",
            replace(
                original,
                payload={
                    **deepcopy(original.payload),
                    "execution_audit_models": list(GEMINI_PANEL),
                    "dag": {
                        **deepcopy(original.payload["dag"]),
                        "detect": {
                            **deepcopy(original.payload["dag"]["detect"]),
                            "output_dir": str(
                                RUN / "audit-gemini" / "old20" / name /
                                original.experiment_id
                            ),
                        },
                    },
                },
            ),
        ))
    return tuple(rows)


def all_gemini_scopes() -> tuple[tuple[str, Experiment], ...]:
    return (*new20_gemini_scopes(), *old20_gemini_scopes())
