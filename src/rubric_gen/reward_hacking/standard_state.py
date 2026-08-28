"""Define and persist standard-request cost state."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.reward_hacking.review import CostBudgetExceeded


def _cost(value: object, name: str, *, tolerate_roundoff: bool = False) -> float:
    minimum = -1e-9 if tolerate_roundoff else 0.0
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < minimum
    ):
        raise ValueError(f"cost state has invalid {name}")
    return max(0.0, float(value))


@dataclass
class StandardCostState:
    run_provenance_sha256: str
    observed_api_usd: float
    observed_by_model_usd: dict[str, float]
    unverified_failed_request_risk_usd: float
    reserved_api_usd: float
    budget_usd: float | None

    @classmethod
    def new(
        cls,
        run_provenance_sha256: str,
        budget_usd: float | None,
    ) -> StandardCostState:
        return cls(
            run_provenance_sha256=run_provenance_sha256,
            observed_api_usd=0.0,
            observed_by_model_usd={},
            unverified_failed_request_risk_usd=0.0,
            reserved_api_usd=0.0,
            budget_usd=budget_usd,
        )

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        run_provenance_sha256: str,
        models: tuple[str, ...],
        budget_usd: float | None,
    ) -> StandardCostState:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid cost state: {path}") from exc
        if not isinstance(value, dict) or set(value) != {
            "run_provenance_sha256",
            "observed_api_usd",
            "observed_by_model_usd",
            "unverified_failed_request_risk_usd",
            "reserved_api_usd",
            "budget_usd",
        }:
            raise ValueError("cost state has an invalid structure")
        if (
            value["run_provenance_sha256"] != run_provenance_sha256
            or value["budget_usd"] != budget_usd
        ):
            raise ValueError("cost state does not match this run")
        raw_by_model = value["observed_by_model_usd"]
        if not isinstance(raw_by_model, dict) or set(raw_by_model) - set(models):
            raise ValueError("cost state has invalid observed_by_model_usd")
        by_model = {
            model: _cost(cost, "model cost")
            for model, cost in raw_by_model.items()
        }
        observed = _cost(value["observed_api_usd"], "observed_api_usd")
        if not math.isclose(sum(by_model.values()), observed, abs_tol=1e-9):
            raise ValueError("cost state model costs do not sum to observed cost")
        failed_risk = _cost(
            value["unverified_failed_request_risk_usd"],
            "unverified_failed_request_risk_usd",
            tolerate_roundoff=True,
        )
        reserved = _cost(
            value["reserved_api_usd"],
            "reserved_api_usd",
            tolerate_roundoff=True,
        )
        return cls(
            run_provenance_sha256=run_provenance_sha256,
            observed_api_usd=observed,
            observed_by_model_usd=by_model,
            unverified_failed_request_risk_usd=failed_risk + reserved,
            reserved_api_usd=0.0,
            budget_usd=budget_usd,
        )

    def reserve(self, model: str, reservation: float) -> None:
        projected = (
            self.observed_api_usd
            + self.reserved_api_usd
            + self.unverified_failed_request_risk_usd
            + reservation
        )
        if self.budget_usd is not None and projected > self.budget_usd:
            raise CostBudgetExceeded(
                f"dispatching {model} would exceed the "
                f"${self.budget_usd:.2f} run budget"
            )
        self.reserved_api_usd += reservation

    def record_failure(self, reservation: float) -> None:
        self.reserved_api_usd = max(
            0.0,
            self.reserved_api_usd - reservation,
        )
        self.unverified_failed_request_risk_usd += reservation

    def record_success(
        self,
        model: str,
        reservation: float,
        actual: float | None,
    ) -> None:
        self.reserved_api_usd = max(
            0.0,
            self.reserved_api_usd - reservation,
        )
        self.observed_api_usd += actual or 0.0
        if actual is not None:
            self.observed_by_model_usd[model] = (
                self.observed_by_model_usd.get(model, 0.0) + actual
            )

    def publish(self, path: Path) -> None:
        write_json_atomic(path, {
            "run_provenance_sha256": self.run_provenance_sha256,
            "observed_api_usd": self.observed_api_usd,
            "observed_by_model_usd": dict(
                sorted(self.observed_by_model_usd.items())
            ),
            "unverified_failed_request_risk_usd": (
                self.unverified_failed_request_risk_usd
            ),
            "reserved_api_usd": self.reserved_api_usd,
            "budget_usd": self.budget_usd,
        })
