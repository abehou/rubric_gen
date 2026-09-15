"""Provider-free checks for the task-required RTT candidate."""

import json
from types import SimpleNamespace

import pytest

from rubric_gen.submission_revision import trace_defense_v2_prompts as legacy_prompts
from rubric_gen.submission_revision import task_paraphrase_required_prompts as prompts
from rubric_gen.submission_revision import task_paraphrase_required_completion_prompts as completion_prompts
from rubric_gen.submission_revision import task_paraphrase_required_completion_pass_prompts as completion_pass_prompts
from rubric_gen.submission_revision import task_paraphrase_required_schema as schema
from rubric_gen.submission_revision.rubric_generation import ElicitedCriterion
from rubric_gen.submission_revision.task_paraphrase_required import (
    TASK_REQUIRED_PREFIX,
    criterion_obligation_mode,
    render_task_required_rubric,
)
from rubric_gen.submission_revision.task_paraphrase_required_stage import TraceStagesV2
from rubric_gen.submission_revision.trace_defense_registry import recipe, prompt_hashes
from test_rubric_evolution import _development_rubric, _rubric


VERSION = "attack_defense_v2.1_task_paraphrase_required"
COMPLETION_VERSION = "attack_defense_v2.1_task_paraphrase_required_completion"
COMPLETION_PASS_VERSION = "attack_defense_v2.1_task_paraphrase_required_completion_pass"


def _proposer(version=VERSION):
    contract = SimpleNamespace(record=lambda: {"model": "stub"})
    return SimpleNamespace(red_team_trace_version=version, max_retries=0,
                           proposer_contract=contract)


def _criterion(requirement):
    return ElicitedCriterion.create(
        title="A task-level public check",
        requirement=requirement,
        levels=(("A", 0, "Pass."), ("B", -5, "Failure."), ("C", -10, "Material failure.")),
        provenance_pair_ids=("pair_" + "1" * 16,), source_generation=2,
    )


def test_new_recipe_and_legacy_unrelated_prompts_are_separate():
    assert recipe(VERSION).learning_module == "task_paraphrase_required"
    for name in ("attack", "quality", "rubric_view", "application", "locator_repair", "corrective", "anticipatory"):
        assert prompt_hashes("attack_defense_v2.1")[name] == prompt_hashes(VERSION)[name]
    assert prompt_hashes(VERSION)["diagnosis"] != prompt_hashes("attack_defense_v2.1")["diagnosis"]
    assert prompt_hashes(VERSION)["compilation"] != prompt_hashes("attack_defense_v2.1")["compilation"]
    assert prompt_hashes(VERSION)["semantic"] != prompt_hashes("attack_defense_v2.1")["semantic"]


def test_actual_stage_dispatch_uses_new_prompt_and_contract_identity():
    validator = schema.ResponseContract("diagnosis", schema.diagnosis_schema((), {
        "preferred": SimpleNamespace(source_id="preferred", lines=("x",), content_sha256="0" * 64),
        "rejected": SimpleNamespace(source_id="rejected", lines=("x",), content_sha256="0" * 64),
    }))
    request = TraceStagesV2(_proposer(), ".").request("diagnosis", {"task": "x"}, validator)
    assert request["prompt_version"] == prompts.PROMPT_VERSION
    assert request["prompt"] == prompts.STAGES["diagnosis"]
    assert request["prompt"] != legacy_prompts.STAGES["diagnosis"]
    assert request["response_contract"]["schema_version"] == schema.SCHEMA_VERSION


def test_task_required_mode_is_explicit_and_not_applicable_is_not_legal():
    docs = {"artifact": SimpleNamespace(source_id="artifact", lines=("x",), content_sha256="0" * 64)}
    contract = schema.ResponseContract("application", schema.application_schema(("A", "B", "C"), docs,
                                                                                   obligation_mode="task_required"),
                                       docs, {"artifact": "artifact"}, labels=("A", "B", "C"))
    response = {"applicability": "not_applicable", "public_refs": [], "check": "none", "level": "A",
                "reason": "no claim"}
    with pytest.raises(ValueError):
        contract.validate(response)


def test_task_required_renderer_changes_only_task_required_scope():
    base = _rubric()
    claim = _criterion("When a result is claimed, check its displayed support.")
    task = _criterion(TASK_REQUIRED_PREFIX + "Report the explicitly requested result and support it.")
    assert criterion_obligation_mode(claim) == "claim_conditional"
    assert criterion_obligation_mode(task) == "task_required"
    assert render_task_required_rubric(base, (claim,)) == __import__(
        "rubric_gen.submission_revision.rubric_generation", fromlist=["render_augmented_rubric"]
    ).render_augmented_rubric(base, (claim,))
    rendered = render_task_required_rubric(base, (task,)).content
    assert "Task-required obligation" in rendered
    assert "omission of the explicitly required" in rendered
    assert "No covered claim is made, or the check passes" not in rendered


def test_candidate_guidance_requires_mode_and_preserves_task_specificity():
    assert "obligation_mode" in prompts.DIAGNOSIS_V2
    assert "claim_conditional" in prompts.COMPILATION_V2
    assert "task_required" in prompts.SEMANTIC_V2
    assert "hidden target" in prompts.TASK_REQUIRED_GUIDANCE
    assert _development_rubric().content != _rubric().content


def test_candidate_request_does_not_introduce_heldout_context():
    text = json.dumps({"diagnosis": prompts.DIAGNOSIS_V2, "compilation": prompts.COMPILATION_V2,
                       "semantic": prompts.SEMANTIC_V2}).lower()
    assert "heldout rubric text" in text
    assert "outcome-heldout" not in text


def test_completion_revision_changes_only_diagnosis_prompt_identity():
    assert recipe(COMPLETION_VERSION).learning_module == "task_paraphrase_required"
    assert completion_prompts.PROMPT_VERSION == COMPLETION_VERSION
    assert completion_prompts.STAGES["diagnosis"] != prompts.STAGES["diagnosis"]
    for name in ("quality", "rubric_view", "compilation", "semantic", "application", "attack",
                 "locator_repair", "corrective", "anticipatory"):
        left = completion_prompts.prompt_hashes()[name]
        right = prompts.prompt_hashes()[name]
        assert left == right, name
    assert "preliminary" in completion_prompts.DIAGNOSIS_V2
    assert "NO_SUPPORTED_RELATION" in completion_prompts.DIAGNOSIS_V2


def test_completion_stage_dispatch_is_version_scoped():
    validator = schema.ResponseContract("diagnosis", schema.diagnosis_schema((), {
        "preferred": SimpleNamespace(source_id="preferred", lines=("x",), content_sha256="0" * 64),
        "rejected": SimpleNamespace(source_id="rejected", lines=("x",), content_sha256="0" * 64),
    }))
    request = TraceStagesV2(_proposer(COMPLETION_VERSION), ".").request("diagnosis", {"task": "x"}, validator)
    assert request["prompt_version"] == COMPLETION_VERSION
    assert request["prompt"] == completion_prompts.DIAGNOSIS_V2
    assert request["prompt"] != prompts.DIAGNOSIS_V2


def test_completion_pass_revision_changes_only_task_required_pass_stages():
    assert recipe(COMPLETION_PASS_VERSION).learning_module == "task_paraphrase_required"
    assert completion_pass_prompts.PROMPT_VERSION == COMPLETION_PASS_VERSION
    for name in ("attack", "quality", "rubric_view", "diagnosis", "locator_repair",
                 "corrective", "anticipatory"):
        assert completion_pass_prompts.prompt_hashes()[name] == completion_prompts.prompt_hashes()[name], name
    for name in ("compilation", "semantic", "application"):
        assert completion_pass_prompts.prompt_hashes()[name] != completion_prompts.prompt_hashes()[name], name
    guidance = completion_pass_prompts.TASK_REQUIRED_PASS_GUIDANCE
    assert "actually performed" in guidance
    assert "applicable non-A failure" in guidance
    assert "zero, negative, or non-estimable result may pass" in guidance
    assert "does not change claim_conditional criteria" in guidance


def test_completion_pass_actual_stage_dispatch_uses_versioned_instructions():
    docs = {
        "artifact": SimpleNamespace(source_id="artifact", lines=("x",), content_sha256="0" * 64),
    }
    validator = schema.ResponseContract(
        "application",
        schema.application_schema(("A", "B", "C"), docs, obligation_mode="task_required"),
        docs,
        {"artifact": "artifact"},
        labels=("A", "B", "C"),
    )
    request = TraceStagesV2(_proposer(COMPLETION_PASS_VERSION), ".").request(
        "application", {"task": "x"}, validator
    )
    assert request["prompt_version"] == COMPLETION_PASS_VERSION
    assert request["prompt"] == completion_pass_prompts.APPLICATION_V2
    assert "non-A level" in request["prompt"]
    assert request["schema"]["properties"]["applicability"]["enum"] == ["applicable", "undecidable"]


def test_completion_pass_preserves_legacy_and_parent_request_identity():
    assert prompt_hashes("attack_defense_v2.1") == legacy_prompts.prompt_hashes()
    assert prompt_hashes(COMPLETION_VERSION) == completion_prompts.prompt_hashes()
    assert completion_pass_prompts.DIAGNOSIS_V2 == completion_prompts.DIAGNOSIS_V2
    assert completion_pass_prompts.ATTACK_V2 == completion_prompts.ATTACK_V2
