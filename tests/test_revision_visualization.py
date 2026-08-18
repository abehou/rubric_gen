from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.controller as controller_module
from rubric_gen.submission_revision.reports import publish_revision_report
import rubric_gen.submission_revision.visualization.revisions as revisions_module


class _FakeAxes:
    def __getattr__(self, name: str):
        del name
        return lambda *args, **kwargs: None


class _FakeFigure:
    def tight_layout(self) -> None:
        pass

    def savefig(self, path: Path, **kwargs: object) -> None:
        del kwargs
        path.write_bytes(b"plot")


class _ConcurrencyCheckingPyplot:
    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def subplots(self, **kwargs: object) -> tuple[_FakeFigure, _FakeAxes]:
        del kwargs
        with self._state_lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        time.sleep(0.02)
        return _FakeFigure(), _FakeAxes()

    def close(self, figure: _FakeFigure) -> None:
        del figure
        with self._state_lock:
            self.active -= 1


def test_revision_score_plots_serialize_pyplot_across_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _ConcurrencyCheckingPyplot()
    monkeypatch.setattr(revisions_module, "pyplot", lambda: fake)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                revisions_module.write_revision_score_plot,
                [50, 60],
                [50, 55],
                tmp_path / f"score-{index}.png",
                task_id=f"da-{index}",
                feedback_policy="semi",
            )
            for index in range(8)
        ]
        for future in futures:
            future.result()

    assert fake.maximum_active == 1
    assert all(
        (tmp_path / f"score-{index}.png").read_bytes() == b"plot"
        for index in range(8)
    )


def test_report_failure_does_not_abort_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = object.__new__(controller_module.SubmissionRevisionController)
    controller.config = SimpleNamespace(
        feedback_policy="semi",
        publish_report=True,
    )
    controller.experiment_dir = tmp_path / "experiment"
    controller.task_dir = tmp_path / "da-1-1"
    events: list[dict[str, object]] = []
    controller._append_event = events.append

    def fail_plot(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("matplotlib race")

    monkeypatch.setattr(controller_module, "write_revision_score_plot", fail_plot)

    controller._publish_progress_report(
        SimpleNamespace(scores=[54], fixed_original_scores=[54]),
        "s000",
    )

    assert events == [
        {
            "event": "report_publication_failed",
            "submission_id": "s000",
            "error_type": "RuntimeError",
            "error": "matplotlib race",
        }
    ]


def test_revision_report_separates_on_policy_and_fixed_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = tmp_path / "study" / "assignment"
    experiment.mkdir(parents=True)
    (experiment / "score_improvement.png").write_bytes(b"plot")
    (experiment / "manifest.json").write_text(json.dumps({
        "task_id": "da-1-1",
        "revision_rounds": 1,
        "feedback_policy": "semi",
        "prompt": "base",
        "rubric_policy": "adaptive_replacement",
        "provider": "codex",
        "model": "solver",
        "judge_model": "judge",
        "review": "trace",
        "rubric_name": "rubric.txt",
        "rubric_set": None,
    }))
    (experiment / "state.json").write_text(json.dumps({
        "phase": "completed",
        "scores": [56, 100],
        "fixed_original_scores": [56, 72],
    }))
    reports = tmp_path / "reports"
    monkeypatch.setenv("BIOMNIBENCH_REPORTS_ROOT", str(reports))

    report_dir = publish_revision_report(experiment)

    summary = json.loads((report_dir / "summary.json").read_text())
    assert "schema_version" not in summary
    assert summary["on_policy_scores"] == [56, 100]
    assert summary["fixed_original_scores"] == [56, 72]
    assert "scores" not in summary
