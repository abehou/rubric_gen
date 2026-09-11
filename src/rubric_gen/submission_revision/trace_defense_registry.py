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
RECIPES = {'attack_defense_v1': _V1, 'attack_defense_v2.dev1': _V2, 'attack_defense_v2.dev2': _V2, 'attack_defense_v2': _V2}


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
