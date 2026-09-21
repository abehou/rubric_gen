"""Host-owned S-H gap improvements; mocked scores are wiring fixtures."""

import json
from types import SimpleNamespace

from rubric_gen.submission_revision import evolution_assessment as assessment
from rubric_gen.submission_revision import trace_defense_delivery as delivery
from rubric_gen.submission_revision.rubric_generation import (
    ElicitedCriterion,
    RubricGeneration,
    render_augmented_rubric,
)
from rubric_gen.submission_revision.trace_defense import select_pairs
from rubric_gen.submission_revision.trace_defense_prompts import SOURCE_SCHEDULE
from rubric_gen.submission_revision.trace_defense_registry import prompt_hashes, recipe
from test_rubric_evolution import _rubric


VERSION = (
    "attack_defense_v2.1_execution_verified_proactive_provenance_gap_improvement"
)


def test_gap_recipe_preserves_provenance_prompt_text():
    assert recipe(VERSION).prompts.PROMPT_VERSION == VERSION
    assert prompt_hashes(VERSION) == prompt_hashes(
        "attack_defense_v2.1_execution_verified_proactive_provenance"
    )


def _score(artifact_id, total):
    return SimpleNamespace(artifact_id=artifact_id, total_score=total)


def _pair(pair_id, gap_views, active=(60, 40), development=(60, 40)):
    return SimpleNamespace(
        pair_id=pair_id,
        preferred_artifact_id=f"preferred-{pair_id}",
        rejected_artifact_id=f"rejected-{pair_id}",
        gap_views=gap_views,
        active_rubric_scores=(
            _score(f"preferred-{pair_id}", active[0]),
            _score(f"rejected-{pair_id}", active[1]),
        ),
        development_rubric_scores=(
            _score(f"preferred-{pair_id}", development[0]),
            _score(f"rejected-{pair_id}", development[1]),
        ),
    )


def test_pair_selection_prioritizes_selected_rubric_transfer_gap():
    active_only = _pair(
        "pair-active-only",
        (assessment.AssessmentView.ACTIVE_RUBRIC,),
        active=(40, 60),
        development=(60, 40),
    )
    newest_both = _pair(
        "pair-newest-both",
        (
            assessment.AssessmentView.ACTIVE_RUBRIC,
            assessment.AssessmentView.DEVELOPMENT_RUBRIC,
        ),
        active=(20, 60),
        development=(20, 60),
    )
    history = SimpleNamespace(
        red_team_evidence=(
            SimpleNamespace(pair_id=newest_both.pair_id, source_checkpoint=3),
        ),
        newest_sidecar_pair_id=newest_both.pair_id,
        pair_source_checkpoints=(),
        artifacts=(),
    )

    selected = select_pairs(
        (newest_both, active_only), history, 3, prefer_active_only=True
    )

    assert [item.pair_id for item in selected] == [
        active_only.pair_id,
        newest_both.pair_id,
    ]


def _criterion(title, requirement):
    return ElicitedCriterion.create(
        title=title,
        requirement=requirement,
        levels=(
            ("A", 0, "Check passes."),
            ("B", -5, "Minor failure."),
            ("C", -10, "Major failure."),
        ),
        provenance_pair_ids=("pair_" + "0" * 16,),
        source_generation=1,
    )


def test_delivery_prefers_unseen_violation_over_stronger_repeat(
    tmp_path, monkeypatch
):
    repeated = _criterion("Repeated", "Repair the repeated public defect.")
    unseen = _criterion("Unseen", "Repair the unseen public defect.")
    generation = RubricGeneration(
        2,
        0,
        render_augmented_rubric(_rubric(), (repeated, unseen)),
        (repeated, unseen),
        10,
        SOURCE_SCHEDULE,
        VERSION,
    )
    reminders = tmp_path / "trace-defense-reminders"
    reminders.mkdir()
    (reminders / "s000.json").write_text(
        json.dumps({"selection": {"criterion_id": repeated.criterion_id}})
    )
    score_path = tmp_path / "score.json"
    score_path.write_text("{}")
    monkeypatch.setattr(
        delivery,
        "_validate_score_record",
        lambda *args: (
            None,
            None,
            None,
            {
                "criterion_1": 70,
                "criterion_2": 30,
                "criterion_3": -10,
                "criterion_4": -5,
            },
        ),
    )

    selection, skipped = delivery.select_reminder(
        generation=generation,
        score_validation_path=score_path,
        root=tmp_path,
        submission_id="s001",
        instruction="Repair the analysis.",
        skip_execution_verified=True,
    )

    assert skipped == []
    assert selection["criterion_id"] == unseen.criterion_id
    assert selection["previously_reminded"] is False
    assert selection["pending_undelivered_corrective_count"] == 1


def test_pending_delivery_followup_uses_remaining_queue(tmp_path):
    reminders = tmp_path / "trace-defense-reminders"
    reminders.mkdir()
    path = reminders / "s004.json"
    path.write_text(json.dumps({
        "red_team_trace_version": VERSION,
        "selection": {
            "criterion_id": "criterion_a",
            "pending_undelivered_corrective_count": 2,
        },
        "deferred_ordinary_selection": None,
    }))
    assert delivery.pending_delivery_followup(tmp_path, "s004") is True

    path.write_text(json.dumps({
        "red_team_trace_version": VERSION,
        "selection": {
            "criterion_id": "criterion_a",
            "pending_undelivered_corrective_count": 1,
        },
        "deferred_ordinary_selection": None,
    }))
    assert delivery.pending_delivery_followup(tmp_path, "s004") is False
