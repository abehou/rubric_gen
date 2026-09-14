"""Provider-free checks for the opt-in task/paraphrase-grounded RTT recipe."""

import json
from pathlib import Path
from types import SimpleNamespace

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.submission_revision import trace_defense_v2_prompts as legacy_prompts
from rubric_gen.submission_revision import task_paraphrase_prompts as candidate_prompts
from rubric_gen.submission_revision import trace_defense_v2_schema as schema
from rubric_gen.submission_revision.rubric_generation import ElicitedCriterion
from rubric_gen.submission_revision.trace_defense_registry import recipe, prompt_hashes
from rubric_gen.submission_revision.trace_defense_v2_stage import TraceStagesV2 as LegacyStages
from rubric_gen.submission_revision.task_paraphrase_stage import TraceStagesV2 as CandidateStages
from rubric_gen.submission_revision.task_paraphrase_grounded import (
    diagnosis_request,
    semantic_request,
)
from test_trace_attack_defense import history, current
from test_rubric_evolution import _development_rubric, _rubric


VERSION = "attack_defense_v2.1_task_paraphrase_grounded"


def _ref(source_id):
    return {"source_id": source_id, "start_line": 1, "end_line": 1}


def _stage_proposer(version):
    contract = SimpleNamespace(record=lambda: {"model": "stub"})
    return SimpleNamespace(red_team_trace_version=version, max_retries=0,
                           proposer_contract=contract)


def test_registry_and_unrelated_prompts_keep_v21_identity():
    assert recipe("attack_defense_v2.1").learning_module == "trace_defense_v21"
    assert recipe(VERSION).learning_module == "task_paraphrase_grounded"
    for name in ("attack", "quality", "rubric_view", "application", "locator_repair", "corrective", "anticipatory"):
        assert prompt_hashes("attack_defense_v2.1")[name] == prompt_hashes(VERSION)[name]
    assert prompt_hashes("attack_defense_v2.1")["diagnosis"] != prompt_hashes(VERSION)["diagnosis"]
    assert prompt_hashes("attack_defense_v2.1")["compilation"] != prompt_hashes(VERSION)["compilation"]
    assert prompt_hashes("attack_defense_v2.1")["semantic"] != prompt_hashes(VERSION)["semantic"]


def test_legacy_stage_file_and_requests_are_unchanged():
    assert sha256_file(Path("src/rubric_gen/submission_revision/trace_defense_v2_stage.py")) == \
        "d3936ae868cc501d1bee71e182ed7ab87dd1c813e838cafa20c52c32c7b3a7e3"
    contract = schema.ResponseContract("semantic", schema.semantic_schema())
    request = LegacyStages(_stage_proposer("attack_defense_v2.1"), ".").request("semantic", {"task": "x"}, contract)
    assert request["prompt"] == legacy_prompts.STAGES["semantic"]
    assert request["prompt_version"] == legacy_prompts.PROMPT_VERSION
    assert request["red_team_trace_version"] == "attack_defense_v2.1"


def test_candidate_stage_uses_actual_candidate_prompt_dispatch():
    contract = schema.ResponseContract("semantic", schema.semantic_schema())
    request = CandidateStages(_stage_proposer(VERSION), ".").request("semantic", {"task": "x"}, contract)
    assert request["prompt"] == candidate_prompts.STAGES["semantic"]
    assert request["prompt_sha256"] == candidate_prompts.prompt_hashes()["semantic"]
    assert request["prompt"] != legacy_prompts.STAGES["semantic"]
    assert request["prompt_version"] == candidate_prompts.PROMPT_VERSION
    assert "heldout" in request["prompt"].lower()


def test_candidate_learning_context_contains_selected_and_development_rubrics_only():
    h = history()
    artifacts = {a.artifact_id: a for a in h.artifacts}
    selected = _rubric()
    development = _development_rubric()
    evidence, contract = diagnosis_request(
        "Check arithmetic.", h.pairs[0], artifacts, selected, development,
        current(), (), (), h.red_team_model_records((h.pairs[0].pair_id,), include_trace=True))
    assert evidence["selected_base_rubric"] == selected.content
    assert evidence["development_base_rubric"] == development.content
    assert evidence["immutable_base_rubric"] == selected.content
    assert "heldout rubric" not in json.dumps(evidence).lower()
    assert contract.stage == "diagnosis"


def test_candidate_semantic_context_contains_both_views_and_no_private_comparison():
    selected = _rubric()
    development = _development_rubric()
    criterion = ElicitedCriterion.create(
        title="A public relation",
        requirement="When X is claimed, check its displayed support.",
        levels=(("A", 0, "Pass."), ("B", -5, "Moderate."), ("C", -10, "Material.")),
        provenance_pair_ids=("pair_" + "1" * 16,), source_generation=2)
    candidate = SimpleNamespace(criterion=criterion, replaces=())
    context = semantic_request("Task", selected, development, current(), (), (), candidate)
    assert context["selected_base_rubric"] == selected.content
    assert context["development_base_rubric"] == development.content
    assert "private_attack_evidence" not in context
    assert "comparison" not in context
    assert "proposed_criterion" in context


def test_only_learning_prompts_change():
    assert candidate_prompts.ATTACK_V2 == legacy_prompts.ATTACK_V2
    assert candidate_prompts.QUALITY_V2 == legacy_prompts.QUALITY_V2
    assert candidate_prompts.RUBRIC_VIEW == legacy_prompts.RUBRIC_VIEW
    assert candidate_prompts.APPLICATION_V2 == legacy_prompts.APPLICATION_V2
    assert candidate_prompts.LOCATOR_REPAIR_V2 == legacy_prompts.LOCATOR_REPAIR_V2
    assert "underlying task-level relation" in candidate_prompts.DIAGNOSIS_V2
    assert "concrete corrective action" in candidate_prompts.COMPILATION_V2
    assert "paraphrased" in candidate_prompts.SEMANTIC_V2
