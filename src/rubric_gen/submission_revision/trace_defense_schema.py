"""Self-contained response schemas and deterministic source binding."""
from .trace_defense_attack import quote_offsets

TEXT = {'type': 'string'}
BOOL = {'type': 'boolean'}

def obj(**properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}

def enum(values):
    return {'type': 'string', **({'enum': list(values)} if values else {})}

def array(items, **bounds):
    return {'type': 'array', 'items': items, **bounds}

def evidence(ids):
    return obj(artifact_id=enum(ids), quote=TEXT)

def quality_schema(ids):
    return obj(artifact_assessments=obj(**{i: TEXT for i in ids}),
               decisive_evidence=array(evidence(ids)),
               preferred_artifact_id={'type': ['string', 'null'], 'enum': [*ids, None]}, reason=TEXT)

def view_schema(artifact_id, generation):
    labels = sorted({l for c in generation.elicited_criteria for l, _, _ in c.levels})
    return obj(artifact_id=enum([artifact_id]),
               base_score={'type': 'integer', 'minimum': 0, 'maximum': generation.normalization_maximum},
               criterion_levels=array(obj(criterion_id=enum([c.criterion_id for c in generation.elicited_criteria]),
                                          level=enum(labels)),
                                      minItems=len(generation.elicited_criteria), maxItems=len(generation.elicited_criteria)),
               reason=TEXT)

def diagnosis_schema(pair, generation):
    return obj(status=enum(['supported_relation', 'no_supported_relation', 'preference_conflict']),
               pair_id=enum([pair.pair_id]),
               preferred_evidence=array(evidence([pair.preferred_artifact_id])),
               rejected_evidence=array(evidence([pair.rejected_artifact_id])),
               relation=TEXT, shared_defects_not_explained=TEXT,
               gap_cause=enum(['missing_coverage','refine_existing']),
               replaces=array(enum([c.criterion_id for c in generation.elicited_criteria])), corrective_check=TEXT)

def compilation_schema(labels, pair, generation):
    from .evolution_protocol import induction_schema
    schema = induction_schema(labels, (pair,), generation)
    schema['properties']['criteria']['maxItems'] = 1
    item = schema['properties']['criteria']['items']['properties']
    item['requirement']['maxLength'] = 650
    item['levels']['items']['properties']['description']['maxLength'] = 500
    item['provenance_pair_ids']['maxItems'] = 1
    schema['properties']['predicted_levels'] = {'anyOf': [obj(preferred=enum(labels), rejected=enum(labels)), {'type':'null'}]}
    schema['properties']['explanation'] = TEXT
    schema['required'] += ['predicted_levels','explanation']
    return schema

def semantic_schema():
    return obj(observable=BOOL, nonredundant=BOOL, reason=TEXT)

def application_schema(artifact_id, labels):
    return obj(applicability=enum(['applicable','not_applicable','undecidable']),
               public_evidence=array(evidence([artifact_id])), check=TEXT,
               level={'type':['string','null'], 'enum':[*labels,None]}, reason=TEXT)

def bind_quotes(items, artifacts, *, required_ids=()):
    """Reject wrong IDs and quotation attribution; do not repair model judgments."""
    resolved, errors = [], []
    for item in items:
        identity, quote = item.get('artifact_id'), item.get('quote')
        offsets = quote_offsets(quote, artifacts.get(identity, ''))
        if identity not in artifacts or not offsets:
            errors.append({'artifact_id': identity, 'quote': quote, 'reason':'quote_not_in_named_artifact'})
        else:
            resolved.append({**item, 'offsets': offsets})
    for identity in required_ids:
        if not any(x['artifact_id'] == identity for x in resolved):
            errors.append({'artifact_id': identity, 'reason':'missing_required_public_witness'})
    return resolved, errors

def criterion_public(criterion):
    return {'title': criterion.title, 'requirement': criterion.requirement,
            'levels': [{'label': l, 'points': p, 'description': d} for l,p,d in criterion.levels]}
