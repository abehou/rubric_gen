"""Define and persist the exact OpenAI Batch audit state."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rubric_gen.artifacts.serialization import write_json_atomic


JsonObject = dict[str, object]
BatchPhase = Literal["initial", "synthesis", "complete"]


def _object_map(value: object, name: str) -> dict[str, JsonObject]:
    if not isinstance(value, dict) or any(
        type(key) is not str or not isinstance(item, dict)
        for key, item in value.items()
    ):
        raise ValueError(f"Batch state has invalid {name}")
    return {key: item for key, item in value.items()}


def _nonnegative_float(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ValueError(f"Batch state has invalid {name}")
    return float(value)


@dataclass(frozen=True)
class BatchSubmission:
    status: str
    batch_id: str
    input_file_id: str
    custom_ids: tuple[str, ...]
    local_input: str

    @classmethod
    def from_json(cls, value: object) -> BatchSubmission:
        if not isinstance(value, dict) or set(value) != {
            "status",
            "batch_id",
            "input_file_id",
            "custom_ids",
            "local_input",
        }:
            raise ValueError("Batch state has invalid submission")
        status = value["status"]
        batch_id = value["batch_id"]
        input_file_id = value["input_file_id"]
        custom_ids = value["custom_ids"]
        local_input = value["local_input"]
        if (
            type(status) is not str
            or not status
            or type(batch_id) is not str
            or not batch_id
            or type(input_file_id) is not str
            or not input_file_id
            or type(local_input) is not str
            or not local_input
            or not isinstance(custom_ids, list)
            or any(type(item) is not str or not item for item in custom_ids)
            or len(set(custom_ids)) != len(custom_ids)
        ):
            raise ValueError("Batch state has invalid submission values")
        return cls(
            status=status,
            batch_id=batch_id,
            input_file_id=input_file_id,
            custom_ids=tuple(custom_ids),
            local_input=local_input,
        )

    def to_json(self) -> JsonObject:
        return {
            "status": self.status,
            "batch_id": self.batch_id,
            "input_file_id": self.input_file_id,
            "custom_ids": list(self.custom_ids),
            "local_input": self.local_input,
        }


@dataclass
class BatchState:
    run_provenance_sha256: str
    phase: BatchPhase
    attempt: int
    initial_results: dict[str, JsonObject]
    initial_failures: dict[str, JsonObject]
    synthesis_results: dict[str, JsonObject]
    synthesis_failures: dict[str, JsonObject]
    observed_api_usd: float
    observed_by_model_usd: dict[str, float]
    unverified_failed_request_risk_usd: float
    submission: BatchSubmission | None

    @classmethod
    def new(cls, run_provenance_sha256: str) -> BatchState:
        return cls(
            run_provenance_sha256=run_provenance_sha256,
            phase="initial",
            attempt=1,
            initial_results={},
            initial_failures={},
            synthesis_results={},
            synthesis_failures={},
            observed_api_usd=0.0,
            observed_by_model_usd={},
            unverified_failed_request_risk_usd=0.0,
            submission=None,
        )

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        run_provenance_sha256: str,
        model: str,
    ) -> BatchState:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Batch state: {path}") from exc
        if not isinstance(value, dict) or set(value) != {
            "run_provenance_sha256",
            "phase",
            "attempt",
            "results",
            "failures",
            "cost",
            "submission",
        }:
            raise ValueError("Batch state has an invalid structure")
        if value["run_provenance_sha256"] != run_provenance_sha256:
            raise ValueError("Batch state provenance does not match this run")
        phase = value["phase"]
        attempt = value["attempt"]
        results = value["results"]
        failures = value["failures"]
        cost = value["cost"]
        if phase not in {"initial", "synthesis", "complete"}:
            raise ValueError("Batch state has an invalid phase")
        if type(attempt) is not int or attempt < 1:
            raise ValueError("Batch state has an invalid attempt")
        if not isinstance(results, dict) or set(results) != {"initial", "synthesis"}:
            raise ValueError("Batch state has invalid results")
        if not isinstance(failures, dict) or set(failures) != {"initial", "synthesis"}:
            raise ValueError("Batch state has invalid failures")
        if not isinstance(cost, dict) or set(cost) != {
            "observed_api_usd",
            "observed_by_model_usd",
            "unverified_failed_request_risk_usd",
        }:
            raise ValueError("Batch state has invalid cost data")
        raw_by_model = cost["observed_by_model_usd"]
        if not isinstance(raw_by_model, dict) or set(raw_by_model) - {model}:
            raise ValueError("Batch state has invalid model costs")
        by_model = {
            key: _nonnegative_float(item, "model cost")
            for key, item in raw_by_model.items()
        }
        observed = _nonnegative_float(
            cost["observed_api_usd"], "observed API cost"
        )
        if not math.isclose(sum(by_model.values()), observed, abs_tol=1e-9):
            raise ValueError("Batch state model costs do not sum to observed cost")
        submission_value = value["submission"]
        return cls(
            run_provenance_sha256=run_provenance_sha256,
            phase=phase,
            attempt=attempt,
            initial_results=_object_map(results["initial"], "initial results"),
            initial_failures=_object_map(
                failures["initial"], "initial failures"
            ),
            synthesis_results=_object_map(
                results["synthesis"], "synthesis results"
            ),
            synthesis_failures=_object_map(
                failures["synthesis"], "synthesis failures"
            ),
            observed_api_usd=observed,
            observed_by_model_usd=by_model,
            unverified_failed_request_risk_usd=_nonnegative_float(
                cost["unverified_failed_request_risk_usd"],
                "unverified failed-request risk",
            ),
            submission=(
                None
                if submission_value is None
                else BatchSubmission.from_json(submission_value)
            ),
        )

    @property
    def phase_results(self) -> dict[str, JsonObject]:
        return (
            self.initial_results
            if self.phase == "initial"
            else self.synthesis_results
        )

    @property
    def phase_failures(self) -> dict[str, JsonObject]:
        return (
            self.initial_failures
            if self.phase == "initial"
            else self.synthesis_failures
        )

    def publish(self, path: Path) -> None:
        write_json_atomic(path, {
            "run_provenance_sha256": self.run_provenance_sha256,
            "phase": self.phase,
            "attempt": self.attempt,
            "results": {
                "initial": self.initial_results,
                "synthesis": self.synthesis_results,
            },
            "failures": {
                "initial": self.initial_failures,
                "synthesis": self.synthesis_failures,
            },
            "cost": {
                "observed_api_usd": self.observed_api_usd,
                "observed_by_model_usd": dict(
                    sorted(self.observed_by_model_usd.items())
                ),
                "unverified_failed_request_risk_usd": (
                    self.unverified_failed_request_risk_usd
                ),
            },
            "submission": (
                None if self.submission is None else self.submission.to_json()
            ),
        })
