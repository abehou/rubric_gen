"""Single-string hypothesis: tiny schema, complete judgments, no inferred rows."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from rubric_gen.submission_revision.evaluation import indexed_rubric as wire, rubric_judge as judge
from rubric_gen.submission_revision.judging.full_rubric_protocol import FullRubricJudgeError
from test_evaluation_rubric_judge import _many_criterion_rubric
from test_opus_block_strings import COUNTS, _records
from test_opus_cardinality import _keyed
from test_runtime_reliability import _wire, _strings, _text


CONTRACTS = [wire.V5_STRUCTURED_OUTPUT, wire.V6_STRUCTURED_OUTPUT,
             wire.V7_STRUCTURED_OUTPUT, wire.STRUCTURED_OUTPUT]


@pytest.mark.parametrize('count', COUNTS)
def test_v8_has_exactly_two_required_strings_and_equivalent_canonical_scores(count):
    items = [f'{i % 2}| evidence {i} | retain | the entire remainder ' for i in range(count)]
    value = _text(items)
    schema = wire.output_schema(count)
    # Exact equality excludes hidden schema expansion, arrays, refs and patterns.
    assert schema == {
        'type': 'object',
        'properties': {'criteria_text': {'type': 'string'},
                       'overall_reasoning': {'type': 'string'}},
        'required': ['criteria_text', 'overall_reasoning'],
        'additionalProperties': False,
    }
    assert schema == wire.output_schema(1) == wire.output_schema(872)
    assert wire.STRUCTURED_OUTPUT.endswith('-v8')
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    assert judge._anthropic_rubric_score_schema(schema) == schema
    fixtures = [_wire(items), _keyed(items), _strings(items), value]
    decoded = [wire.decode_output(json.dumps(v), count, contract=c)
               for v, c in zip(fixtures, CONTRACTS, strict=True)]
    assert all(result == decoded[0] for result in decoded)
    records = [_records(v, count, c) for v, c in zip(fixtures, CONTRACTS, strict=True)]
    for record in records[1:]:
        assert record.score == records[0].score
        assert record.evaluation['criteria'] == records[0].evaluation['criteria']
        assert record.evaluation['total_score'] == records[0].evaluation['total_score']
        assert record.evaluation['full_rubric_structured']['raw_report'] == (
            records[0].evaluation['full_rubric_structured']['raw_report'])


@pytest.mark.parametrize('count', COUNTS)
@pytest.mark.parametrize('damage', [
    'missing-row', 'extra-row', 'duplicate-index', 'reordered-index', 'wrong-global-index',
    'missing-global-index', 'negative-index', 'padded-index', 'nondecimal-index',
    'negative-level', 'noninteger-level', 'level-out-of-range', 'missing-level',
    'empty-reason', 'missing-separator', 'placeholder', 'leading-blank', 'interior-blank',
    'double-terminator', 'empty-overall', 'nonstring-overall', 'nonstring-criteria',
])
def test_v8_rejects_incomplete_or_invalid_rows_without_imputation(count, damage):
    value = _text(['0|evidence'] * count)
    lines = value['criteria_text'].splitlines()
    if damage == 'missing-row':
        lines.pop()
    elif damage == 'extra-row':
        lines.append(f'{count}|0|extra')
    elif damage == 'duplicate-index':
        if count > 1:
            lines[-1] = lines[0]
        else:
            lines.append(lines[0])
    elif damage == 'reordered-index':
        if count > 1:
            lines[0], lines[-1] = lines[-1], lines[0]
        else:
            lines[0] = '1|0|evidence'
    elif damage == 'leading-blank':
        lines.insert(0, '')
    elif damage == 'interior-blank':
        lines.insert(count // 2, '')
    elif damage == 'double-terminator':
        lines.extend(['', ''])
    elif damage == 'empty-overall':
        value['overall_reasoning'] = ' \n '
    elif damage == 'nonstring-overall':
        value['overall_reasoning'] = []
    elif damage != 'nonstring-criteria':
        lines[0] = {
            'wrong-global-index': '999|0|evidence',
            'missing-global-index': '|0|evidence',
            'negative-index': '-1|0|evidence',
            'padded-index': '00|0|evidence',
            'nondecimal-index': 'zero|0|evidence',
            'negative-level': '0|-1|evidence',
            'noninteger-level': '0|false|evidence',
            'level-out-of-range': '0|2|evidence',
            'missing-level': '0||evidence',
            'empty-reason': '0|0| \t ',
            'missing-separator': '0|0',
            'placeholder': 'x',
        }[damage]
    value['criteria_text'] = [] if damage == 'nonstring-criteria' else '\n'.join(lines)
    with pytest.raises(FullRubricJudgeError):
        _records(value, count, wire.STRUCTURED_OUTPUT)


@pytest.mark.parametrize('damage', ['missing-text', 'missing-overall', 'extra-key', 'v7-container'])
def test_v8_schema_and_decoder_reject_wrong_top_level_members(damage):
    value = _text(['0|evidence'] * 67)
    if damage == 'missing-text':
        del value['criteria_text']
    elif damage == 'missing-overall':
        del value['overall_reasoning']
    elif damage == 'extra-key':
        value['extra'] = ''
    else:
        value = _strings(['0|evidence'] * 67)
    with pytest.raises(ValidationError):
        Draft202012Validator(wire.output_schema(67)).validate(value)
    with pytest.raises(FullRubricJudgeError, match='top-level keys'):
        wire.decode_output(json.dumps(value), 67)


@pytest.mark.parametrize('key', ['criteria_text', 'overall_reasoning'])
def test_v8_rejects_duplicate_json_keys_even_when_values_are_identical(key):
    text = json.dumps(_text(['0|reason']))
    field = json.dumps(key) + ': ' + json.dumps(json.loads(text)[key])
    text = text.replace(field, field + ', ' + field)
    with pytest.raises(FullRubricJudgeError, match='duplicate JSON key'):
        wire.decode_output(text, 1)


@pytest.mark.parametrize('ending', ['\n', '\r\n'])
def test_v8_accepts_one_terminal_line_ending_and_preserves_reason_bytes(ending):
    value = _text(['0| reason | with | pipes '] * 67)
    terminated = deepcopy(value)
    terminated['criteria_text'] += ending
    assert wire.decode_output(json.dumps(terminated), 67) == wire.decode_output(json.dumps(value), 67)
    assert json.loads(wire.decode_output(json.dumps(terminated), 67))['criteria'][0]['reason'] == (
        ' reason | with | pipes ')


def test_v7_observed_64_of_306_omission_is_not_salvageable_as_v8():
    # Observed shape: 0..63 present, three empty blocks, a literal x tail.
    # Synthetic reasons avoid storing provider evidence in the test suite.
    observed = _strings(['0|evidence'] * 306)
    for i in (1, 2, 3):
        observed['criteria'][f'block_{i}'] = ''
    observed['criteria']['tail'] = 'x'
    Draft202012Validator(wire.output_schema(306, contract=wire.V7_STRUCTURED_OUTPUT)).validate(observed)
    with pytest.raises(FullRubricJudgeError, match='block_1 must contain exactly 64'):
        wire.decode_output(json.dumps(observed), 306, contract=wire.V7_STRUCTURED_OUTPUT)
    for suffix in ('', '\nx'):
        incomplete = dict(criteria_text=observed['criteria']['block_0'] + suffix,
                          overall_reasoning=observed['overall_reasoning'])
        Draft202012Validator(wire.output_schema(306)).validate(incomplete)
        with pytest.raises(FullRubricJudgeError, match='exactly 306 criterion lines'):
            wire.decode_output(json.dumps(incomplete), 306)


@pytest.mark.parametrize('count', [306, 872])
def test_v8_changes_only_wire_settings_and_format_instructions(count):
    specs = [judge.build_rubric_score_run_spec(
        rubric_text=_many_criterion_rubric(count), review_text='unchanged artifact evidence',
        answer_text='unchanged answer', requested_model='claude-opus-5', seed=17,
        indexed_contract=contract) for contract in CONTRACTS]
    wire_fields = {'structured_output_contract', 'system_prompt_sha256', 'schema_bytes',
                   'request_content_bytes_per_call', 'total_request_content_bytes'}
    semantic = [{k: v for k, v in spec.as_json().items() if k not in wire_fields} for spec in specs]
    assert all(value == semantic[0] for value in semantic)
    assert all(judge._request_parameters(spec) == judge._request_parameters(specs[0]) for spec in specs)
    for contract in CONTRACTS:
        assert judge._system_prompt('anthropic', contract).replace(
            wire.format_instructions(contract), wire.ARRAY_FORMAT) == judge.RUBRIC_SCORE_SYSTEM_PROMPT
