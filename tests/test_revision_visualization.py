from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.controller_scoring as scoring_module
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


def test_final_plot_failure_does_not_abort_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scorer = object.__new__(scoring_module.RevisionScorer)
    scorer.config = SimpleNamespace(feedback_policy="semi")
    scorer.experiment_dir = tmp_path / "experiment"
    scorer.task_dir = tmp_path / "da-1-1"
    events: list[dict[str, object]] = []
    scorer.store = SimpleNamespace(append_event=events.append)

    def fail_plot(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("matplotlib race")

    monkeypatch.setattr(scoring_module, "write_revision_score_plot", fail_plot)

    scorer.publish_final_plot(
        SimpleNamespace(scores=[54], fixed_original_scores=[54]),
        "s000",
    )

    assert events == [
        {
            "event": "plot_publication_failed",
            "submission_id": "s000",
            "error_type": "RuntimeError",
            "error": "matplotlib race",
        }
    ]
