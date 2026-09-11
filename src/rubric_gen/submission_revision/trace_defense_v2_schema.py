"""Strict v2 schemas and deterministic response contracts, before cache validity."""
from dataclasses import dataclass, field
from typing import Any
import jsonschema
from .trace_defense_evidence_v2 import (
    PublicDocument, EvidenceContractError, references_schema, bind_references, allowed_actions,
    source_manifest, EVIDENCE_CONTRACT_VERSION,
)
from .trace_defense_schema import obj, array, TEXT, BOOL, criterion_public, view_schema, semantic_schema

SCHEMA_VERSION = 'trace-defense-v2-schema-1'
VALIDATION_VERSION = 'trace-defense-v2-validation-1'


def enum(values):
    values = list(values)
    if not values:
        raise ValueError('v2 enum must contain explicit legal values')
    return {'type': 'string', 'enum': values}


def quality_schema(ids, documents):
    if len(ids) != 2 or len(set(ids)) != 2:
        raise ValueError('quality requires two distinct actual artifact IDs')
    return obj(artifact_assessments=obj(artifact_A=TEXT, artifact_B=TEXT),
               decisive_refs=references_schema(documents),
               preferred_artifact_id={'type': ['string', 'null'], 'enum': [*ids, None]}, reason=TEXT)


def diagnosis_schema(active_ids, documents):
    return obj(action=enum(allowed_actions(active_ids)),
               preferred_refs=references_schema({k: v for k, v in documents.items() if k != 'rejected'}),
               rejected_refs=references_schema({k: v for k, v in documents.items() if k != 'preferred'}),
               relation=TEXT, trigger=TEXT, public_check=TEXT, shared_defects_not_explained=TEXT,
               corrective_action=TEXT, preserve_supported_work=TEXT, explanation=TEXT)


def compilation_schema(labels):
    return obj(criteria=array(obj(title=TEXT, requirement={'type': 'string', 'maxLength': 650},
                                  levels=array(obj(label=enum(labels), description={'type': 'string', 'maxLength': 500}),
                                               minItems=len(labels), maxItems=len(labels))), minItems=0, maxItems=1), reason=TEXT)


def application_schema(labels, documents):
    return obj(applicability=enum(['applicable', 'not_applicable', 'undecidable']),
               public_refs=references_schema(documents), check=TEXT,
               level={'type': ['string', 'null'], 'enum': [*labels, None]}, reason=TEXT)


@dataclass(frozen=True)
class ResponseContract:
    stage: str
    schema: dict
    documents: dict[str, PublicDocument] = field(default_factory=dict)
    native_ids: dict[str, str] = field(default_factory=dict)
    active_ids: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    generation: Any = None

    def identity(self):
        return {'schema_version': SCHEMA_VERSION, 'validation_version': VALIDATION_VERSION,
                'evidence_contract_version': EVIDENCE_CONTRACT_VERSION,
                'sources': source_manifest(self.documents, self.native_ids),
                'allowed_actions': list(allowed_actions(self.active_ids)) if self.stage == 'diagnosis' else [],
                'labels': list(self.labels)}

    def validate(self, value):
        """Returns recomputable bindings. No semantic verdict is changed."""
        errors = [{'field': '.'.join(map(str, e.absolute_path)) or '$', 'reason': e.message}
                  for e in jsonschema.Draft202012Validator(self.schema).iter_errors(value)]
        if errors:
            raise EvidenceContractError(errors)
        resolved = {}
        def refs(name, required=(), excluded=()):
            docs = {k: v for k, v in self.documents.items() if k not in excluded}
            try:
                resolved[name] = bind_references(value[name], docs, required_sources=required)
            except EvidenceContractError as exc:
                errors.extend({**e, 'field': e['field'].replace('references', name, 1)} for e in exc.errors)
        if self.stage == 'quality':
            refs('decisive_refs', ('artifact_A', 'artifact_B') if value['preferred_artifact_id'] else ())
        elif self.stage == 'diagnosis':
            supported = value['action'] not in {'NO_SUPPORTED_RELATION', 'PREFERENCE_CONFLICT'}
            refs('preferred_refs', ('preferred',) if supported else (), ('rejected',))
            refs('rejected_refs', ('rejected',) if supported else (), ('preferred',))
        elif self.stage == 'application':
            refs('public_refs', ('artifact',) if value['applicability'] == 'applicable' else ())
            if not self.application_combination_valid(value):
                errors.append({'field': 'applicability/level', 'reason': 'incoherent_applicability_level_combination'})
            if not value['reason'].strip() or not value['check'].strip():
                errors.append({'field': 'reason/check', 'reason': 'specific_explanation_required'})
        elif self.stage == 'compilation':
            from .evolution_artifacts import single_line
            for index, criterion in enumerate(value['criteria']):
                try:
                    single_line(criterion['requirement'], 'new criterion requirement', 650)
                    if tuple(x['label'] for x in criterion['levels']) != self.labels:
                        raise ValueError('criterion levels must follow supplied native order')
                    for level in criterion['levels']:
                        single_line(level['description'], 'new level description', 500)
                    single_line(criterion['title'], 'new criterion title')
                except ValueError as exc:
                    errors.append({'field': f'criteria[{index}]', 'reason': str(exc)})
        elif self.stage == 'rubric_view':
            from .trace_defense import _validate_view
            try:
                _validate_view(value, self.generation)
            except ValueError as exc:
                errors.append({'field': 'criterion_levels', 'reason': str(exc)})
        if errors:
            raise EvidenceContractError(errors)
        return resolved

    def application_combination_valid(self, value):
        return ((value.get('applicability') == 'applicable' and value.get('level') in self.labels)
                or (value.get('applicability') == 'not_applicable' and value.get('level') == self.labels[0])
                or (value.get('applicability') == 'undecidable' and value.get('level') is None))

    def repair_locks(self, value):
        """Only locator/illegal-action repairs with an otherwise valid scientific payload."""
        if not isinstance(value, dict) or set(value) != set(self.schema['properties']):
            return None
        editable = {'quality': ['decisive_refs'], 'diagnosis': ['preferred_refs', 'rejected_refs'],
                    'application': ['public_refs']}.get(self.stage)
        if editable is None:
            return None
        editable = list(editable)
        if self.stage == 'diagnosis' and value['action'] not in allowed_actions(self.active_ids):
            editable.append('action')
        if self.stage == 'application' and not self.application_combination_valid(value):
            return None
        for key, item in value.items():
            if key not in editable:
                if list(jsonschema.Draft202012Validator(self.schema['properties'][key]).iter_errors(item)):
                    return None
                if isinstance(item, str) and not item.strip():
                    return None
        return {'allowed_edit_fields': editable,
                'locked_fields': {k: v for k, v in value.items() if k not in editable}}
