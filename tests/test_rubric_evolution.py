from __future__ import annotations

import json
from pathlib import Path

import pytest

import rubric_gen.submission_revision.evolution as evolution_module
import rubric_gen.submission_revision.evolution_protocol as protocol_module
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.autorubric import parse_autorubric_rubric
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    ArtifactPair,
    BlindedArtifact,
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
        ArtifactPair.create(artifacts[left].artifact_id, artifacts[right].artifact_id)
        for left in range(len(artifacts))
        for right in range(left + 1, len(artifacts))
    )
    return ArtifactHistory(artifacts=artifacts, pairs=pairs)


def _provenance_pair_ids() -> list[str]:
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


def _proposer_output(value: object, response_id: str) -> StructuredProviderOutput:
    return StructuredProviderOutput(
        response_text=json.dumps(value),
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
    provenance: list[str] | None = None,
) -> dict[str, object]:
    return {
        "criteria": [{
            "title": title,
            "requirement": "Test the result under a task-relevant perturbation.",
            "levels": [
                {"label": "A", "points": 0, "description": "Complete and correct."},
                {"label": "B", "points": -3, "description": "Partly correct."},
                {"label": "C", "points": -9, "description": "Missing or incorrect."},
            ],
            "provenance_pair_ids": (
                _provenance_pair_ids() if provenance is None else provenance
            ),
        }]
    }


def _proposer(run_proposer=None, *, retries: int = 1) -> RubricProposer:
    counters = {"differences": 0, "rubric": 0}

    def default_proposer(**kwargs):
        stage = kwargs["stage"]
        counters[stage] += 1
        value = _difference_value() if stage == "differences" else _criterion_value()
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
    instruction: str = "Solve the analysis task.",
) -> RubricGeneration:
    return proposer.elicit_rubric(
        instruction=instruction,
        original_rubric=_rubric(),
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
        current_generation=current,
        policy=RubricPolicy.ONLINE_ELICITATION,
        generation_round=current.generation_round + 1,
        output_dir=root,
        artifact_history=_history(),
        source_checkpoint=current.generation_round,
    )


def test_prompt_contract_is_blinded_model_weighted_and_complete_set() -> None:
    difference = protocol_module.difference_instructions().lower()
    rubric = " ".join(protocol_module.rubric_instructions().lower().split())

    assert "do not rank" in difference
    assert "every unordered pair" in difference
    assert "not a minimum support threshold" in rubric
    assert "choose the integer penalty points" in rubric
    assert "too small" in rubric
    assert "too large" in rubric
    assert "choose the set size" in rubric
    assert "complete active learned-criterion set" in rubric
    assert "retain, rewrite, merge, retire, replace, or add" in rubric
    assert "unseen solutions" in rubric
    assert "judge-visible" in rubric
    assert "planned or unexecuted code" in rubric
    assert "named but unseen file" in rubric
    assert "evidence is absent or contradictory" in rubric
    assert "cannot verify" in rubric
    assert "observed solution result" in rubric
    assert "task or original rubric" in rubric
    assert "outcome" not in difference + rubric


def test_generation_identity_covers_history_and_scoring_code() -> None:
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


def test_artifact_history_requires_the_complete_pair_graph() -> None:
    history = _history()
    with pytest.raises(ValueError, match="complete pair graph"):
        ArtifactHistory(history.artifacts, history.pairs[:-1])


def test_artifact_history_allows_one_unique_valid_attempt() -> None:
    content = "one structurally valid attempt"
    artifact = BlindedArtifact(
        artifact_id="artifact_0000000000000001",
        source_id="hidden:source:1",
        content_sha256=sha256_text(content),
        content=content,
    )

    history = ArtifactHistory((artifact,), ())

    assert history.artifacts == (artifact,)
    assert history.pairs == ()


def test_provenance_allows_one_pair_and_repeated_edges_around_one_artifact() -> None:
    history = _history()
    hub = history.artifacts[0].artifact_id
    hub_pairs = tuple(
        pair.pair_id for pair in history.pairs if hub in pair.artifact_ids
    )
    assert history.validate_provenance(hub_pairs) == hub_pairs
    assert history.validate_provenance(hub_pairs[:1]) == hub_pairs[:1]


@pytest.mark.parametrize(
    "policy",
    [RubricPolicy.OFFLINE_ELICITATION, RubricPolicy.ONLINE_ELICITATION],
)
def test_two_stage_elicitation_builds_one_model_weighted_active_criterion(
    tmp_path: Path,
    policy: RubricPolicy,
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
    parsed = parse_autorubric_rubric(generation.rubric.content)

    assert [stage for stage, _ in calls] == ["differences", "rubric"]
    assert generation.generation_round == 1
    assert len(generation.elicited_criteria) == 1
    assert [item.levels[0].points for item in parsed.criteria] == [60, 40, 0]
    assert [level.points for level in parsed.criteria[-1].levels] == [0, -3, -9]
    assert parsed.normalization_maximum == 100
    assert generation.proposer_call_budget == 4


def test_both_proposer_stages_see_the_blinded_artifact_history(
    tmp_path: Path,
) -> None:
    evidence_by_stage: dict[str, str] = {}

    def propose(**kwargs):
        evidence_by_stage[kwargs["stage"]] = kwargs["evidence"]
        value = (
            _difference_value()
            if kwargs["stage"] == "differences"
            else _criterion_value()
        )
        return _proposer_output(value, kwargs["stage"])

    _replace(_proposer(propose), tmp_path)

    assert "artifact one" in evidence_by_stage["differences"]
    assert "artifact one" in evidence_by_stage["rubric"]
    assert '"blinded_artifact_history"' in evidence_by_stage["rubric"]
    assert _history().artifacts[0].artifact_id in evidence_by_stage["rubric"]
    assert "hidden:pair" not in evidence_by_stage["differences"]
    assert "hidden:pair" not in evidence_by_stage["rubric"]
    assert "score" not in evidence_by_stage["differences"].lower()


def test_rubric_evidence_uses_current_rubric_without_duplicate_original() -> None:
    evidence = json.loads(protocol_module.rubric_evidence(
        instruction="Solve the analysis task.",
        original_rubric=_rubric(),
        current_generation=_initial_generation(),
        artifact_history=_history(),
        difference_response=_difference_value(),
        level_labels=("A", "B", "C"),
    ))

    assert "original_rubric" not in evidence
    assert evidence["current_rubric"] == _rubric().content


def test_empty_criterion_list_retains_the_current_rubric(tmp_path: Path) -> None:
    def propose(**kwargs):
        value = (
            _difference_value()
            if kwargs["stage"] == "differences"
            else {"criteria": []}
        )
        return _proposer_output(value, kwargs["stage"])

    generation = _replace(_proposer(propose), tmp_path)
    assert generation.rubric == _initial_generation().rubric


def test_criterion_allows_one_provenance_pair(tmp_path: Path) -> None:
    calls = 0

    def propose(**kwargs):
        nonlocal calls
        calls += 1
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        return _proposer_output(
            _criterion_value(provenance=_provenance_pair_ids()[:1]),
            f"rubric-{calls}",
        )

    generation = _replace(_proposer(propose, retries=0), tmp_path)
    assert calls == 2
    assert generation.elicited_criteria[0].provenance_pair_ids == tuple(
        _provenance_pair_ids()[:1]
    )


def test_rubric_schema_has_no_count_or_penalty_magnitude_cap() -> None:
    schema = protocol_module.rubric_schema(("A", "B", "C"), _history())
    criteria = schema["properties"]["criteria"]  # type: ignore[index]
    item = criteria["items"]
    support = item["properties"]["provenance_pair_ids"]
    points = item["properties"]["levels"]["items"]["properties"]["points"]

    assert "uniqueItems" not in support
    assert "maxItems" not in criteria
    assert points == {"type": "integer"}


def test_invalid_penalty_schedule_falls_back_to_the_current_set(
    tmp_path: Path,
) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        value = _criterion_value()
        value["criteria"][0]["levels"][1]["points"] = 0
        return _proposer_output(value, "rubric")

    generation = _replace(_proposer(propose, retries=0), tmp_path)
    metadata = json.loads(
        (
            tmp_path
            / "rubric-generations"
            / "generation-0001"
            / "evolution.json"
        ).read_text()
    )

    assert generation.elicited_criteria == ()
    assert "strictly decrease" in metadata["rubric_fallback_reason"]


def test_model_can_rewrite_the_active_penalty_schedule_online(
    tmp_path: Path,
) -> None:
    first = _replace(_proposer(), tmp_path, policy=RubricPolicy.ONLINE_ELICITATION)

    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "round-two-differences")
        value = _criterion_value()
        value["criteria"][0]["levels"][1]["points"] = -6
        value["criteria"][0]["levels"][2]["points"] = -18
        return _proposer_output(value, "round-two-rubric")

    second = _next_online_generation(_proposer(propose), tmp_path, first)

    assert len(second.elicited_criteria) == 1
    assert [point for _, point, _ in second.elicited_criteria[0].levels] == [
        0,
        -6,
        -18,
    ]
    assert second.elicited_criteria[0].source_generation == 2
    assert second.elicited_criteria[0].criterion_id != first.elicited_criteria[0].criterion_id


def test_complete_proposer_can_retire_all_active_criteria(tmp_path: Path) -> None:
    first = _replace(_proposer(), tmp_path, policy=RubricPolicy.ONLINE_ELICITATION)

    def propose(**kwargs):
        value = (
            _difference_value()
            if kwargs["stage"] == "differences"
            else {"criteria": []}
        )
        return _proposer_output(value, f"round-two-{kwargs['stage']}")

    second = _next_online_generation(_proposer(propose), tmp_path, first)

    assert second.elicited_criteria == ()
    assert second.rubric == _rubric()


def test_duplicate_provenance_pairs_trigger_lenient_fallback(tmp_path: Path) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        return _proposer_output(
            _criterion_value(provenance=[_provenance_pair_ids()[0]] * 2),
            "rubric",
        )

    generation = _replace(_proposer(propose, retries=0), tmp_path)
    assert generation.elicited_criteria == ()


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("title", f"{_history().artifacts[0].artifact_id} score improvement"),
        ("description", "Reports an enrichment ratio of approximately 1.39-fold."),
        ("requirement", "Preserve source identifier 17e905999814."),
    ],
)
def test_semantic_content_is_not_mechanically_rejected(
    tmp_path: Path,
    field: str,
    text: str,
) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        value = _criterion_value()
        if field == "description":
            value["criteria"][0]["levels"][0]["description"] = text
        else:
            value["criteria"][0][field] = text
        return _proposer_output(value, "rubric")

    generation = _replace(_proposer(propose, retries=0), tmp_path)
    assert len(generation.elicited_criteria) == 1


def test_validation_retry_is_exact_and_bounded(tmp_path: Path) -> None:
    difference_calls = 0

    def propose(**kwargs):
        nonlocal difference_calls
        if kwargs["stage"] == "differences":
            difference_calls += 1
            if difference_calls == 1:
                return StructuredProviderOutput(
                    response_text="not json",
                    cost=_cost(),
                    generation=_generation("proposer", "bad"),
                )
            assert "prior response failed validation" in kwargs["evidence"]
            return _proposer_output(_difference_value(), "fixed")
        return _proposer_output(_criterion_value(), "rubric")

    _replace(_proposer(propose, retries=1), tmp_path)
    assert difference_calls == 2


def test_invalid_rubric_response_gets_one_exact_repair_retry(
    tmp_path: Path,
) -> None:
    rubric_calls = 0

    def propose(**kwargs):
        nonlocal rubric_calls
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        rubric_calls += 1
        if rubric_calls == 1:
            return _proposer_output({"criteria": "invalid"}, "bad-rubric")
        assert "prior rubric response failed validation" in kwargs["evidence"]
        return _proposer_output(_criterion_value(), "fixed-rubric")

    generation = _replace(_proposer(propose, retries=1), tmp_path)
    assert rubric_calls == 2
    assert len(generation.elicited_criteria) == 1


def test_complete_proposer_persists_its_active_set(tmp_path: Path) -> None:
    def propose(**kwargs):
        if kwargs["stage"] == "differences":
            return _proposer_output(_difference_value(), "differences")
        return _proposer_output(_criterion_value(title="Traceability"), "rubric")

    generation = _replace(_proposer(propose), tmp_path)

    assert [item.title for item in generation.elicited_criteria] == ["Traceability"]
    saved = json.loads(
        (
            tmp_path
            / "rubric-generations"
            / "generation-0001"
            / "rubric-proposal.json"
        ).read_text()
    )
    assert set(saved) == {"criteria"}


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
    generation_root = tmp_path / "rubric-generations" / "generation-0001"
    assert all(path.stat().st_mode & 0o200 for path in generation_root.iterdir())


def test_incomplete_generation_restarts_from_the_first_stage(tmp_path: Path) -> None:
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
    assert calls == 4


def test_provider_failures_stop_after_three_retries(tmp_path: Path) -> None:
    calls = 0

    def fail(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("provider request timed out")

    with pytest.raises(RuntimeError, match="failed after 4 calls"):
        _replace(_proposer(fail, retries=5), tmp_path)

    assert calls == 4


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
    proposal = (
        tmp_path
        / "rubric-generations"
        / "generation-0001"
        / "rubric-proposal.json"
    )
    proposal.chmod(0o600)
    proposal.write_text(json.dumps({"criteria": []}))
    with pytest.raises(RuntimeError, match="file hash changed"):
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
            original_rubric=_rubric(),
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
            current_generation=_initial_generation(),
            policy=RubricPolicy.OFFLINE_ELICITATION,
            generation_round=True,
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
            current_generation=_initial_generation(),
            policy=RubricPolicy.ONLINE_ELICITATION,
            generation_round=1,
            source_checkpoint=1,
            output_dir=tmp_path / "online",
            artifact_history=_history(),
        )
