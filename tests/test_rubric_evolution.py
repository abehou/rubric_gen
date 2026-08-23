from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import rubric_gen.submission_revision.evolution as evolution_module
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.autorubric import parse_autorubric_rubric
from rubric_gen.submission_revision.evolution import (
    ArtifactHistory,
    ArtifactPair,
    BankProposerOutput,
    BlindedArtifact,
    RubricBankProposer,
    SemanticReviewerOutput,
)
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    RubricBank,
    RubricBankItem,
    RubricBankPolicy,
    RubricLineage,
    identity_criterion_map,
)


def _rubric() -> CompleteRubric:
    return CompleteRubric.from_content(
        "RUBRIC: Analysis\n\n"
        "Criterion 1: Correct answer\n"
        "Description: Produce a correct answer.\n"
        "Levels: A=60 B=30 C=0\n"
        "[A]: Complete and correct.\n"
        "[B]: Partly correct.\n"
        "[C]: Missing or incorrect.\n\n"
        "Criterion 2: Evidence\n"
        "Description: Save reproducible evidence.\n"
        "Levels: A=40 B=20 C=0\n"
        "[A]: Complete and reproducible.\n"
        "[B]: Partly reproducible.\n"
        "[C]: Missing or unusable.\n"
    )


def _initial_bank() -> RubricBank:
    rubric = _rubric()
    return RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=rubric,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            rubric=rubric,
            weight=1.0,
            lineage=RubricLineage.NEW,
            criterion_map=identity_criterion_map(rubric),
        ),),
    )


def _history() -> ArtifactHistory:
    contents = ("artifact one", "artifact two", "artifact three", "artifact four")
    artifacts = tuple(
        BlindedArtifact(
            artifact_id=f"artifact_{index:016x}",
            source_id=f"hidden:source:{index}",
            content_sha256=sha256_text(content),
            content=content,
        )
        for index, content in enumerate(contents, start=1)
    )
    pairs = tuple(
        ArtifactPair.create(artifacts[left].artifact_id, artifacts[right].artifact_id)
        for left in range(len(artifacts))
        for right in range(left + 1, len(artifacts))
    )
    return ArtifactHistory(artifacts=artifacts, pairs=pairs)


def _support_pair_ids() -> list[str]:
    history = _history()
    return [history.pairs[0].pair_id, history.pairs[-1].pair_id]


def _cost() -> dict[str, float | str | None]:
    return {
        "cost_usd": None,
        "estimated_cost_usd": 0.01,
        "cost_source": "test",
    }


def _generation(model: str, response_id: str) -> dict[str, object]:
    return {
        "provider": "openai",
        "requested_model": model,
        "effective_model": model,
        "response_id": response_id,
        "request_parameters": {"max_output_tokens": 1},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _proposer_output(value: object, response_id: str) -> BankProposerOutput:
    return BankProposerOutput(
        proposal_text=json.dumps(value),
        cost=_cost(),
        generation=_generation("proposer", response_id),
    )


def _difference_value() -> dict[str, object]:
    return {
        "pairs": [
            {
                "pair_id": pair.pair_id,
                "differences": [{
                    "summary": "The artifacts handle robustness differently.",
                    "task_relevance": "Robustness affects the required result.",
                }],
            }
            for pair in _history().pairs
        ]
    }


def _criterion_value(
    *,
    title: str = "Robustness",
    support: list[str] | None = None,
) -> dict[str, object]:
    return {
        "criteria": [{
            "title": title,
            "requirement": "Test the result under a task-relevant perturbation.",
            "level_descriptions": [
                {"label": "A", "description": "Complete and correct."},
                {"label": "B", "description": "Partly correct."},
                {"label": "C", "description": "Missing or incorrect."},
            ],
            "support_pair_ids": support or _support_pair_ids(),
        }]
    }


def _semantic_output(
    schema: dict[str, object],
    *,
    evidence: str,
    drop_indices: tuple[int, ...] = (),
) -> SemanticReviewerOutput:
    del schema
    proposed = json.loads(evidence)["proposed_criteria"]
    response = {
        "actions": [
            {
                "action": "drop" if index in drop_indices else "accept",
                "source_criterion_ids": [criterion["criterion_id"]],
                "title": None if index in drop_indices else criterion["title"],
                "requirement": (
                    None if index in drop_indices else criterion["requirement"]
                ),
                "level_descriptions": (
                    None if index in drop_indices else criterion["level_descriptions"]
                ),
                "support_pair_ids": (
                    None if index in drop_indices else criterion["support_pair_ids"]
                ),
                "reason": (
                    "The criterion is general and supported."
                    if index not in drop_indices
                    else "The evidence does not establish a general criterion."
                ),
            }
            for index, criterion in enumerate(proposed)
        ],
    }
    return SemanticReviewerOutput(
        response_text=json.dumps(response),
        cost=_cost(),
        generation=_generation("semantic", "semantic-review"),
    )


def _proposer(
    run_proposer=None,
    run_semantic=None,
    *,
    retries: int = 1,
    semantic_calls: int = 5,
) -> RubricBankProposer:
    counters = {"differences": 0, "criteria": 0}

    def default_proposer(**kwargs):
        stage = kwargs["stage"]
        counters[stage] += 1
        value = _difference_value() if stage == "differences" else _criterion_value()
        return _proposer_output(value, f"{stage}-{counters[stage]}")

    return RubricBankProposer(
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        model="proposer",
        base_url=None,
        semantic_judge_model="semantic",
        semantic_judge_base_url=None,
        semantic_judge_max_calls=semantic_calls,
        semantic_judge_max_request_bytes=1_048_576,
        semantic_judge_max_output_tokens=32_768,
        max_retries=retries,
        run_proposer=run_proposer or default_proposer,
        run_semantic_reviewer=(
            run_semantic
            or (lambda **kwargs: _semantic_output(
                kwargs["response_schema"],
                evidence=kwargs["evidence"],
            ))
        ),
    )


def _replace(
    proposer: RubricBankProposer,
    root: Path,
    *,
    policy: RubricBankPolicy = RubricBankPolicy.OFFLINE_ELICITATION,
):
    return proposer.elicit_rubric(
        instruction="Solve the analysis task.",
        current_bank=_initial_bank(),
        policy=policy,
        generation_round=1,
        output_dir=root,
        artifact_history=_history(),
        source_boundary=(
            1 if policy is RubricBankPolicy.ONLINE_ELICITATION else None
        ),
    )


def test_prompt_contract_is_blinded_add_only_and_support_bounded() -> None:
    difference = evolution_module._difference_instructions().lower()
    criterion = evolution_module._criterion_instructions().lower()
    semantic = " ".join(evolution_module._editor_instructions().lower().split())

    assert "do not rank" in difference
    assert "every unordered pair" in difference
    assert "at least three artifacts" in criterion
    assert "no one artifact" in criterion
    assert "do not choose points or weights" in criterion
    assert "unseen solutions" in criterion
    assert "judge-visible" in criterion
    assert "planned or unexecuted code" in criterion
    assert "named but unseen file" in criterion
    assert "evidence is absent or contradictory" in criterion
    assert "cannot verify" in criterion
    assert "accept, rewrite, merge, or drop" in semantic
    assert "directly control" in semantic
    assert "outcome" not in difference + criterion + semantic


def test_generation_identity_covers_history_and_scoring_code() -> None:
    assert set(evolution_module.rubric_generation_implementation_identity()) >= {
        "evolution_sha256",
        "artifact_history_builder_sha256",
        "rubric_bank_sha256",
        "bank_scoring_sha256",
        "full_rubric_judge_sha256",
        "judge_models_sha256",
        "judge_scoring_sha256",
    }


def test_artifact_history_requires_the_complete_pair_graph() -> None:
    history = _history()
    with pytest.raises(ValueError, match="complete pair graph"):
        ArtifactHistory(history.artifacts, history.pairs[:-1])


def test_support_rejects_repeated_edges_around_one_artifact() -> None:
    history = _history()
    hub = history.artifacts[0].artifact_id
    hub_pairs = tuple(
        pair.pair_id for pair in history.pairs if hub in pair.artifact_ids
    )
    with pytest.raises(ValueError, match="shared hub"):
        history.validate_support(hub_pairs)


@pytest.mark.parametrize(
    "policy",
    [
        RubricBankPolicy.OFFLINE_ELICITATION,
        RubricBankPolicy.ONLINE_ELICITATION,
    ],
)
def test_two_stage_elicitation_appends_one_criterion_and_keeps_one_rubric(
    tmp_path: Path,
    policy: RubricBankPolicy,
) -> None:
    calls: list[tuple[str, str]] = []

    def propose(**kwargs):
        calls.append((kwargs["stage"], kwargs["evidence"]))
        value = (
            _difference_value()
            if kwargs["stage"] == "differences"
            else _criterion_value()
        )
        return _proposer_output(value, f"proposal-{len(calls)}")

    generation = _replace(_proposer(propose), tmp_path, policy=policy)
    bank = generation.bank
    parsed = parse_autorubric_rubric(bank.items[0].rubric.content)

    assert [stage for stage, _ in calls] == ["differences", "criteria"]
    assert bank.rubric_count == 1
    assert bank.items[0].weight == 1.0
    assert bank.specification_anchor == _initial_bank().specification_anchor
    assert len(bank.items[0].elicited_criteria) == 1
    assert [item.levels[0].points for item in parsed.criteria] == [60, 40, 20]
    assert parsed.normalization_maximum == 120
    assert generation.proposer_call_budget == 4


def test_only_difference_discovery_sees_raw_artifacts(tmp_path: Path) -> None:
    proposer_evidence: dict[str, str] = {}
    reviewer_evidence: list[str] = []

    def propose(**kwargs):
        proposer_evidence[kwargs["stage"]] = kwargs["evidence"]
        return _proposer_output(
            _difference_value()
            if kwargs["stage"] == "differences"
            else _criterion_value(),
            kwargs["stage"],
        )

    def review(**kwargs):
        reviewer_evidence.append(kwargs["evidence"])
        return _semantic_output(
            kwargs["response_schema"],
            evidence=kwargs["evidence"],
        )

    _replace(_proposer(propose, review), tmp_path)
    assert "artifact one" in proposer_evidence["differences"]
    assert "artifact one" not in proposer_evidence["criteria"]
    assert '"blinded_pair_graph"' in proposer_evidence["criteria"]
    assert _history().artifacts[0].artifact_id in proposer_evidence["criteria"]
    assert "artifact one" in reviewer_evidence[0]
    assert "hidden:pair" not in proposer_evidence["differences"]
    assert "hidden:pair" not in reviewer_evidence[0]
    assert "score" not in proposer_evidence["differences"].lower()


def test_empty_criterion_list_retains_the_current_rubric(tmp_path: Path) -> None:
    def propose(**kwargs):
        value = (
            _difference_value()
            if kwargs["stage"] == "differences"
            else {"criteria": []}
        )
        return _proposer_output(value, kwargs["stage"])

    generation = _replace(_proposer(propose), tmp_path)
    assert generation.bank.items[0].rubric == _initial_bank().items[0].rubric
    assert generation.bank.items[0].lineage is RubricLineage.RETAINED


def test_criterion_needs_support_from_two_pairs_before_review(tmp_path: Path) -> None:
    calls = 0

    def propose(**kwargs):
        nonlocal calls
        calls += 1
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        return _proposer_output(
            _criterion_value(support=_support_pair_ids()[:1]),
            f"criteria-{calls}",
        )

    with pytest.raises(RuntimeError, match="failed after"):
        _replace(_proposer(propose, retries=0), tmp_path)
    assert calls == 2


def test_criterion_schema_leaves_distinctness_to_local_validation() -> None:
    schema = evolution_module._criterion_schema(
        3,
        ("A", "B", "C"),
        _history(),
    )
    support = schema["properties"]["criteria"]["items"]["properties"][  # type: ignore[index]
        "support_pair_ids"
    ]

    assert "uniqueItems" not in support


def test_criterion_rejects_duplicate_support_pairs_before_review(
    tmp_path: Path,
) -> None:
    calls = 0

    def propose(**kwargs):
        nonlocal calls
        calls += 1
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        return _proposer_output(
            _criterion_value(support=[_support_pair_ids()[0]] * 2),
            f"criteria-{calls}",
        )

    with pytest.raises(RuntimeError, match="failed after"):
        _replace(_proposer(propose, retries=0), tmp_path)
    assert calls == 2


def test_meta_conditioned_criterion_is_rejected_before_review(tmp_path: Path) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            value = _difference_value()
        else:
            value = _criterion_value(
                title=f"{_history().artifacts[0].artifact_id} score improvement"
            )
        return _proposer_output(value, kwargs["stage"])

    with pytest.raises(RuntimeError, match="trajectory-specific"):
        _replace(_proposer(propose, retries=0), tmp_path)


def test_validation_retry_is_exact_and_bounded(tmp_path: Path) -> None:
    difference_calls = 0

    def propose(**kwargs):
        nonlocal difference_calls
        if kwargs["stage"] == "differences":
            difference_calls += 1
            if difference_calls == 1:
                return BankProposerOutput(
                    proposal_text="not json",
                    cost=_cost(),
                    generation=_generation("proposer", "bad"),
                )
            return _proposer_output(_difference_value(), "fixed")
        assert "prior response failed validation" not in kwargs["evidence"]
        return _proposer_output(_criterion_value(), "criteria")

    _replace(_proposer(propose, retries=1), tmp_path)
    assert difference_calls == 2


def test_reviewer_drop_removes_the_criterion(tmp_path: Path) -> None:
    calls = {"proposer": 0, "semantic": 0}

    def propose(**kwargs):
        calls["proposer"] += 1
        return _proposer_output(
            _difference_value()
            if kwargs["stage"] == "differences"
            else _criterion_value(),
            f"proposal-{calls['proposer']}",
        )

    def reject(**kwargs):
        calls["semantic"] += 1
        return _semantic_output(
            kwargs["response_schema"],
            evidence=kwargs["evidence"],
            drop_indices=(0,),
        )

    first = _replace(_proposer(propose, reject), tmp_path)
    assert calls == {"proposer": 2, "semantic": 1}
    assert first.bank.items[0].rubric == _initial_bank().items[0].rubric
    assert first.bank.items[0].elicited_criteria == ()
    assert (tmp_path / "bank-0001").is_dir()

    resumed_calls = 0

    def forbidden(**_kwargs):
        nonlocal resumed_calls
        resumed_calls += 1
        raise AssertionError("provider must not run")

    second = _replace(_proposer(forbidden, forbidden), tmp_path)
    assert second == first
    assert resumed_calls == 0


def test_reviewer_can_accept_one_criterion_and_drop_another(
    tmp_path: Path,
) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        first = _criterion_value()["criteria"][0]
        second = {
            "title": "Traceability",
            "requirement": "Connect each result to reproducible evidence.",
            "level_descriptions": [
                {"label": "A", "description": "Complete and reproducible."},
                {"label": "B", "description": "Partly reproducible."},
                {"label": "C", "description": "Missing or unusable."},
            ],
            "support_pair_ids": _support_pair_ids(),
        }
        return _proposer_output(
            {"criteria": [first, second]},
            "criteria",
        )

    def review(**kwargs):
        return _semantic_output(
            kwargs["response_schema"],
            evidence=kwargs["evidence"],
            drop_indices=(1,),
        )

    generation = _replace(_proposer(propose, review), tmp_path)

    assert [
        item.title for item in generation.bank.items[0].elicited_criteria
    ] == ["Robustness"]
    saved_review = json.loads(
        (tmp_path / "bank-0001" / "criterion-edit.json").read_text()
    )
    assert set(saved_review) == {"actions"}
    assert [item["action"] for item in saved_review["actions"]] == [
        "accept",
        "drop",
    ]


def test_reviewer_rewrite_replaces_the_proposed_criterion(tmp_path: Path) -> None:
    def review(**kwargs):
        source = json.loads(kwargs["evidence"])["proposed_criteria"][0]
        return SemanticReviewerOutput(
            response_text=json.dumps({"actions": [{
                "action": "rewrite",
                "source_criterion_ids": [source["criterion_id"]],
                "title": "Observable robustness evidence",
                "requirement": source["requirement"],
                "level_descriptions": source["level_descriptions"],
                "support_pair_ids": source["support_pair_ids"],
                "reason": "The new title states the observable scope.",
            }]}),
            cost=_cost(),
            generation=_generation("semantic", "rewrite"),
        )

    generation = _replace(_proposer(run_semantic=review), tmp_path)
    assert [
        item.title for item in generation.bank.items[0].elicited_criteria
    ] == ["Observable robustness evidence"]


def test_reviewer_rewrite_can_replace_support_from_the_full_history(
    tmp_path: Path,
) -> None:
    replacement_support = [
        _history().pairs[1].pair_id,
        _history().pairs[4].pair_id,
    ]

    def review(**kwargs):
        source = json.loads(kwargs["evidence"])["proposed_criteria"][0]
        return SemanticReviewerOutput(
            response_text=json.dumps({"actions": [{
                "action": "rewrite",
                "source_criterion_ids": [source["criterion_id"]],
                "title": source["title"],
                "requirement": source["requirement"],
                "level_descriptions": source["level_descriptions"],
                "support_pair_ids": replacement_support,
                "reason": "The full history supplies stronger non-hub support.",
            }]}),
            cost=_cost(),
            generation=_generation("semantic", "replacement-support"),
        )

    generation = _replace(_proposer(run_semantic=review), tmp_path)
    assert (
        generation.bank.items[0].elicited_criteria[0].support_pair_ids
        == tuple(replacement_support)
    )


def test_reviewer_merge_combines_two_proposals(tmp_path: Path) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        first = _criterion_value()["criteria"][0]
        second = dict(first)
        second["title"] = "Perturbation evidence"
        second["requirement"] = "Save direct evidence from a relevant perturbation."
        return _proposer_output({"criteria": [first, second]}, "criteria")

    def review(**kwargs):
        proposed = json.loads(kwargs["evidence"])["proposed_criteria"]
        first = proposed[0]
        return SemanticReviewerOutput(
            response_text=json.dumps({"actions": [{
                "action": "merge",
                "source_criterion_ids": [
                    proposed[0]["criterion_id"],
                    proposed[1]["criterion_id"],
                ],
                "title": "Robustness evidence",
                "requirement": (
                    "Test a task-relevant perturbation and save direct evidence."
                ),
                "level_descriptions": first["level_descriptions"],
                "support_pair_ids": first["support_pair_ids"],
                "reason": "The proposals express one overlapping requirement.",
            }]}),
            cost=_cost(),
            generation=_generation("semantic", "merge"),
        )

    generation = _replace(_proposer(propose, review), tmp_path)
    assert [
        item.title for item in generation.bank.items[0].elicited_criteria
    ] == ["Robustness evidence"]


def test_invalid_semantic_review_retries_then_abandons_the_criterion(
    tmp_path: Path,
) -> None:
    calls = 0

    def invalid_review(**_kwargs):
        nonlocal calls
        calls += 1
        return SemanticReviewerOutput(
            response_text=json.dumps({"actions": []}),
            cost=_cost(),
            generation=_generation("semantic", "invalid-semantic-review"),
        )

    first = _replace(_proposer(run_semantic=invalid_review), tmp_path)
    assert calls == 2
    assert first.bank.items[0].elicited_criteria == ()
    ledger = tmp_path / "bank-0001.provider-attempts.json"
    assert ledger.stat().st_mode & 0o222 == 0

    resumed_calls = 0

    def forbidden(**_kwargs):
        nonlocal resumed_calls
        resumed_calls += 1
        raise AssertionError("provider must not run")

    second = _replace(_proposer(forbidden, forbidden), tmp_path)
    assert second == first
    assert resumed_calls == 0


def test_invalid_editor_response_gets_exact_repair_retry(tmp_path: Path) -> None:
    calls = 0

    def review(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            value = {"actions": []}
        else:
            assert "prior editor response failed validation" in kwargs["evidence"]
            evidence = json.loads(kwargs["evidence"].split("\n\n<repair>", 1)[0])
            source = evidence["proposed_criteria"][0]
            value = {"actions": [{
                "action": "accept",
                "source_criterion_ids": [source["criterion_id"]],
                "title": source["title"],
                "requirement": source["requirement"],
                "level_descriptions": source["level_descriptions"],
                "support_pair_ids": source["support_pair_ids"],
                "reason": "The criterion is valid and supported.",
            }]}
        return SemanticReviewerOutput(
            response_text=json.dumps(value),
            cost=_cost(),
            generation=_generation("semantic", f"editor-{calls}"),
        )

    generation = _replace(_proposer(run_semantic=review), tmp_path)
    assert calls == 2
    assert len(generation.bank.items[0].elicited_criteria) == 1


def test_completed_generation_replays_without_provider_calls(tmp_path: Path) -> None:
    first = _replace(_proposer(), tmp_path)
    calls = 0

    def forbidden(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run")

    second = _replace(_proposer(forbidden, forbidden), tmp_path)
    assert second == first
    assert calls == 0
    generation_root = tmp_path / "bank-0001"
    assert all(path.stat().st_mode & 0o222 == 0 for path in generation_root.iterdir())


def test_provider_failure_retries_and_resume_does_not_add_calls(
    tmp_path: Path,
) -> None:
    calls = 0

    def fail(**_kwargs):
        nonlocal calls
        calls += 1
        raise ValueError("transport failed")

    with pytest.raises(RuntimeError, match="failed after 2 calls"):
        _replace(_proposer(fail), tmp_path)
    assert calls == 2
    with pytest.raises(RuntimeError, match="failed after 2 calls"):
        _replace(_proposer(fail), tmp_path)
    assert calls == 2


def test_out_of_order_ledger_prefix_fails_before_dispatch(tmp_path: Path) -> None:
    _replace(_proposer(), tmp_path)
    ledger = tmp_path / "bank-0001.provider-attempts.json"
    ledger.chmod(0o600)
    value = json.loads(ledger.read_text())
    value["attempts"][0]["role"] = "criteria"
    ledger.write_text(json.dumps(value))
    calls = 0

    def forbidden(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run")

    with pytest.raises(RuntimeError, match="prefix differs"):
        _replace(_proposer(forbidden, forbidden), tmp_path)
    assert calls == 0


def test_model_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    def propose(**kwargs):
        output = _proposer_output(
            _difference_value()
            if kwargs["stage"] == "differences"
            else _criterion_value(),
            kwargs["stage"],
        )
        output.generation["effective_model"] = "different"
        return output

    with pytest.raises(RuntimeError, match="failed after 2 calls"):
        _replace(_proposer(propose), tmp_path)


def test_generation_file_tampering_fails_closed(tmp_path: Path) -> None:
    _replace(_proposer(), tmp_path)
    proposal = tmp_path / "bank-0001" / "criterion-proposal.json"
    proposal.chmod(0o600)
    proposal.write_text(json.dumps({"criteria": []}))
    with pytest.raises(RuntimeError, match="file changed"):
        _replace(_proposer(), tmp_path)


def test_rejects_nonexact_control_types_before_dispatch(tmp_path: Path) -> None:
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        return _proposer_output(_difference_value(), "unused")

    proposer = _proposer(run)
    with pytest.raises(ValueError, match="elicitation policy"):
        proposer.elicit_rubric(
            instruction="Solve.",
            current_bank=_initial_bank(),
            policy="offline_elicitation",  # type: ignore[arg-type]
            generation_round=1,
            output_dir=tmp_path,
            artifact_history=_history(),
        )
    with pytest.raises(ValueError, match="integer"):
        proposer.elicit_rubric(
            instruction="Solve.",
            current_bank=_initial_bank(),
            policy=RubricBankPolicy.OFFLINE_ELICITATION,
            generation_round=True,
            output_dir=tmp_path,
            artifact_history=_history(),
        )
    assert calls == 0


def test_online_and_offline_boundaries_are_not_interchangeable(tmp_path: Path) -> None:
    proposer = _proposer()
    with pytest.raises(ValueError, match="cannot use a live boundary"):
        proposer.elicit_rubric(
            instruction="Solve.",
            current_bank=_initial_bank(),
            policy=RubricBankPolicy.OFFLINE_ELICITATION,
            generation_round=1,
            source_boundary=1,
            output_dir=tmp_path / "offline",
            artifact_history=_history(),
        )
    with pytest.raises(ValueError, match="matching live boundary"):
        proposer.elicit_rubric(
            instruction="Solve.",
            current_bank=_initial_bank(),
            policy=RubricBankPolicy.ONLINE_ELICITATION,
            generation_round=1,
            source_boundary=None,
            output_dir=tmp_path / "online",
            artifact_history=_history(),
        )


def test_semantic_call_schedule_is_exact(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="schedule is exhausted"):
        _replace(_proposer(semantic_calls=0), tmp_path)
