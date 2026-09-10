"""Keep test capacity leases and telemetry isolated from production jobs."""
import pytest
from rubric_gen.runtime import capacity


@pytest.fixture(autouse=True)
def isolated_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(capacity, "policy", lambda: {
        "version": 1, "aggregate_concurrency": 60, "audit_studies": 1,
        "coordination_dir": str(tmp_path / "runtime"),
    })
