"""Validated v5 single-call representation; independent of benchmark and scoring.

Factored from scripts/babel/paperbench_keyed_protocol.py validated in job 10392624.
Block order is explicit; leaf order is the original criterion-contract order.
"""

import json
import re

from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    FULL_RUBRIC_MAX_CRITERIA,
    FullRubricJudgeError,
)

STRUCTURED_OUTPUT = "indexed-64-leaf-blocks-fixed-tail-index-pipe-reason-v5"

ARRAY_FORMAT = '''Evaluate the complete artifact against every rubric criterion. Return one item in
the criteria array for each criterion_contracts item, in the same order. Array
position identifies the criterion. Set level_index to the matching level_options
index. Do not output criterion identifiers or level names. Do not omit or add
items.'''
INDEXED_FORMAT = '''Evaluate the complete artifact against every rubric criterion. Return one leaf
for each criterion_contracts item. The criteria.full_blocks array, when present,
must contain exactly one block for every allowed block_index. Block i covers
criterion_contracts positions 64*i through 64*i+63 (zero-based), in its values
tree. The criteria.tail tree, when present, covers the remaining items after all
full blocks. Follow each tree's required left/right branches; leaves in
left-before-right traversal order identify the criteria within that block or
tail. Do not repeat or omit a block. Each leaf value must be a string in the form
"level_index|reason": the matching level_options index as a decimal integer,
then a literal | separator, then the evidence-based reason. For example, "0|The
artifact contains the required implementation." Do not output criterion
identifiers or level names.
Do not omit or add entries.'''


def output_schema(criterion_count):
    """Provider enforces block sizes; local validation enforces exact block IDs."""
    if type(criterion_count) is not int or not 1 <= criterion_count <= FULL_RUBRIC_MAX_CRITERIA:
        raise FullRubricJudgeError("rubric-score criterion count is out of range")
    definitions = {}
    def subtree(count):
        name = f'leaves_{count}'
        if name not in definitions:
            if count == 1:
                definitions[name] = {'type': 'string'}
            else:
                properties = {'left': subtree(count // 2), 'right': subtree(count - count // 2)}
                definitions[name] = dict(type='object', properties=properties,
                    required=['left', 'right'], additionalProperties=False)
        return {'$ref': f'#/$defs/{name}'}
    full_count, tail_count = divmod(criterion_count, 64)
    criteria_properties = {}
    if full_count:
        criteria_properties['full_blocks'] = {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {'block_index': {'type': 'integer', 'enum': list(range(full_count))},
                               'values': subtree(64)},
                'required': ['block_index', 'values'],
                'additionalProperties': False,
            },
        }
    if tail_count:
        criteria_properties['tail'] = subtree(tail_count)
    return {
        'type': 'object',
        'properties': {
            'criteria': dict(type='object', properties=criteria_properties,
                required=list(criteria_properties), additionalProperties=False),
            'overall_reasoning': {'type': 'string'},
        },
        'required': ['criteria', 'overall_reasoning'],
        'additionalProperties': False,
        '$defs': definitions,
    }


def _unique_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise FullRubricJudgeError('keyed rubric output has a duplicate JSON key')
        value[key] = child
    return value


def decode_output(text, criterion_count):
    """Decode indexed blocks to the ordered records used by the canonical validator."""
    if type(text) is not str or not text.strip():
        raise FullRubricJudgeError('keyed rubric output is empty')
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise FullRubricJudgeError('keyed rubric output is not exact JSON') from exc
    if type(value) is not dict or set(value) != {'criteria', 'overall_reasoning'}:
        raise FullRubricJudgeError('keyed rubric output has invalid top-level keys')
    schema = output_schema(criterion_count)
    leaves = []
    def collect(node, branch):
        if '$ref' in branch:
            branch = schema['$defs'][branch['$ref'].rsplit('/', 1)[1]]
        if branch['type'] == 'string':
            leaves.append(node)
            return
        expected = branch['properties']
        if type(node) is not dict or set(node) != set(expected):
            raise FullRubricJudgeError('count-safe tree shape does not exactly match the rubric')
        for key, child_schema in expected.items():
            collect(node[key], child_schema)
    container = value['criteria']
    properties = schema['properties']['criteria']['properties']
    if type(container) is not dict or set(container) != set(properties):
        raise FullRubricJudgeError('count-safe block container does not exactly match the rubric')
    full_count, tail_count = divmod(criterion_count, 64)
    if full_count:
        blocks = container['full_blocks']
        if type(blocks) is not list or len(blocks) != full_count:
            raise FullRubricJudgeError('count-safe block count does not exactly match the rubric')
        indexed = {}
        for block in blocks:
            if type(block) is not dict or set(block) != {'block_index', 'values'}:
                raise FullRubricJudgeError('count-safe block has invalid keys')
            index = block['block_index']
            if type(index) is not int or index not in range(full_count) or index in indexed:
                raise FullRubricJudgeError('count-safe block index is invalid or duplicated')
            indexed[index] = block['values']
        assert set(indexed) == set(range(full_count))
        for index in range(full_count):
            collect(indexed[index], properties['full_blocks']['items']['properties']['values'])
    if tail_count:
        collect(container['tail'], properties['tail'])
    assert len(leaves) == criterion_count
    # This is a lossless wire-format conversion, not a count repair: all exact
    # leaves are mandatory, and the original level/reason checks still run.
    items = []
    for record in leaves:
        if type(record) is not str:
            raise FullRubricJudgeError('keyed criterion value must be an index|reason string')
        index, separator, reason = record.partition('|')
        if not separator or re.fullmatch(r'0|[1-9][0-9]*', index) is None:
            raise FullRubricJudgeError('keyed criterion has an invalid decimal level index')
        items.append(dict(level_index=int(index), reason=reason))
    ordered = dict(criteria=items, overall_reasoning=value['overall_reasoning'])
    return json.dumps(ordered, allow_nan=False)
