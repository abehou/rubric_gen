"""Explicit trace recipe dispatch. Historical prompt modules remain immutable."""
from dataclasses import dataclass
from importlib import import_module

SOURCE_SCHEDULE = 'pre_revision_v1'


@dataclass(frozen=True)
class TraceRecipe:
    family: str
    prompts_module: str
    learning_module: str
    attack_module: str
    attack_record_name: str

    @property
    def prompts(self):
        return import_module('.'+self.prompts_module, __package__)

    def elicit(self, **kwargs):
        return import_module('.'+self.learning_module, __package__).elicit_trace_defense(**kwargs)

    def attack_record(self, *args, version):
        operation = import_module('.'+self.attack_module, __package__).attack_record
        return operation(*args) if self.family == 'v1' else operation(*args, version=version)


_V1 = TraceRecipe('v1', 'trace_defense_prompts', 'trace_defense', 'trace_defense_attack', 'attack-record.json')
_V2 = TraceRecipe('v2', 'trace_defense_v2_prompts', 'trace_defense_v2', 'trace_defense_v2_attack', 'attack-record-v2.json')
_V21 = TraceRecipe('v2', 'trace_defense_v2_prompts', 'trace_defense_v21', 'trace_defense_v2_attack', 'attack-record-v2.json')
# The task/paraphrase candidate keeps the v2.1 attack and native contracts but
# dispatches its learning stages through an opt-in module with explicit
# selected/development rubric context.
_V21_TASK_PARAPHRASE = TraceRecipe(
    'v2', 'task_paraphrase_prompts', 'task_paraphrase_grounded',
    'trace_defense_v2_attack', 'attack-record-v2.json')
# This opt-in descendant adds only the explicit obligation-mode contract to the
# task/paraphrase-grounded learner.  Legacy v2.1 and the prior candidate remain
# separate recipes and are never rewritten.
_V21_TASK_REQUIRED = TraceRecipe(
    'v2', 'task_paraphrase_required_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
# One diagnosis-only follow-up.  Every other stage remains the preceding
# task-required implementation; the distinct prompt module preserves request
# identity for the new scientific recipe.
_V21_TASK_REQUIRED_COMPLETION = TraceRecipe(
    'v2', 'task_paraphrase_required_completion_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_TASK_REQUIRED_COMPLETION_PASS = TraceRecipe(
    'v2', 'task_paraphrase_required_completion_pass_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
# The next development candidate preserves the task-required pairwise learner
# and adds one absolute, execution-grounded enforcement review per checkpoint.
_V21_TASK_REQUIRED_ENFORCED = TraceRecipe(
    'v2', 'task_required_enforced_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY = TraceRecipe(
    'v2', 'task_required_enforced_requirement_only_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_SOURCE_BOUND = TraceRecipe(
    'v2', 'task_required_enforced_requirement_only_source_bound_prompts',
    'task_paraphrase_required', 'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_WITNESS_FROZEN = TraceRecipe(
    'v2', 'task_required_enforced_requirement_only_witness_frozen_prompts',
    'task_paraphrase_required', 'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_DURABLE = TraceRecipe(
    'v2', 'task_required_enforced_requirement_only_durable_prompts',
    'task_paraphrase_required', 'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_DURABLE_DELIVERY = TraceRecipe(
    'v2', 'task_required_enforced_requirement_only_durable_delivery_prompts',
    'task_paraphrase_required', 'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_EXECUTION_VERIFIED = TraceRecipe(
    'v2', 'execution_verified_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_EXECUTION_VERIFIED_PROACTIVE = TraceRecipe(
    'v2', 'execution_verified_proactive_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
_V21_EXECUTION_VERIFIED_PROACTIVE_PROVENANCE = TraceRecipe(
    'v2', 'execution_verified_provenance_prompts', 'task_paraphrase_required',
    'trace_defense_v2_attack', 'attack-record-v2.json')
# v3 keeps the complete v2.1 attack/learning path.  Its only scientific
# difference is the User-simulator delivery adapter, selected in controller
# scoring; the learning recipe remains the pinned v2.1 implementation.
_V3 = TraceRecipe('v2', 'trace_defense_v2_prompts', 'trace_defense_v21', 'trace_defense_v2_attack', 'attack-record-v2.json')
RECIPES = {
    'attack_defense_v1': _V1,
    'attack_defense_v2.dev1': _V2,
    'attack_defense_v2.dev2': _V2,
    'attack_defense_v2': _V2,
    'attack_defense_v2.1': _V21,
    'attack_defense_v2.1_task_paraphrase_grounded': _V21_TASK_PARAPHRASE,
    'attack_defense_v2.1_task_paraphrase_required': _V21_TASK_REQUIRED,
    'attack_defense_v2.1_task_paraphrase_required_completion': _V21_TASK_REQUIRED_COMPLETION,
    'attack_defense_v2.1_task_paraphrase_required_completion_pass': _V21_TASK_REQUIRED_COMPLETION_PASS,
    'attack_defense_v2.1_task_paraphrase_required_enforced': _V21_TASK_REQUIRED_ENFORCED,
    'attack_defense_v2.1_task_paraphrase_required_enforced_requirement_only': _V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY,
    'attack_defense_v2.1_task_paraphrase_required_enforced_requirement_only_source_bound': _V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_SOURCE_BOUND,
    'attack_defense_v2.1_task_paraphrase_required_enforced_requirement_only_witness_frozen': _V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_WITNESS_FROZEN,
    'attack_defense_v2.1_task_paraphrase_required_enforced_requirement_only_durable': _V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_DURABLE,
    'attack_defense_v2.1_task_paraphrase_required_enforced_requirement_only_durable_delivery': _V21_TASK_REQUIRED_ENFORCED_REQUIREMENT_ONLY_DURABLE_DELIVERY,
    'attack_defense_v2.1_execution_verified': _V21_EXECUTION_VERIFIED,
    'attack_defense_v2.1_execution_verified_proactive': _V21_EXECUTION_VERIFIED_PROACTIVE,
    'attack_defense_v2.1_execution_verified_proactive_provenance': _V21_EXECUTION_VERIFIED_PROACTIVE_PROVENANCE,
    'attack_defense_v2.1_corrective_appendix': _V21,
    'attack_defense_v2.1_no_appendix': _V21,
    'attack_defense_v2.1_score_only_no_appendix': _V21,
    'attack_defense_v3': _V3,
    # v3.1 is the same v2.1 learner and attack recipe.  Its only additional
    # behavior is the deterministic User-delivery guard documented in the v3
    # dev iteration report; the version keeps request/replay identities apart.
    'attack_defense_v3.1': _V3,
    'attack_defense_v3.2': _V3,
    'attack_defense_user_d1g0': _V21,
    'attack_defense_user_d0g1': _V21,
    'attack_defense_user_d1g1': _V21,
    'attack_defense_user_public_p1': _V21,
    'attack_defense_user_public_p2': _V21,
}


def validate_version(value):
    if value is not None and (not isinstance(value, str) or value not in RECIPES):
        raise ValueError(f'unknown red_team_trace_version: {value!r}')


def recipe(version):
    validate_version(version)
    if version is None:
        raise ValueError('a trace recipe requires an explicit version')
    return RECIPES[version]


def enabled(policy, version):
    from .rubric_generation import RubricPolicy
    validate_version(version)
    return RubricPolicy(policy) is RubricPolicy.RED_TEAM_TRACE and version is not None


def prompt_hashes(version):
    return recipe(version).prompts.prompt_hashes()
