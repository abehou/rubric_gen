from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.evolution as evolution_module
from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.autorubric import parse_autorubric_rubric
from rubric_gen.submission_revision.evolution import (
    BankProposerOutput,
    RubricBankProposer,
    SemanticReviewerOutput,
)
from rubric_gen.submission_revision.feedback import render_rubric_bank
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    RubricBank,
    RubricBankItem,
    RubricBankPolicy,
    RubricLineage,
    identity_criterion_map,
    parse_rubric_member_presentation,
    render_locked_rubric_member,
)
from rubric_gen.submission_revision.user_simulator import _bank_criteria


def _rubric_proposal(
    name: str,
    *,
    point_vectors: tuple[tuple[int, ...], ...] = ((60, 30, 0), (40, 20, 0)),
) -> dict[str, object]:
    return {
        "rubric_title": name,
        "criteria": [
            {
                "title": f"{name} criterion {index}",
                "description": (
                    f"Evaluate every required {name} item {index} in order. "
                    f"Criterion {index}: {name} criterion {index} can appear in evidence."
                ),
                "levels": [
                    {
                        "label": chr(ord("A") + level_index),
                        "points": point,
                        "description": f"Exact {name} level {level_index + 1} text.",
                    }
                    for level_index, point in enumerate(points)
                ],
            }
            for index, points in enumerate(point_vectors, start=1)
        ],
    }


def _complete_rubric(name: str = "anchor") -> CompleteRubric:
    return CompleteRubric.from_content(evolution_module._proposal_rubric_text(
        _rubric_proposal(name),
        normalization_maximum=100,
        scoring_protocol=None,
    ))


def _initial_bank(anchor: CompleteRubric | None = None) -> RubricBank:
    anchor = anchor or _complete_rubric()
    return RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=anchor,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            rubric=anchor,
            weight=1.0,
            lineage=RubricLineage.NEW,
            criterion_map=identity_criterion_map(anchor),
        ),),
    )


def test_anchor_prompt_matches_fail_closed_fidelity_contract() -> None:
    instructions = evolution_module._anchor_instructions()

    assert "preserve every prior requirement" in instructions
    assert "add task-supported requirements" in instructions
    assert "remove" not in instructions


def test_replace_bank_rejects_nonexact_control_types_before_dispatch(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        return _proposer_output(_member_response(current.specification_anchor))

    proposer = _proposer(
        run,
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    with pytest.raises(ValueError, match="replacement policy"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy="invalid_policy",  # type: ignore[arg-type]
            generation_round=1,
            output_dir=tmp_path / "policy",
        )
    with pytest.raises(ValueError, match="round must be an integer"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=True,
            output_dir=tmp_path / "round",
        )
    with pytest.raises(ValueError, match="preceding artifact boundary"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.ADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path / "boundary",
            current_submission="artifact",
            trajectory_path=_trajectory(tmp_path / "trajectory.jsonl"),
            source_boundary=False,
        )
    assert calls == 0


def _anchor_response(bank: RubricBank) -> dict[str, object]:
    return {"specification_anchor": {
        "lineage": "retained",
        "prior_content_sha256": bank.specification_anchor.content_sha256,
        "rubric": None,
    }}


def _refined_anchor_response(bank: RubricBank) -> dict[str, object]:
    return {"specification_anchor": {
        "lineage": "refined",
        "prior_content_sha256": bank.specification_anchor.content_sha256,
        "rubric": _rubric_proposal("refined anchor"),
    }}


def _presentation(
    anchor: CompleteRubric,
    label: str,
    *,
    reverse: bool = False,
) -> dict[str, object]:
    criterion_ids = list(evolution_module._criterion_ids(anchor))
    if reverse:
        criterion_ids.reverse()
    return {
        "title": f"{label} title",
        "overview": f"{label} overview",
        "criteria": [
            {
                "anchor_criterion_id": criterion_id,
                "heading": f"{label} heading {criterion_id}",
                "lens": f"Inspect concrete evidence through {label} {criterion_id}.",
            }
            for criterion_id in criterion_ids
        ],
    }


def _member_response(anchor: CompleteRubric) -> dict[str, object]:
    return {"members": [
        {
            "lineage": "new",
            "prior_content_sha256": None,
            "presentation": _presentation(anchor, "first"),
        },
    ]}


def _generation(model: str, response_id: str) -> dict[str, object]:
    return {
        "provider": "openai",
        "requested_model": model,
        "effective_model": model,
        "response_id": response_id,
        "request_parameters": {"max_output_tokens": 1},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _cost() -> dict[str, float | str | None]:
    return {
        "cost_usd": None,
        "estimated_cost_usd": 0.01,
        "cost_source": "test",
    }


def _proposer_output(value: object, response_id: str = "proposal") -> BankProposerOutput:
    return BankProposerOutput(
        proposal_text=json.dumps(value),
        cost=_cost(),
        generation=_generation("proposer", response_id),
    )


def _semantic_value(
    schema: dict[str, object],
    *,
    verdict: str = "equivalent",
) -> dict[str, object]:
    anchor_schema = schema["properties"]["anchor_fidelity"]  # type: ignore[index]
    anchor_properties = anchor_schema["properties"]
    if "status" in anchor_properties:
        anchor_fidelity: dict[str, object] = {"status": "not_applicable"}
    else:
        anchor_verdict = "faithful" if verdict == "equivalent" else verdict
        anchor_fidelity = {
            "task_fidelity": anchor_verdict,
            "prior_anchor_fidelity": anchor_verdict,
            "issues": (
                []
                if anchor_verdict == "faithful"
                else [{
                    "field": field,
                    "verdict": anchor_verdict,
                    "reason": f"The {field} anchor contract changes.",
                } for field in ("task_fidelity", "prior_anchor_fidelity")]
            ),
        }
    member_schema = schema["properties"]["members"]  # type: ignore[index]
    members: dict[str, object] = {}
    for member_hash in member_schema["required"]:  # type: ignore[index]
        value_schema = member_schema["properties"][member_hash]  # type: ignore[index]
        criteria_schema = value_schema["properties"]["criteria"]  # type: ignore[index]
        criteria = {
            criterion_id: verdict
            for criterion_id in criteria_schema["required"]
        }
        fields = {"overall": verdict, **criteria}
        issues = [
            {
                "field": field,
                "verdict": field_verdict,
                "reason": f"The {field} lens changes the anchor.",
            }
            for field, field_verdict in fields.items()
            if field_verdict != "equivalent"
        ]
        members[member_hash] = {
            "overall": verdict,
            "criteria": criteria,
            "issues": issues,
        }
    return {"anchor_fidelity": anchor_fidelity, "members": members}


def _semantic_output(
    schema: dict[str, object],
    *,
    verdict: str = "equivalent",
) -> SemanticReviewerOutput:
    return SemanticReviewerOutput(
        response_text=json.dumps(_semantic_value(schema, verdict=verdict)),
        cost=_cost(),
        generation=_generation("semantic", "review"),
    )


def _proposer(
    run_proposer,
    run_semantic,
    *,
    retries: int = 2,
    semantic_request_bytes: int = 1_048_576,
) -> RubricBankProposer:
    def singleton_run_proposer(**kwargs):
        output = run_proposer(**kwargs)
        if kwargs["stage"] != "anchor" or not isinstance(
            output, BankProposerOutput
        ):
            return output
        try:
            payload = json.loads(output.proposal_text)
        except json.JSONDecodeError:
            return output
        if not isinstance(payload, dict) or set(payload) != {"members"}:
            return output
        anchor_schema = kwargs["response_schema"]["properties"][
            "specification_anchor"
        ]
        prior_hash = anchor_schema["properties"]["prior_content_sha256"][
            "enum"
        ][0]
        return BankProposerOutput(
            proposal_text=json.dumps({"specification_anchor": {
                "lineage": "retained",
                "prior_content_sha256": prior_hash,
                "rubric": None,
            }}),
            cost=output.cost,
            generation=output.generation,
        )

    return RubricBankProposer(
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        model="proposer",
        base_url=None,
        semantic_judge_model="semantic",
        semantic_judge_base_url=None,
        semantic_judge_max_calls=6,
        semantic_judge_max_request_bytes=semantic_request_bytes,
        semantic_judge_max_output_tokens=32_768,
        max_retries=retries,
        run_proposer=singleton_run_proposer,
        run_semantic_reviewer=run_semantic,
    )


def _trajectory(path: Path) -> Path:
    path.write_text(
        json.dumps({"type": "message", "role": "assistant", "text": "sealed"})
        + "\n"
    )
    return path


def test_generation_implementation_identity_covers_scoring_dependencies() -> None:
    assert set(evolution_module.rubric_generation_implementation_identity()) >= {
        "evolution_sha256",
        "rubric_bank_sha256",
        "bank_scoring_sha256",
        "autorubric_judge_sha256",
        "paperbench_judge_sha256",
        "judge_models_sha256",
        "judge_scoring_sha256",
    }


def test_locked_renderer_preserves_anchor_payload_and_criterion_order() -> None:
    anchor = _complete_rubric("normative")
    presentation = parse_rubric_member_presentation(
        _presentation(anchor, "evidence-first")
    )
    member, criterion_map = render_locked_rubric_member(anchor, presentation)
    anchor_parsed = parse_autorubric_rubric(anchor.content)
    member_parsed = parse_autorubric_rubric(member.content)

    assert [mapping.anchor_criterion_id for mapping in criterion_map] == [
        "criterion_1", "criterion_2"
    ]
    for mapping in criterion_map:
        anchor_criterion = next(
            item for item in anchor_parsed.criteria
            if item.criterion_id == mapping.anchor_criterion_id
        )
        member_criterion = next(
            item for item in member_parsed.criteria
            if item.criterion_id == mapping.member_criterion_id
        )
        assert member_criterion.title == anchor_criterion.title
        assert member_criterion.levels == anchor_criterion.levels
        assert "Evaluate every required" in member_criterion.requirement
        assert "can appear in evidence" in member_criterion.requirement
        assert "Presentation lens (non-normative)" in member_criterion.requirement

    reordered = parse_rubric_member_presentation(
        _presentation(anchor, "reordered", reverse=True)
    )
    with pytest.raises(ValueError, match="exact anchor criterion order"):
        render_locked_rubric_member(anchor, reordered)


def test_member_schema_is_clean_break_and_weights_are_program_owned() -> None:
    current = _initial_bank()
    schema = evolution_module._member_response_schema(
        current,
        next_anchor=current.specification_anchor,
    )
    member_fields = schema["properties"]["members"]["items"]["properties"]  # type: ignore[index]
    assert set(member_fields) == {"lineage", "prior_content_sha256", "presentation"}
    assert schema["properties"]["members"]["minItems"] == 1  # type: ignore[index]
    assert schema["properties"]["members"]["maxItems"] == 1  # type: ignore[index]
    presentation_schema = member_fields["presentation"]["anyOf"][0]
    presentation_fields = presentation_schema["properties"]
    assert presentation_fields["title"]["maxLength"] == 160
    assert presentation_fields["overview"]["maxLength"] == 500
    criterion_fields = presentation_fields["criteria"]["items"]["properties"]
    assert criterion_fields["heading"]["maxLength"] == 160
    assert criterion_fields["lens"]["maxLength"] == 500

    bank, _ = evolution_module._validated_member_response(
        json.dumps(_member_response(current.specification_anchor)),
        current_bank=current,
        next_anchor=current.specification_anchor,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        source_boundary=None,
    )
    assert [item.weight for item in bank.items] == [1.0]

    old = _member_response(current.specification_anchor)
    old["members"][0]["relative_weight"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="invalid member"):
        evolution_module._validated_member_response(
            json.dumps(old),
            current_bank=current,
            next_anchor=current.specification_anchor,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            source_boundary=None,
        )


@pytest.mark.parametrize(
    "invalid_text",
    ["hidden\vline", "hidden\u0085line", "hidden\u2028line", "hidden\x01text"],
)
def test_presentation_rejects_hidden_line_and_control_characters(
    invalid_text: str,
) -> None:
    anchor = _complete_rubric()
    value = _presentation(anchor, "bounded")
    value["criteria"][0]["lens"] = invalid_text  # type: ignore[index]
    with pytest.raises(ValueError, match="printable single-line"):
        parse_rubric_member_presentation(value)


@pytest.mark.parametrize(
    ("field", "length"),
    [("title", 161), ("overview", 501)],
)
def test_presentation_rejects_oversized_global_text(
    field: str,
    length: int,
) -> None:
    anchor = _complete_rubric()
    value = _presentation(anchor, "bounded")
    value[field] = "x" * length
    with pytest.raises(ValueError, match="at most"):
        parse_rubric_member_presentation(value)


def test_member_proposal_rejects_more_than_one_member() -> None:
    current = _initial_bank()
    proposal = _member_response(current.specification_anchor)
    proposal["members"].append({  # type: ignore[union-attr]
        "lineage": "new",
        "prior_content_sha256": None,
        "presentation": _presentation(current.specification_anchor, "second"),
    })
    with pytest.raises(ValueError, match="1 to 1 members"):
        evolution_module._validated_member_response(
            json.dumps(proposal),
            current_bank=current,
            next_anchor=current.specification_anchor,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            source_boundary=None,
        )


def test_presentation_requires_each_anchor_criterion_once() -> None:
    current = _initial_bank()
    proposal = _member_response(current.specification_anchor)
    proposal["members"][0]["presentation"]["criteria"].pop()  # type: ignore[index]
    with pytest.raises(ValueError, match="exact anchor criterion order"):
        evolution_module._validated_member_response(
            json.dumps(proposal),
            current_bank=current,
            next_anchor=current.specification_anchor,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            source_boundary=None,
        )


def test_member_prompt_and_schema_are_policy_blind_for_equal_inputs() -> None:
    current = _initial_bank()
    evidence = []
    schemas = []
    for _policy in (
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        RubricBankPolicy.ADAPTIVE_REPLACEMENT,
    ):
        evidence.append(evolution_module._member_proposer_evidence(
            instruction="Solve.",
            current_bank=current,
            next_anchor=current.specification_anchor,
            repair_error=None,
            rejected_attempts=(),
        ))
        schemas.append(evolution_module._member_response_schema(
            current,
            next_anchor=current.specification_anchor,
        ))
    assert evidence[0] == evidence[1]
    assert schemas[0] == schemas[1]
    assert all(policy.value not in evidence[0] for policy in RubricBankPolicy)
    assert "fixed_equal_weights" not in evidence[0]


def test_adaptive_artifact_context_reaches_only_anchor_stage(tmp_path: Path) -> None:
    current = _initial_bank()
    member_calls: dict[RubricBankPolicy, tuple[str, dict[str, object]]] = {}

    for policy in (
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        RubricBankPolicy.ADAPTIVE_REPLACEMENT,
    ):
        calls: list[dict[str, object]] = []

        def run(**kwargs):
            calls.append(kwargs)
            value = (
                _anchor_response(current)
                if kwargs["stage"] == "anchor"
                else _member_response(current.specification_anchor)
            )
            return _proposer_output(value, str(len(calls)))

        _proposer(run, lambda **kwargs: _semantic_output(kwargs["response_schema"])).replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=policy,
            generation_round=1,
            output_dir=tmp_path / policy.value,
            current_submission="SECRET_SUBMISSION" if policy is RubricBankPolicy.ADAPTIVE_REPLACEMENT else None,
            trajectory_path=(
                _trajectory(tmp_path / "trajectory.jsonl")
                if policy is RubricBankPolicy.ADAPTIVE_REPLACEMENT else None
            ),
            source_boundary=0 if policy is RubricBankPolicy.ADAPTIVE_REPLACEMENT else None,
        )
        member_call = next(call for call in calls if call["stage"] == "members")
        member_calls[policy] = (
            member_call["evidence"],  # type: ignore[arg-type]
            member_call["response_schema"],  # type: ignore[arg-type]
        )
        assert "SECRET_SUBMISSION" not in member_call["evidence"]
        if policy is RubricBankPolicy.ADAPTIVE_REPLACEMENT:
            anchor_call = next(call for call in calls if call["stage"] == "anchor")
            assert "SECRET_SUBMISSION" in anchor_call["evidence"]

    assert len(set(value[0] for value in member_calls.values())) == 1
    assert member_calls[RubricBankPolicy.NONADAPTIVE_REPLACEMENT][1] == (
        member_calls[RubricBankPolicy.ADAPTIVE_REPLACEMENT][1]
    )


@pytest.mark.parametrize("verdict", ["changed", "uncertain"])
def test_semantic_rejection_fails_generation_without_pass_shopping(
    tmp_path: Path,
    verdict: str,
) -> None:
    current = _initial_bank()
    proposer_calls = 0
    review_calls = 0

    def run(**_kwargs):
        nonlocal proposer_calls
        proposer_calls += 1
        return _proposer_output(_member_response(current.specification_anchor))

    def review(**kwargs):
        nonlocal review_calls
        review_calls += 1
        return _semantic_output(kwargs["response_schema"], verdict=verdict)

    with pytest.raises(RuntimeError, match="rejection is sealed"):
        _proposer(run, review, retries=5).replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert proposer_calls == 2
    assert review_calls == 1
    assert not (tmp_path / "bank-0001").exists()
    rejection = tmp_path / "bank-0001.semantic-rejection.json"
    assert rejection.is_file()
    with pytest.raises(RuntimeError, match="sealed semantic rejection"):
        _proposer(run, review, retries=5).replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert proposer_calls == 2
    assert review_calls == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_attempt_field",
        "missing_error",
        "empty_error",
        "changed_reason",
        "boolean_call_budget",
    ],
)
def test_semantic_rejection_requires_exact_member_stage_records(
    tmp_path: Path,
    mutation: str,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(
            kwargs["response_schema"], verdict="changed"
        ),
        retries=5,
    )
    with pytest.raises(RuntimeError, match="rejection is sealed"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    path = tmp_path / "bank-0001.semantic-rejection.json"
    path.chmod(0o600)
    value = json.loads(path.read_text())
    if mutation == "extra_attempt_field":
        value["member_generation"]["attempts"][0]["unexpected"] = True
    elif mutation == "missing_error":
        del value["member_generation"]["final_repair_error"]
    elif mutation == "empty_error":
        value["member_generation"]["final_repair_error"] = ""
    elif mutation == "boolean_call_budget":
        value["member_generation"]["call_budget"] = True
    else:
        value["reason"] = "forged rejection reason"
    path.write_text(json.dumps(value))

    with pytest.raises(RuntimeError, match="sealed semantic rejection"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_semantic_rejection_resume_restores_read_only_seal(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(
            kwargs["response_schema"], verdict="changed"
        ),
    )
    with pytest.raises(RuntimeError, match="rejection is sealed"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    rejection_path = tmp_path / "bank-0001.semantic-rejection.json"
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    rejection_path.chmod(0o600)
    ledger_path.chmod(0o600)

    with pytest.raises(RuntimeError, match="sealed semantic rejection"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert rejection_path.stat().st_mode & 0o222 == 0
    assert ledger_path.stat().st_mode & 0o222 == 0


def test_refined_anchor_gets_one_trajectory_blind_fidelity_review(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer_calls: list[str] = []
    review_calls = 0

    def run(**kwargs):
        stage = kwargs["stage"]
        proposer_calls.append(stage)
        if stage == "anchor":
            assert "SECRET_SUBMISSION" in kwargs["evidence"]
            value = _refined_anchor_response(current)
        else:
            assert "SECRET_SUBMISSION" not in kwargs["evidence"]
            next_anchor, _ = evolution_module._validated_anchor_response(
                json.dumps(_refined_anchor_response(current)),
                current_bank=current,
                policy=RubricBankPolicy.ADAPTIVE_REPLACEMENT,
            )
            value = _member_response(next_anchor)
        return _proposer_output(value, stage)

    def review(**kwargs):
        nonlocal review_calls
        review_calls += 1
        evidence = kwargs["evidence"]
        assert "SECRET_SUBMISSION" not in evidence
        parsed_evidence = json.loads(evidence)
        anchor_input = parsed_evidence["anchor_fidelity_input"]
        assert anchor_input["task_instruction"] == "Solve every requirement."
        assert anchor_input["prior_specification_anchor"] == (
            current.specification_anchor.content
        )
        assert "refined anchor" in anchor_input["proposed_specification_anchor"]
        value = _semantic_value(kwargs["response_schema"])
        value["anchor_fidelity"] = {
            "task_fidelity": "changed",
            "prior_anchor_fidelity": "faithful",
            "issues": [{
                "field": "task_fidelity",
                "verdict": "changed",
                "reason": "The proposed anchor omits a task requirement.",
            }],
        }
        return SemanticReviewerOutput(
            response_text=json.dumps(value),
            cost=_cost(),
            generation=_generation("semantic", "anchor-review"),
        )

    with pytest.raises(RuntimeError, match="rejection is sealed"):
        _proposer(run, review).replace_bank(
            instruction="Solve every requirement.",
            current_bank=current,
            policy=RubricBankPolicy.ADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
            current_submission="SECRET_SUBMISSION",
            trajectory_path=_trajectory(tmp_path / "trajectory.jsonl"),
            source_boundary=0,
        )

    assert proposer_calls == ["anchor", "members"]
    assert review_calls == 1
    rejection = json.loads(
        (tmp_path / "bank-0001.semantic-rejection.json").read_text()
    )
    assert rejection["semantic_review"]["accepted"] is False


def test_malformed_semantic_review_fails_closed_without_proposer_retry(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        return _proposer_output(_member_response(current.specification_anchor))

    malformed = SemanticReviewerOutput(
        response_text="{}",
        cost=_cost(),
        generation=_generation("semantic", "bad-review"),
    )
    with pytest.raises(RuntimeError, match="semantic reviewer returned invalid"):
        _proposer(run, lambda **_kwargs: malformed, retries=5).replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert calls == 2
    with pytest.raises(RuntimeError, match="semantic reviewer returned invalid"):
        _proposer(run, lambda **_kwargs: malformed, retries=5).replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert calls == 2


def test_semantic_dispatch_error_is_sealed_and_resume_does_not_resample(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = {"proposer": 0, "review": 0}

    def run(**_kwargs):
        calls["proposer"] += 1
        return _proposer_output(_member_response(current.specification_anchor))

    def review(**_kwargs):
        calls["review"] += 1
        raise ValueError("provider transport failed after dispatch")

    proposer = _proposer(run, review, retries=5)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="attempt is sealed"):
            proposer.replace_bank(
                instruction="Solve.",
                current_bank=current,
                policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
                generation_round=1,
                output_dir=tmp_path,
            )
    assert calls == {"proposer": 2, "review": 1}


@pytest.mark.parametrize("error_kind", ["value", "json"])
def test_proposer_dispatch_error_is_sealed_and_resume_does_not_resample(
    tmp_path: Path,
    error_kind: str,
) -> None:
    current = _initial_bank()
    calls = {"proposer": 0, "review": 0}

    def run(**_kwargs):
        calls["proposer"] += 1
        if error_kind == "value":
            raise ValueError("provider transport failed after dispatch")
        raise json.JSONDecodeError("provider returned invalid JSON", "", 0)

    def review(**kwargs):
        calls["review"] += 1
        return _semantic_output(kwargs["response_schema"])

    proposer = _proposer(run, review, retries=5)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="attempt is sealed"):
            proposer.replace_bank(
                instruction="Solve.",
                current_bank=current,
                policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
                generation_round=1,
                output_dir=tmp_path,
            )
    assert calls == {"proposer": 1, "review": 0}


def test_semantic_reviewer_effective_model_mismatch_is_terminal(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = {"proposer": 0, "review": 0}

    def run(**_kwargs):
        calls["proposer"] += 1
        return _proposer_output(_member_response(current.specification_anchor))

    def review(**kwargs):
        calls["review"] += 1
        output = _semantic_output(kwargs["response_schema"])
        output.generation["effective_model"] = "unexpected-served-model"
        return output

    proposer = _proposer(run, review, retries=5)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="configured pin"):
            proposer.replace_bank(
                instruction="Solve.",
                current_bank=current,
                policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
                generation_round=1,
                output_dir=tmp_path,
            )

    assert calls == {"proposer": 2, "review": 1}


def test_member_proposer_effective_model_mismatch_is_terminal(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        output = _proposer_output(_member_response(current.specification_anchor))
        output.generation["effective_model"] = "unexpected-served-model"
        return output

    proposer = _proposer(
        run,
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
        retries=0,
    )
    for _ in range(2):
        with pytest.raises(RuntimeError, match="configured pin"):
            proposer.replace_bank(
                instruction="Solve.",
                current_bank=current,
                policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
                generation_round=1,
                output_dir=tmp_path,
            )

    assert calls == 1


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        (None, "OpenAI bank response has no effective model"),
        ("http://judge.invalid/v1", "vLLM bank response has no effective model"),
    ],
)
def test_direct_proposer_requires_provider_effective_model(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str | None,
    message: str,
) -> None:
    hosted_response = SimpleNamespace(
        status="completed",
        output_text="{}",
        usage=None,
        id="response-id",
    )
    vllm_response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="{}"),
        )],
        usage=None,
        id="response-id",
    )

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(
                create=lambda **_arguments: hosted_response
            )
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_arguments: vllm_response
                )
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=FakeOpenAI),
    )

    with pytest.raises(RuntimeError, match=message):
        evolution_module._generate_structured_bank(
            model="pinned-model",
            base_url=base_url,
            service_tier=None,
            instructions="Return JSON.",
            evidence="Evidence.",
            response_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )


def test_identical_semantic_request_reuses_one_sealed_decision(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    member_value = _member_response(current.specification_anchor)
    calls = {"proposer": 0, "review": 0}

    def run(**_kwargs):
        calls["proposer"] += 1
        return _proposer_output(member_value, f"proposal-{calls['proposer']}")

    def review(**kwargs):
        calls["review"] += 1
        return _semantic_output(kwargs["response_schema"])

    proposer = _proposer(run, review)
    first = proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    member_value = {"members": [{
        "lineage": "retained",
        "prior_content_sha256": item.rubric.content_sha256,
        "presentation": None,
    } for item in first.bank.items]}
    second = proposer.replace_bank(
        instruction="Solve.",
        current_bank=first.bank,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=2,
        output_dir=tmp_path,
    )
    assert second.bank.content_sha256 == first.bank.content_sha256
    assert calls == {"proposer": 4, "review": 1}
    generation = json.loads((tmp_path / "bank-0002/generation.json").read_text())
    assert generation["semantic_review"]["cost"]["cost_source"] == (
        "exact-request-reuse"
    )


def test_semantic_reuse_requires_ordered_full_source_replay(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    member_value = _member_response(current.specification_anchor)
    creator = _proposer(
        lambda **_kwargs: _proposer_output(member_value),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    first = creator.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    member_value = {"members": [{
        "lineage": "retained",
        "prior_content_sha256": item.rubric.content_sha256,
        "presentation": None,
    } for item in first.bank.items]}
    calls = {"proposer": 0, "review": 0}

    def run(**_kwargs):
        calls["proposer"] += 1
        return _proposer_output(member_value, "retained")

    def review(**kwargs):
        calls["review"] += 1
        return _semantic_output(kwargs["response_schema"])

    fresh = _proposer(run, review)
    fresh.replace_bank(
        instruction="Solve.",
        current_bank=first.bank,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=2,
        output_dir=tmp_path,
    )
    assert calls == {"proposer": 2, "review": 1}


def test_ordered_replay_rebuilds_semantic_reuse_registry(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    member_value = _member_response(current.specification_anchor)
    creator = _proposer(
        lambda **_kwargs: _proposer_output(member_value),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    first = creator.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    member_value = {"members": [{
        "lineage": "retained",
        "prior_content_sha256": item.rubric.content_sha256,
        "presentation": None,
    } for item in first.bank.items]}
    calls = {"proposer": 0, "review": 0}

    def run(**_kwargs):
        calls["proposer"] += 1
        return _proposer_output(member_value, "retained")

    def reject_review(**_kwargs):
        calls["review"] += 1
        raise AssertionError("validated semantic output was not reused")

    resumed = _proposer(run, reject_review)
    assert resumed.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    ) == first
    second = resumed.replace_bank(
        instruction="Solve.",
        current_bank=first.bank,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=2,
        output_dir=tmp_path,
    )
    assert second.bank.content_sha256 == first.bank.content_sha256
    assert calls == {"proposer": 2, "review": 0}


def test_semantic_registry_is_root_bound_and_rechecks_source_digests(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    member_value = _member_response(current.specification_anchor)
    calls = {"review": 0}

    def review(**kwargs):
        calls["review"] += 1
        return _semantic_output(kwargs["response_schema"])

    proposer = _proposer(
        lambda **_kwargs: _proposer_output(member_value),
        review,
    )
    first = proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path / "first",
    )
    member_value = {"members": [{
        "lineage": "retained",
        "prior_content_sha256": item.rubric.content_sha256,
        "presentation": None,
    } for item in first.bank.items]}
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=first.bank,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=2,
        output_dir=tmp_path / "second",
    )
    assert calls["review"] == 2

    source = tmp_path / "first/bank-0001/anchor-proposal.json"
    source.chmod(0o600)
    source.write_text(source.read_text() + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="attempt is sealed") as exc_info:
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=first.bank,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=2,
            output_dir=tmp_path / "first",
        )
    assert exc_info.value.__cause__ is not None
    assert "semantic source" in str(exc_info.value.__cause__)


def test_accepted_raw_member_output_must_reproduce_sealed_proposal(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    changed = _member_response(current.specification_anchor)
    changed["members"][0]["presentation"]["overview"] = "Changed overview"
    changed_raw = json.dumps(changed)
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger_path.chmod(0o600)
    ledger = json.loads(ledger_path.read_text())
    ledger["attempts"][0]["output"]["response"] = changed_raw
    ledger_path.write_text(json.dumps(ledger))
    metadata_path = tmp_path / "bank-0001/generation.json"
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_text())
    metadata["member_generation"]["attempts"][0][
        "provider_response_sha256"
    ] = sha256_text(changed_raw)
    metadata["provider_attempt_ledger_sha256"] = sha256_file(ledger_path)
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(
        RuntimeError,
        match="provider attempt ledger differs|reproduce the sealed proposal",
    ):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_accepted_raw_semantic_output_must_reproduce_sealed_review(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    generation = proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    schema = evolution_module._semantic_review_schema(
        generation.bank,
        prior_anchor=current.specification_anchor,
    )
    changed_raw = json.dumps(_semantic_value(schema, verdict="changed"))
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger_path.chmod(0o600)
    ledger = json.loads(ledger_path.read_text())
    ledger["attempts"][1]["output"]["response"] = changed_raw
    ledger_path.write_text(json.dumps(ledger))
    metadata_path = tmp_path / "bank-0001/generation.json"
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_text())
    changed_sha256 = sha256_text(changed_raw)
    metadata["semantic_review"]["provider_response_sha256"] = changed_sha256
    metadata["member_generation"]["attempts"][0]["semantic_review"][
        "provider_response_sha256"
    ] = changed_sha256
    metadata["provider_attempt_ledger_sha256"] = sha256_file(ledger_path)
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(
        RuntimeError,
        match="provider attempt ledger differs|reproduce the sealed proposal",
    ):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_accepted_proposal_hash_is_bound_to_sealed_response(tmp_path: Path) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    metadata_path = tmp_path / "bank-0001/generation.json"
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_text())
    metadata["member_generation"]["attempts"][0]["proposal_sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(RuntimeError, match="invalid complete-bank generation"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_invalid_proposer_cost_is_terminal_and_does_not_retry(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        output = _proposer_output(_member_response(current.specification_anchor))
        output.cost["estimated_cost_usd"] = -1.0
        return output

    proposer = _proposer(
        run,
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
        retries=5,
    )
    for _ in range(2):
        with pytest.raises(RuntimeError, match="invalid cost metadata"):
            proposer.replace_bank(
                instruction="Solve.",
                current_bank=current,
                policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
                generation_round=1,
                output_dir=tmp_path,
            )
    assert calls == 1


def test_finalized_generation_requires_untampered_provider_ledger(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    ledger = tmp_path / "bank-0001.provider-attempts.json"
    ledger.chmod(0o600)
    value = json.loads(ledger.read_text())
    value["attempts"][0]["request"]["prompt_sha256"] = "0" * 64
    ledger.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="provider attempt ledger"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_existing_empty_provider_ledger_cannot_resume_dispatch(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        return _proposer_output(_member_response(current.specification_anchor))

    proposer = _proposer(
        run,
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger = proposer._load_provider_ledger(
        ledger_path,
        prior_bank_sha256=current.content_sha256,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        create=True,
    )
    ledger_path.write_text(json.dumps(ledger))

    with pytest.raises(RuntimeError, match="provider attempt ledger changed"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert calls == 0


def test_out_of_order_provider_ledger_cannot_resume_dispatch(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer_calls = 0
    reviewer_calls = 0

    def run(**_kwargs):
        nonlocal proposer_calls
        proposer_calls += 1
        return _proposer_output(_member_response(current.specification_anchor))

    def review(**kwargs):
        nonlocal reviewer_calls
        reviewer_calls += 1
        return _semantic_output(kwargs["response_schema"])

    proposer = _proposer(run, review)
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger = proposer._load_provider_ledger(
        ledger_path,
        prior_bank_sha256=current.content_sha256,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        create=True,
    )
    request = {"forged": True}
    ledger["attempts"].append({
        "call_index": 1,
        "role": "members",
        "attempt": 2,
        "request": request,
        "request_sha256": evolution_module._canonical_object_sha256(request),
        "state": "completed",
        "output": {
            "kind": "proposer",
            "response": "{}",
            "cost": {},
            "generation": {},
        },
        "source": None,
        "error": None,
    })
    ledger_path.write_text(json.dumps(ledger))

    with pytest.raises(RuntimeError, match="attempt order changed"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert proposer_calls == 0
    assert reviewer_calls == 0


@pytest.mark.parametrize(
    ("policy", "role"),
    [
        (RubricBankPolicy.NONADAPTIVE_REPLACEMENT, "members"),
        (RubricBankPolicy.NONADAPTIVE_REPLACEMENT, "anchor"),
    ],
)
def test_nonsemantic_reused_prefix_cannot_resume_dispatch(
    tmp_path: Path,
    policy: RubricBankPolicy,
    role: str,
) -> None:
    current = _initial_bank()
    proposer_calls = 0
    reviewer_calls = 0

    def run(**_kwargs):
        nonlocal proposer_calls
        proposer_calls += 1
        return _proposer_output(_member_response(current.specification_anchor))

    def review(**kwargs):
        nonlocal reviewer_calls
        reviewer_calls += 1
        return _semantic_output(kwargs["response_schema"])

    proposer = _proposer(run, review)
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger = proposer._load_provider_ledger(
        ledger_path,
        prior_bank_sha256=current.content_sha256,
        policy=policy,
        generation_round=1,
        create=True,
    )
    request = {"forged": True}
    ledger["attempts"].append({
        "call_index": 1,
        "role": role,
        "attempt": 1,
        "request": request,
        "request_sha256": evolution_module._canonical_object_sha256(request),
        "state": "reused",
        "output": {
            "kind": "proposer",
            "response": "{}",
            "cost": {},
            "generation": {},
        },
        "source": "bank-0000.provider-attempts.json",
        "error": None,
    })
    ledger_path.write_text(json.dumps(ledger))

    with pytest.raises(RuntimeError, match="only semantic provider attempts"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=policy,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert proposer_calls == 0
    assert reviewer_calls == 0


def test_finalized_generation_rejects_extra_provider_output_fields(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger_path.chmod(0o600)
    ledger = json.loads(ledger_path.read_text())
    ledger["attempts"][0]["output"]["unexpected"] = True
    ledger_path.write_text(json.dumps(ledger))
    metadata_path = tmp_path / "bank-0001/generation.json"
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_text())
    metadata["provider_attempt_ledger_sha256"] = sha256_file(ledger_path)
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(RuntimeError, match="provider attempt"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


@pytest.mark.parametrize("field", ["generation_round", "call_index"])
def test_provider_ledger_rejects_boolean_integer_fields(
    tmp_path: Path,
    field: str,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger_path.chmod(0o600)
    ledger = json.loads(ledger_path.read_text())
    if field == "generation_round":
        ledger["generation_round"] = True
    else:
        ledger["attempts"][0]["call_index"] = True
    ledger_path.write_text(json.dumps(ledger))
    metadata_path = tmp_path / "bank-0001/generation.json"
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_text())
    metadata["provider_attempt_ledger_sha256"] = sha256_file(ledger_path)
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(RuntimeError, match="provider attempt ledger"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


@pytest.mark.parametrize(
    "field",
    [
        "generation_round",
        "proposer_call_budget",
        "member_call_budget",
        "member_attempt_count",
        "member_attempt_number",
        "anchor_call_budget",
        "anchor_attempt_count",
    ],
)
def test_generation_metadata_rejects_boolean_integer_fields(
    tmp_path: Path,
    field: str,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
        retries=0,
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    metadata_path = tmp_path / "bank-0001/generation.json"
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_text())
    if field in {"generation_round", "proposer_call_budget"}:
        metadata[field] = True
    elif field == "member_call_budget":
        metadata["member_generation"]["call_budget"] = True
    elif field == "member_attempt_count":
        metadata["member_generation"]["attempt_count"] = True
    elif field == "member_attempt_number":
        metadata["member_generation"]["attempts"][0]["attempt"] = True
    elif field == "anchor_call_budget":
        metadata["anchor_generation"]["call_budget"] = False
    else:
        metadata["anchor_generation"]["attempt_count"] = False
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(RuntimeError, match="invalid complete-bank generation"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_completed_generation_resume_restores_read_only_seal(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    ledger_path = tmp_path / "bank-0001.provider-attempts.json"
    ledger_path.chmod(0o600)

    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    assert ledger_path.stat().st_mode & 0o222 == 0


def test_finalized_generation_requires_its_provider_ledger(tmp_path: Path) -> None:
    current = _initial_bank()
    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        lambda **kwargs: _semantic_output(kwargs["response_schema"]),
    )
    proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    ledger = tmp_path / "bank-0001.provider-attempts.json"
    ledger.chmod(0o600)
    ledger.unlink()

    with pytest.raises(RuntimeError, match="ledger is missing"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_semantic_issue_list_must_cover_each_non_equivalent_verdict() -> None:
    current = _initial_bank()
    bank, _ = evolution_module._validated_member_response(
        json.dumps(_member_response(current.specification_anchor)),
        current_bank=current,
        next_anchor=current.specification_anchor,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        source_boundary=None,
    )
    schema = evolution_module._semantic_review_schema(
        bank,
        prior_anchor=current.specification_anchor,
    )
    value = _semantic_value(schema, verdict="equivalent")
    first = next(iter(value["members"].values()))  # type: ignore[union-attr]
    first["criteria"]["criterion_1"] = "changed"
    with pytest.raises(ValueError, match="do not cover"):
        evolution_module._validated_semantic_review(
            json.dumps(value),
            bank=bank,
            prior_anchor=current.specification_anchor,
        )


def test_accepted_generation_persists_exact_review_and_resumes_without_calls(
    tmp_path: Path,
) -> None:
    current = _initial_bank()
    calls = {"proposer": 0, "review": 0}

    def run(**_kwargs):
        calls["proposer"] += 1
        return _proposer_output(_member_response(current.specification_anchor))

    def review(**kwargs):
        calls["review"] += 1
        return _semantic_output(kwargs["response_schema"])

    proposer = _proposer(run, review)
    first = proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    second = proposer.replace_bank(
        instruction="Solve.",
        current_bank=current,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        generation_round=1,
        output_dir=tmp_path,
    )
    assert first == second
    assert calls == {"proposer": 2, "review": 1}
    metadata = json.loads((tmp_path / "bank-0001/generation.json").read_text())
    nested = metadata["member_generation"]["attempts"][0]["semantic_review"]
    assert nested["response"] == (tmp_path / "bank-0001/semantic-review.json").read_text()

    path = tmp_path / "bank-0001/generation.json"
    path.chmod(0o600)
    metadata["member_generation"]["attempts"][0]["semantic_review"]["accepted"] = False
    path.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match="invalid complete-bank generation"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )


def test_request_byte_cap_fails_before_adaptive_provider_dispatch(tmp_path: Path) -> None:
    current = _initial_bank()
    calls = 0

    def run(**_kwargs):
        nonlocal calls
        calls += 1
        return _proposer_output(_anchor_response(current))

    with pytest.raises(ValueError, match="UTF-8 bytes; the limit"):
        _proposer(run, lambda **kwargs: _semantic_output(kwargs["response_schema"])).replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.ADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path / "generation",
            current_submission="é" * 600_000,
            trajectory_path=_trajectory(tmp_path / "trajectory.jsonl"),
            source_boundary=0,
        )
    assert calls == 0


def test_semantic_request_cap_fails_before_reviewer_dispatch(tmp_path: Path) -> None:
    current = _initial_bank()
    reviewer_calls = 0

    def review(**_kwargs):
        nonlocal reviewer_calls
        reviewer_calls += 1
        raise AssertionError("semantic reviewer must not run")

    proposer = _proposer(
        lambda **_kwargs: _proposer_output(
            _member_response(current.specification_anchor)
        ),
        review,
        semantic_request_bytes=1,
    )
    with pytest.raises(RuntimeError, match="semantic reviewer request"):
        proposer.replace_bank(
            instruction="Solve.",
            current_bank=current,
            policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            generation_round=1,
            output_dir=tmp_path,
        )
    assert reviewer_calls == 0


def test_semantic_judge_must_differ_from_member_proposer() -> None:
    with pytest.raises(ValueError, match="must differ"):
        RubricBankProposer(
            benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
            model="same",
            base_url=None,
            semantic_judge_model="same",
            semantic_judge_base_url=None,
            semantic_judge_max_calls=1,
            semantic_judge_max_request_bytes=1_048_576,
            semantic_judge_max_output_tokens=32_768,
        )
