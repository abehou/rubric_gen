from __future__ import annotations

import json
from itertools import product
from pathlib import Path

import pytest

import rubric_gen.submission_revision.evolution as evolution_module
import rubric_gen.submission_revision.evolution_assessment as assessment_module
import rubric_gen.submission_revision.evolution_protocol as protocol_module
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.autorubric import parse_autorubric_rubric
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    ArtifactPair,
    BlindedArtifact,
    RedTeamEvidence,
)
from rubric_gen.submission_revision.evolution_provider import (
    ProviderContract,
    StructuredProviderOutput,
)
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricGeneration,
    RubricPolicy,
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


def _development_rubric() -> CompleteRubric:
    return CompleteRubric.from_content(
        _rubric().content
        .replace("Criterion 1: Correct answer", "Criterion 1: Answer accuracy")
        .replace(
            "Description: Produce a correct answer.",
            "Description: Give an accurate answer.",
        )
    )


def _initial_generation() -> RubricGeneration:
    rubric = _rubric()
    return RubricGeneration(
        generation_round=0,
        source_checkpoint=None,
        rubric=rubric,
        elicited_criteria=(),
        proposer_call_budget=0,
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
        ArtifactPair.create(artifacts[index].artifact_id, artifacts[index + 1].artifact_id)
        for index in range(len(artifacts) - 1)
    )
    return ArtifactHistory(
        artifacts=artifacts,
        pairs=pairs,
        red_team_evidence=(),
    )


def _parsed_assessment(
    relation: str,
    view: assessment_module.AssessmentView,
    current_generation: RubricGeneration | None = None,
):
    current = current_generation or _initial_generation()
    schema = assessment_module.assessment_schema(
        _history(),
        view=view,
        current_generation=current,
    )
    return assessment_module.validated_assessment_response(
        json.dumps(_assessment_value(relation=relation, schema=schema)),
        artifact_history=_history(),
        view=view,
        current_generation=current,
    )


def _comparisons():
    return assessment_module.pair_comparisons(
        _parsed_assessment(
            "preferred", assessment_module.AssessmentView.RUBRIC_FREE
        ),
        _parsed_assessment("tie", assessment_module.AssessmentView.ACTIVE_RUBRIC),
        _parsed_assessment(
            "tie", assessment_module.AssessmentView.DEVELOPMENT_RUBRIC
        ),
        _history(),
    )


def _induction_pair_ids() -> list[str]:
    induction, _validation = assessment_module.partition_gaps(_comparisons())
    return [item.pair_id for item in induction]


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


def _proposer_output(value: object, response_id: str) -> StructuredProviderOutput:
    return StructuredProviderOutput(
        response_text=json.dumps(value),
        cost=_cost(),
        generation=_generation("proposer", response_id),
    )


def _assessment_value(
    *,
    relation: str,
    schema: dict[str, object] | None = None,
    base_scores: dict[str, int] | None = None,
) -> dict[str, object]:
    if relation not in {"preferred", "rejected", "tie"}:
        raise AssertionError("invalid test assessment relation")

    def preference(pair: ArtifactPair) -> str:
        if relation == "tie":
            return "tie"
        presented = assessment_module.assessment_artifact_ids(pair)
        artifact_id = pair.artifact_ids[0 if relation == "preferred" else 1]
        return "artifact_A" if artifact_id == presented[0] else "artifact_B"

    result: dict[str, object] = {
        "assessments": [
            {
                "pair_id": pair.pair_id,
                "assessment_A": "This artifact has inspectable task evidence.",
                "assessment_B": "This artifact has weaker task evidence.",
                "preference": preference(pair),
                "reason": "The preferred artifact has stronger task evidence.",
            }
            for pair in _history().pairs
        ]
    }
    if schema is None or "rubric_scores" not in schema["properties"]:  # type: ignore[operator]
        return result
    score_schema = schema["properties"]["rubric_scores"]["items"]  # type: ignore[index]
    score_properties = score_schema["properties"]
    artifact_ids = score_properties["artifact_id"]["enum"]
    maximum = score_properties["base_score"]["maximum"]
    criterion_schema = score_properties["criterion_levels"]["items"]["properties"]
    criterion_ids = criterion_schema["criterion_id"].get("enum", [])
    level_labels = criterion_schema["level"].get("enum", [])
    resolved_base_scores = base_scores or {
        artifact_id: (
            maximum // 2
            if relation == "tie"
            else maximum - index
            if relation == "preferred"
            else index
        )
        for index, artifact_id in enumerate(artifact_ids)
    }
    result["rubric_scores"] = [
        {
            "artifact_id": artifact_id,
            "base_score": resolved_base_scores[artifact_id],
            "criterion_levels": [
                {
                    "criterion_id": criterion_id,
                    "level": level_labels[0],
                }
                for criterion_id in criterion_ids
            ],
            "reason": "The score follows the supplied rubric.",
        }
        for artifact_id in artifact_ids
    ]
    return result


def _criterion_value(
    *,
    title: str = "Robustness",
    provenance: list[str] | None = None,
    replaces: list[str] | None = None,
) -> dict[str, object]:
    return {
        "criteria": [{
            "title": title,
            "requirement": "Test the result under a task-relevant perturbation.",
            "levels": [
                {"label": "A", "description": "The check is complete and valid."},
                {"label": "B", "description": "The check is incomplete."},
                {"label": "C", "description": "The check is absent or invalid."},
            ],
            "provenance_pair_ids": (
                _induction_pair_ids()[:1] if provenance is None else provenance
            ),
            "replaces": [] if replaces is None else replaces,
        }]
    }


def _validation_value(
    schema: dict[str, object],
    *,
    positive_pair_ids: tuple[str, ...] | None = None,
    reverse_pair_ids: tuple[str, ...] = (),
    tie_pair_ids: tuple[str, ...] = (),
    penalize_preferred: bool = False,
):
    item = schema["properties"]["validations"]["items"]  # type: ignore[index]
    properties = item["properties"]
    candidate_ids = properties["criterion_id"]["enum"]
    application_item = properties["artifact_applications"]["items"]
    application_properties = application_item["properties"]
    artifact_ids = application_properties["artifact_id"]["enum"]
    level_labels = application_properties["level"]["enum"]
    comparisons_by_id = {item.pair_id: item for item in _comparisons()}
    positive_pair_ids = (
        (_induction_pair_ids()[0],)
        if positive_pair_ids is None
        else positive_pair_ids
    )
    constrained_ids = {
        *positive_pair_ids,
        *reverse_pair_ids,
        *tie_pair_ids,
    }
    if not constrained_ids <= comparisons_by_id.keys():
        raise AssertionError("validation helper received an unknown pair ID")

    levels_by_artifact = None
    for ranks in product(range(len(level_labels)), repeat=len(artifact_ids)):
        ranks_by_artifact = dict(zip(artifact_ids, ranks, strict=True))

        def pair_ranks(pair_id: str) -> tuple[int, int]:
            comparison = comparisons_by_id[pair_id]
            return (
                ranks_by_artifact[comparison.preferred_artifact_id],
                ranks_by_artifact[comparison.rejected_artifact_id],
            )

        if any(
            preferred >= rejected
            for preferred, rejected in map(pair_ranks, positive_pair_ids)
        ):
            continue
        if any(
            preferred <= rejected
            for preferred, rejected in map(pair_ranks, reverse_pair_ids)
        ):
            continue
        if any(
            preferred != rejected
            for preferred, rejected in map(pair_ranks, tie_pair_ids)
        ):
            continue
        if any(
            preferred > rejected
            for pair_id in comparisons_by_id
            if pair_id not in reverse_pair_ids
            for preferred, rejected in (pair_ranks(pair_id),)
        ):
            continue
        if penalize_preferred:
            support = comparisons_by_id[positive_pair_ids[0]]
            if ranks_by_artifact[support.preferred_artifact_id] == 0:
                continue
        levels_by_artifact = {
            artifact_id: level_labels[ranks_by_artifact[artifact_id]]
            for artifact_id in artifact_ids
        }
        break
    if levels_by_artifact is None:
        raise AssertionError("validation helper constraints are inconsistent")
    return {
        "validations": [
            {
                "criterion_id": criterion_id,
                "observable": True,
                "nonredundant": True,
                "artifact_applications": [
                    {
                        "artifact_id": artifact_id,
                        "level": levels_by_artifact[artifact_id],
                        "reason": "The artifact supports this criterion level.",
                    }
                    for artifact_id in artifact_ids
                ],
                "reason": "The candidate is observable and distinct.",
            }
            for criterion_id in candidate_ids
        ]
    }


def _proposer(run_proposer=None, *, retries: int = 1) -> RubricProposer:
    counters: dict[str, int] = {}

    def default_proposer(**kwargs):
        stage = kwargs["stage"]
        counters[stage] = counters.get(stage, 0) + 1
        if stage == "assessment_rubric_free":
            value = _assessment_value(
                relation="preferred",
                schema=kwargs["response_schema"],
            )
        elif stage in {
            "assessment_active_rubric",
            "assessment_development_rubric",
        }:
            value = _assessment_value(
                relation="tie",
                schema=kwargs["response_schema"],
            )
        elif stage == "induction":
            value = _criterion_value()
        elif stage == "validation":
            value = _validation_value(kwargs["response_schema"])
        else:
            raise AssertionError(f"unexpected stage: {stage}")
        return _proposer_output(value, f"{stage}-{counters[stage]}")

    return RubricProposer(
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        model="proposer",
        max_retries=retries,
        run_proposer=run_proposer or default_proposer,
    )


def _replace(
    proposer: RubricProposer,
    root: Path,
    *,
    policy: RubricPolicy = RubricPolicy.OFFLINE_ELICITATION,
) -> RubricGeneration:
    return proposer.elicit_rubric(
        instruction="Solve the analysis task.",
        original_rubric=_rubric(),
        development_rubric=_development_rubric(),
        current_generation=_initial_generation(),
        policy=policy,
        generation_round=1,
        output_dir=root,
        artifact_history=_history(),
        source_checkpoint=None,
    )


def _next_online_generation(
    proposer: RubricProposer,
    root: Path,
    current: RubricGeneration,
) -> RubricGeneration:
    return proposer.elicit_rubric(
        instruction="Solve the analysis task.",
        original_rubric=_rubric(),
        development_rubric=_development_rubric(),
        current_generation=current,
        policy=RubricPolicy.ONLINE_ELICITATION,
        generation_round=current.generation_round + 1,
        output_dir=root,
        artifact_history=_history(),
        source_checkpoint=current.generation_round,
    )


def test_prompt_contract_uses_simple_pairwise_induction_terms() -> None:
    rubric_free = " ".join(assessment_module.assessment_instructions(
        assessment_module.AssessmentView.RUBRIC_FREE
    ).split()).lower()
    rubric_bound = " ".join(assessment_module.assessment_instructions(
        assessment_module.AssessmentView.ACTIVE_RUBRIC
    ).split()).lower()
    induction = " ".join(protocol_module.induction_instructions().split()).lower()
    validation = " ".join(protocol_module.validation_instructions().split()).lower()
    assessment = rubric_free + rubric_bound

    assert "assess artifact a and artifact b independently" in assessment
    assert "length, polish, confidence" in assessment
    assert "rubric-free task-quality preference" in induction
    assert "correlated evidence" in induction
    assert "without using any rubric" in rubric_free
    assert "higher computed total score" in rubric_bound
    assert "atomic criteria" in induction
    assert "fixed penalty scale" in induction
    assert "do not compare artifacts" in validation
    assert "exact candidate level" in validation
    assert "observable" in validation
    assert "nonredundant" in validation
    assert "failure analyst" not in assessment + induction + validation
    assert "counterexample editor" not in assessment + induction + validation


def test_generation_identity_covers_pairwise_protocol() -> None:
    assert len(evolution_module.rubric_generation_implementation_sha256()) == 64


def test_provider_contract_rejects_oversized_request_before_dispatch() -> None:
    contract = ProviderContract(
        model="test-model",
        max_output_tokens=10,
        max_request_bytes=1,
        service_tier=None,
    )
    with pytest.raises(ValueError, match="request is"):
        contract.generate(
            instructions="instructions",
            evidence="evidence",
            response_schema={"type": "object"},
            request_context="test provider",
            schema_name="test_schema",
        )


def test_provider_contract_uses_five_minute_request_timeout() -> None:
    contract = ProviderContract(
        model="test-model",
        max_output_tokens=10,
        max_request_bytes=100,
        service_tier=None,
    )
    assert contract.record()["client_timeout_seconds"] == 300.0


def test_artifact_history_accepts_only_ordered_matched_pairs() -> None:
    history = _history()
    assert len(history.pairs) == 3
    with pytest.raises(ValueError, match="matched pairs"):
        ArtifactHistory(history.artifacts, history.pairs[::-1], ())


def test_pairwise_assessment_extracts_multi_view_gaps() -> None:
    history = _history()
    rubric_free = _parsed_assessment(
        "preferred",
        assessment_module.AssessmentView.RUBRIC_FREE,
    )
    active = _parsed_assessment(
        "tie",
        assessment_module.AssessmentView.ACTIVE_RUBRIC,
    )
    development = _parsed_assessment(
        "preferred",
        assessment_module.AssessmentView.DEVELOPMENT_RUBRIC,
    )
    comparisons = assessment_module.pair_comparisons(
        rubric_free,
        active,
        development,
        history,
    )
    induction, validation = assessment_module.partition_gaps(comparisons)

    assert len(comparisons) == 3
    assert len(induction) == 2
    assert len(validation) == 1
    assert all(
        item.preferred_artifact_id == pair.artifact_ids[0]
        for item, pair in zip(comparisons, history.pairs, strict=True)
    )
    assert all(
        item.gap_views == (assessment_module.AssessmentView.ACTIVE_RUBRIC,)
        for item in comparisons
    )


def test_agreement_across_all_views_creates_no_induction_gap() -> None:
    history = _history()
    rubric_free = _parsed_assessment(
        "preferred",
        assessment_module.AssessmentView.RUBRIC_FREE,
    )
    active = _parsed_assessment(
        "preferred",
        assessment_module.AssessmentView.ACTIVE_RUBRIC,
    )
    development = _parsed_assessment(
        "preferred",
        assessment_module.AssessmentView.DEVELOPMENT_RUBRIC,
    )

    comparisons = assessment_module.pair_comparisons(
        rubric_free,
        active,
        development,
        history,
    )
    induction, validation = assessment_module.partition_gaps(comparisons)

    assert len(comparisons) == len(history.pairs)
    assert all(not item.gap_views for item in comparisons)
    assert induction == ()
    assert validation == ()


def test_rubric_preference_must_match_the_computed_total_scores() -> None:
    current = _initial_generation()
    schema = assessment_module.assessment_schema(
        _history(),
        view=assessment_module.AssessmentView.ACTIVE_RUBRIC,
        current_generation=current,
    )
    value = _assessment_value(relation="tie", schema=schema)
    value["assessments"][0]["preference"] = "artifact_A"  # type: ignore[index]

    with pytest.raises(ValueError, match="does not match computed"):
        assessment_module.validated_assessment_response(
            json.dumps(value),
            artifact_history=_history(),
            view=assessment_module.AssessmentView.ACTIVE_RUBRIC,
            current_generation=current,
        )


def test_all_views_use_one_fixed_pair_orientation() -> None:
    active_rubric = _rubric()
    development_rubric = _development_rubric()
    payloads = [
        json.loads(
            assessment_module.assessment_evidence(
                instruction="Solve.",
                artifact_history=_history(),
                view=view,
                rubric={
                    assessment_module.AssessmentView.RUBRIC_FREE: None,
                    assessment_module.AssessmentView.ACTIVE_RUBRIC: active_rubric,
                    assessment_module.AssessmentView.DEVELOPMENT_RUBRIC: (
                        development_rubric
                    ),
                }[view],
                current_generation=_initial_generation(),
            )
        )
        for view in assessment_module.AssessmentView
    ]
    orders = [
        [
            (pair["artifact_A"]["artifact_id"], pair["artifact_B"]["artifact_id"])
            for pair in payload["pairs"]
        ]
        for payload in payloads
    ]
    assert orders[0] == orders[1] == orders[2]
    assert "base_rubric" not in payloads[0]
    assert payloads[1]["base_rubric"] == active_rubric.content
    assert payloads[2]["base_rubric"] == development_rubric.content


def test_trace_is_visible_only_to_trace_induction() -> None:
    base = _history()
    pair = base.pairs[0]
    trace = '{"type":"item.completed","item":{"text":"target weak check"}}\n'
    red_team = RedTeamEvidence(
        pair_id=pair.pair_id,
        observed_artifact_id=pair.artifact_ids[0],
        adversarial_artifact_id=pair.artifact_ids[1],
        trajectory_sha256=sha256_text(trace),
        trajectory_excerpt_sha256=sha256_text(trace),
        trajectory_excerpt=trace,
        trajectory_truncated=False,
    )
    history = ArtifactHistory(
        artifacts=base.artifacts,
        pairs=base.pairs,
        red_team_evidence=(red_team,),
    )
    comparisons = _comparisons()
    induction, validation = assessment_module.partition_gaps(
        comparisons,
        priority_induction_pair_ids=history.red_team_pair_ids,
    )
    assert pair.pair_id in {item.pair_id for item in induction}
    assert pair.pair_id not in {item.pair_id for item in validation}

    common = {
        "instruction": "Solve the task.",
        "current_generation": _initial_generation(),
        "artifact_history": history,
        "induction_gaps": induction,
        "level_labels": ("A", "B", "C"),
    }
    artifact_only = json.loads(protocol_module.induction_evidence(
        include_red_team_trace=False,
        **common,
    ))
    trace_aware = json.loads(protocol_module.induction_evidence(
        include_red_team_trace=True,
        **common,
    ))

    assert artifact_only["red_team_pairs"] == [{
        "pair_id": pair.pair_id,
        "observed_artifact_id": pair.artifact_ids[0],
        "adversarial_artifact_id": pair.artifact_ids[1],
    }]
    assert trace_aware["red_team_pairs"][0]["trajectory_excerpt"] == trace
    assert trace_aware["red_team_pairs"][0]["trajectory_truncated"] is False
    validation_payload = json.loads(protocol_module.validation_evidence(
        instruction="Solve the task.",
        current_generation=_initial_generation(),
        artifact_history=history,
        candidates=(),
        comparisons=comparisons,
    ))
    assert "red_team_pairs" not in validation_payload
    assert "target weak check" not in json.dumps(validation_payload)
    assert "rubric_gaps" not in validation_payload
    assert pair.pair_id not in json.dumps(validation_payload)


@pytest.mark.parametrize(
    "policy",
    [
        RubricPolicy.OFFLINE_ELICITATION,
        RubricPolicy.ONLINE_ELICITATION,
        RubricPolicy.RED_TEAM_ARTIFACT,
        RubricPolicy.RED_TEAM_TRACE,
    ],
)
def test_pairwise_induction_builds_one_fixed_penalty_criterion(
    tmp_path: Path,
    policy: RubricPolicy,
) -> None:
    calls: list[str] = []

    def propose(**kwargs):
        calls.append(kwargs["stage"])
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose), tmp_path, policy=policy)
    parsed = parse_autorubric_rubric(generation.rubric.content)

    assert calls == [
        "assessment_rubric_free",
        "assessment_active_rubric",
        "assessment_development_rubric",
        "induction",
        "validation",
    ]
    assert len(generation.elicited_criteria) == 1
    assert [level.points for level in parsed.criteria[-1].levels] == [0, -5, -10]
    assert parsed.normalization_maximum == 100
    assert generation.proposer_call_budget == 10


def test_induction_does_not_see_sources_or_held_out_artifacts(tmp_path: Path) -> None:
    evidence_by_stage: dict[str, str] = {}

    def propose(**kwargs):
        evidence_by_stage[kwargs["stage"]] = kwargs["evidence"]
        return _proposer().run_proposer(**kwargs)

    _replace(_proposer(propose), tmp_path)
    induction_gaps, validation_gaps = (
        assessment_module.partition_gaps(_comparisons())
    )
    held_out = validation_gaps[0]

    assert "hidden:source" not in "".join(evidence_by_stage.values())
    assert held_out.pair_id not in evidence_by_stage["induction"]
    assert held_out.pair_id not in evidence_by_stage["validation"]
    assert held_out.preferred_artifact_id in evidence_by_stage["validation"]
    assert held_out.rejected_artifact_id in evidence_by_stage["validation"]
    assert "rubric_gaps" not in evidence_by_stage["validation"]
    assert "rubric_free_reason" not in evidence_by_stage["validation"]
    assert induction_gaps[0].pair_id in evidence_by_stage["induction"]
    assert induction_gaps[0].pair_id not in evidence_by_stage["validation"]
    assert "provenance_pair_ids" not in evidence_by_stage["validation"]
    assert "adversarially_prompted" not in "".join(evidence_by_stage.values())


def test_schema_assigns_penalties_outside_the_model() -> None:
    induction, _validation = assessment_module.partition_gaps(_comparisons())
    schema = protocol_module.induction_schema(
        ("A", "B", "C"),
        induction,
        _initial_generation(),
    )
    levels = schema["properties"]["criteria"]["items"]["properties"]["levels"]  # type: ignore[index]
    assert "points" not in levels["items"]["properties"]
    assert protocol_module.fixed_penalty_points(("A", "B", "C"), 100) == (
        0,
        -5,
        -10,
    )
    assert protocol_module.fixed_penalty_points(("A", "B"), 4) == (0, -1)


def test_ties_produce_no_candidates_and_no_induction_call(tmp_path: Path) -> None:
    calls: list[str] = []

    def propose(**kwargs):
        stage = kwargs["stage"]
        calls.append(stage)
        if stage.startswith("assessment_"):
            return _proposer_output(
                _assessment_value(
                    relation="tie",
                    schema=kwargs["response_schema"],
                ),
                stage,
            )
        raise AssertionError("later stages must be skipped")

    generation = _replace(_proposer(propose), tmp_path)
    assert calls == [
        "assessment_rubric_free",
        "assessment_active_rubric",
        "assessment_development_rubric",
    ]
    assert generation.elicited_criteria == ()
    assert generation.rubric == _rubric()


def test_candidate_that_reverses_its_cited_pair_is_rejected(
    tmp_path: Path,
) -> None:
    cited_pair_id = _induction_pair_ids()[0]

    def propose(**kwargs):
        if kwargs["stage"] == "validation":
            return _proposer_output(
                _validation_value(
                    kwargs["response_schema"],
                    positive_pair_ids=(),
                    reverse_pair_ids=(cited_pair_id,),
                ),
                "validation",
            )
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose), tmp_path)
    assert generation.elicited_criteria == ()


def test_candidate_that_reduces_an_unrelated_total_margin_is_rejected(
    tmp_path: Path,
) -> None:
    cited_pair_id = _induction_pair_ids()[0]
    unrelated_pair_id = next(
        item.pair_id for item in _comparisons()
        if item.pair_id != cited_pair_id
    )

    def propose(**kwargs):
        if kwargs["stage"] == "validation":
            return _proposer_output(
                _validation_value(
                    kwargs["response_schema"],
                    positive_pair_ids=(cited_pair_id,),
                    reverse_pair_ids=(unrelated_pair_id,),
                ),
                "validation",
            )
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose), tmp_path)
    decisions = json.loads(
        (
            tmp_path
            / "rubric-generations/generation-0001/aggregate-margins.json"
        ).read_text()
    )["decisions"]

    assert generation.elicited_criteria == ()
    assert decisions[0]["reason"] == "aggregate_margin_failed"
    assert any(
        item["pair_id"] == unrelated_pair_id and not item["passed"]
        for item in decisions[0]["margin_checks"]
    )


def test_negative_total_margin_can_improve_without_reversing(
    tmp_path: Path,
) -> None:
    artifact_ids = sorted(
        artifact_id
        for pair in _history().pairs
        for artifact_id in pair.artifact_ids
    )
    base_scores = {
        artifact_id: 40 + 10 * index
        for index, artifact_id in enumerate(dict.fromkeys(artifact_ids))
    }

    def propose(**kwargs):
        stage = kwargs["stage"]
        if stage == "assessment_rubric_free":
            return _proposer_output(
                _assessment_value(
                    relation="preferred",
                    schema=kwargs["response_schema"],
                ),
                stage,
            )
        if stage in {
            "assessment_active_rubric",
            "assessment_development_rubric",
        }:
            return _proposer_output(
                _assessment_value(
                    relation="rejected",
                    schema=kwargs["response_schema"],
                    base_scores=base_scores,
                ),
                stage,
            )
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose), tmp_path)
    decisions = json.loads(
        (
            tmp_path
            / "rubric-generations/generation-0001/aggregate-margins.json"
        ).read_text()
    )["decisions"]
    strict_checks = [
        item for item in decisions[0]["margin_checks"]
        if item["strict_improvement_required"]
    ]

    assert len(generation.elicited_criteria) == 1
    assert strict_checks
    assert all(
        item["current_margin"] == -10
        and -10 < item["prospective_margin"] < 0
        and item["passed"]
        for item in strict_checks
    )


def test_preferred_artifact_can_receive_a_less_severe_penalty(
    tmp_path: Path,
) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "validation":
            return _proposer_output(
                _validation_value(
                    kwargs["response_schema"],
                    penalize_preferred=True,
                ),
                "validation",
            )
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose), tmp_path)
    assert len(generation.elicited_criteria) == 1


def test_validated_candidate_can_replace_an_active_criterion(tmp_path: Path) -> None:
    first = _replace(_proposer(), tmp_path, policy=RubricPolicy.ONLINE_ELICITATION)
    prior_id = first.elicited_criteria[0].criterion_id

    def propose(**kwargs):
        if kwargs["stage"] == "induction":
            return _proposer_output(
                _criterion_value(title="Execution evidence", replaces=[prior_id]),
                "induction",
            )
        return _proposer().run_proposer(**kwargs)

    second = _next_online_generation(_proposer(propose), tmp_path, first)
    assert [item.title for item in second.elicited_criteria] == ["Execution evidence"]
    assert second.elicited_criteria[0].source_generation == 2


def test_replacement_must_preserve_replaced_criterion_provenance(
    tmp_path: Path,
) -> None:
    first = _replace(_proposer(), tmp_path, policy=RubricPolicy.ONLINE_ELICITATION)
    prior = first.elicited_criteria[0]
    old_pair_id = prior.provenance_pair_ids[0]
    new_pair_id = next(
        pair_id for pair_id in _induction_pair_ids()
        if pair_id != old_pair_id
    )

    def propose(**kwargs):
        if kwargs["stage"] == "induction":
            return _proposer_output(
                _criterion_value(
                    title="Execution evidence",
                    provenance=[new_pair_id],
                    replaces=[prior.criterion_id],
                ),
                "induction",
            )
        if kwargs["stage"] == "validation":
            return _proposer_output(
                _validation_value(
                    kwargs["response_schema"],
                    positive_pair_ids=(new_pair_id,),
                    tie_pair_ids=(old_pair_id,),
                ),
                "validation",
            )
        return _proposer().run_proposer(**kwargs)

    second = _next_online_generation(_proposer(propose), tmp_path, first)
    assert second.elicited_criteria == (prior,)


def test_each_candidate_must_be_safe_if_other_replacements_are_rejected(
    tmp_path: Path,
) -> None:
    current = _replace(
        _proposer(),
        tmp_path,
        policy=RubricPolicy.ONLINE_ELICITATION,
    )
    prior = current.elicited_criteria[0]
    replacement = _criterion_value(
        title="Execution evidence",
        replaces=[prior.criterion_id],
    )["criteria"][0]
    conflict = _criterion_value(title=prior.title)["criteria"][0]
    conflict["requirement"] = "Verify each reported conclusion from visible evidence."
    induction, _validation = assessment_module.partition_gaps(_comparisons())

    with pytest.raises(ValueError, match="duplicate criterion titles"):
        protocol_module.validated_induction_response(
            json.dumps({"criteria": [replacement, conflict]}),
            original_rubric=_rubric(),
            current_generation=current,
            generation_round=2,
            level_labels=("A", "B", "C"),
            induction_gaps=induction,
        )


def test_invalid_induction_falls_back_to_the_current_rubric(tmp_path: Path) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "induction":
            return _proposer_output({"criteria": "invalid"}, "induction")
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose, retries=0), tmp_path)
    metadata = json.loads(
        (tmp_path / "rubric-generations/generation-0001/evolution.json").read_text()
    )
    assert generation.elicited_criteria == ()
    assert metadata["induction_fallback_reason"] is not None
    assert metadata["validation_attempt_count"] == 0


def test_invalid_validation_rejects_all_candidates(tmp_path: Path) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "validation":
            return _proposer_output({"validations": "invalid"}, "validation")
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose, retries=0), tmp_path)
    metadata = json.loads(
        (tmp_path / "rubric-generations/generation-0001/evolution.json").read_text()
    )
    assert generation.elicited_criteria == ()
    assert metadata["validation_fallback_reason"] is not None


def test_validation_retry_is_exact_and_bounded(tmp_path: Path) -> None:
    validation_calls = 0

    def propose(**kwargs):
        nonlocal validation_calls
        if kwargs["stage"] == "validation":
            validation_calls += 1
            if validation_calls == 1:
                return _proposer_output({"validations": "invalid"}, "bad")
            assert "prior response failed validation" in kwargs["evidence"]
        return _proposer().run_proposer(**kwargs)

    generation = _replace(_proposer(propose, retries=1), tmp_path)
    assert validation_calls == 2
    assert len(generation.elicited_criteria) == 1


def test_provider_failures_fall_back_without_failing_the_generation(
    tmp_path: Path,
) -> None:
    calls = 0

    def fail(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("provider request timed out")

    generation = _replace(_proposer(fail, retries=5), tmp_path)
    metadata = json.loads(
        (tmp_path / "rubric-generations/generation-0001/evolution.json").read_text()
    )
    assert calls == 12
    assert generation.elicited_criteria == ()
    assert metadata["assessment_rubric_free_attempt_count"] == 4
    assert metadata["assessment_active_rubric_attempt_count"] == 4
    assert metadata["assessment_development_rubric_attempt_count"] == 4


def test_completed_generation_replays_without_provider_calls(tmp_path: Path) -> None:
    first = _replace(_proposer(), tmp_path)
    calls = 0

    def forbidden(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run")

    second = _replace(_proposer(forbidden), tmp_path)
    assert second == first
    assert calls == 0


def test_generation_file_tampering_fails_closed(tmp_path: Path) -> None:
    _replace(_proposer(), tmp_path)
    proposal = tmp_path / "rubric-generations/generation-0001/criterion-proposal.json"
    proposal.chmod(0o600)
    proposal.write_text(json.dumps({"criteria": []}))
    with pytest.raises(RuntimeError, match="file hash changed"):
        _replace(_proposer(), tmp_path)


def test_generation_persists_pairwise_induction_artifacts(tmp_path: Path) -> None:
    _replace(_proposer(), tmp_path)
    root = tmp_path / "rubric-generations/generation-0001"
    assert {path.name for path in root.iterdir()} == {
        "artifact-history.json",
        "pairwise-assessment-rubric-free.json",
        "pairwise-assessment-active-rubric.json",
        "pairwise-assessment-development-rubric.json",
        "pairwise-comparisons.json",
        "criterion-proposal.json",
        "criterion-validation.json",
        "aggregate-margins.json",
        "evolution.json",
        "criteria.json",
        "rubric.txt",
        "manifest.json",
    }
    comparisons = json.loads((root / "pairwise-comparisons.json").read_text())
    assert {item["subset"] for item in comparisons["comparisons"]} == {
        "induction",
        "validation",
    }
    decisions = json.loads((root / "aggregate-margins.json").read_text())
    assert decisions["decisions"][0]["accepted"] is True
    assert decisions["decisions"][0]["margin_checks"]


def test_no_matched_pairs_skips_all_provider_calls(tmp_path: Path) -> None:
    artifact = _history().artifacts[0]
    history = ArtifactHistory((artifact,), (), ())
    calls = 0

    def forbidden(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run")

    generation = _proposer(forbidden).elicit_rubric(
        instruction="Solve the analysis task.",
        original_rubric=_rubric(),
        development_rubric=_development_rubric(),
        current_generation=_initial_generation(),
        policy=RubricPolicy.OFFLINE_ELICITATION,
        generation_round=1,
        output_dir=tmp_path,
        artifact_history=history,
    )
    assert calls == 0
    assert generation.elicited_criteria == ()


def test_rejects_nonexact_control_types_before_dispatch(tmp_path: Path) -> None:
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        return _proposer_output(
            _assessment_value(
                relation="preferred",
                schema=_kwargs["response_schema"],
            ),
            "unused",
        )

    proposer = _proposer(run)
    with pytest.raises(ValueError, match="elicitation policy"):
        proposer.elicit_rubric(
            instruction="Solve.",
            original_rubric=_rubric(),
            development_rubric=_development_rubric(),
            current_generation=_initial_generation(),
            policy="offline_elicitation",  # type: ignore[arg-type]
            generation_round=1,
            output_dir=tmp_path,
            artifact_history=_history(),
        )
    with pytest.raises(ValueError, match="integer"):
        proposer.elicit_rubric(
            instruction="Solve.",
            original_rubric=_rubric(),
            development_rubric=_development_rubric(),
            current_generation=_initial_generation(),
            policy=RubricPolicy.OFFLINE_ELICITATION,
            generation_round=True,
            output_dir=tmp_path,
            artifact_history=_history(),
        )
    assert calls == 0


def test_rejects_development_rubric_with_a_different_score_scale(
    tmp_path: Path,
) -> None:
    development = CompleteRubric.from_content(
        _development_rubric().content
        .replace(
            "RUBRIC: Analysis",
            "RUBRIC: Analysis\n\nScore normalization maximum: 200",
        )
        .replace("Levels: A=60 B=30 C=0", "Levels: A=120 B=60 C=0")
        .replace("Levels: A=40 B=20 C=0", "Levels: A=80 B=40 C=0")
    )
    calls = 0

    def forbidden(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run")

    with pytest.raises(ValueError, match="same score scale"):
        _proposer(forbidden).elicit_rubric(
            instruction="Solve.",
            original_rubric=_rubric(),
            development_rubric=development,
            current_generation=_initial_generation(),
            policy=RubricPolicy.OFFLINE_ELICITATION,
            generation_round=1,
            output_dir=tmp_path,
            artifact_history=_history(),
        )
    assert calls == 0


def test_online_and_offline_checkpoints_are_not_interchangeable(
    tmp_path: Path,
) -> None:
    proposer = _proposer()
    with pytest.raises(ValueError, match="cannot use a live checkpoint"):
        proposer.elicit_rubric(
            instruction="Solve.",
            original_rubric=_rubric(),
            development_rubric=_development_rubric(),
            current_generation=_initial_generation(),
            policy=RubricPolicy.OFFLINE_ELICITATION,
            generation_round=1,
            source_checkpoint=1,
            output_dir=tmp_path / "offline",
            artifact_history=_history(),
        )
    with pytest.raises(ValueError, match="pre-treatment online rubric"):
        proposer.elicit_rubric(
            instruction="Solve.",
            original_rubric=_rubric(),
            development_rubric=_development_rubric(),
            current_generation=_initial_generation(),
            policy=RubricPolicy.ONLINE_ELICITATION,
            generation_round=1,
            source_checkpoint=1,
            output_dir=tmp_path / "online",
            artifact_history=_history(),
        )
