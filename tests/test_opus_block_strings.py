"""Small provider schema, strict local cardinality, and historical score equivalence."""
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from rubric_gen.submission_revision.evaluation import indexed_rubric as wire, rubric_judge as judge
from rubric_gen.submission_revision.judging.full_rubric_protocol import FullRubricGeneration, FullRubricJudgeError
from test_evaluation_rubric_judge import _many_criterion_rubric
from test_runtime_reliability import _wire, _strings
from test_opus_cardinality import _keyed

COUNTS = [1, 63, 64, 67, 86, 92, 120, 145, 178, 255, 306, 403, 872]


def _records(value, count, contract=wire.V7_STRUCTURED_OUTPUT):
    rubric = _many_criterion_rubric(count).replace('A=1 B=0', 'A=2 B=-1')
    spec = judge.build_rubric_score_run_spec(rubric_text=rubric, review_text='unchanged evidence',
        answer_text='', requested_model='claude-opus-5', seed=17, indexed_contract=contract)
    generation = FullRubricGeneration(text=json.dumps(value), provider=spec.provider,
        requested_model=spec.requested_model, effective_model=spec.requested_model,
        response_id='fixture', request_parameters=judge._request_parameters(spec), usage={})
    return judge._records_from_generation(spec, generation, rubric_text=rubric)


@pytest.mark.parametrize('count', COUNTS)
def test_v7_tiny_schema_exact_complete_output_and_canonical_equivalence(count):
    items = [f'{i%2}|evidence for criterion {i} | entire remainder preserved' for i in range(count)]
    value = _strings(items)
    schema = wire.output_schema(count, contract=wire.V7_STRUCTURED_OUTPUT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    assert judge._anthropic_rubric_score_schema(schema) == schema
    assert set(schema) == {'type','properties','required','additionalProperties'}
    assert schema['type']=='object' and schema['additionalProperties'] is False
    assert set(schema['required']) == {'criteria','overall_reasoning'}
    criteria = schema['properties']['criteria']
    assert criteria['type']=='object' and criteria['additionalProperties'] is False
    assert criteria['required'] == list(value['criteria'])
    assert criteria['properties'] == {key:{'type':'string'} for key in value['criteria']}
    assert schema['properties']['overall_reasoning']=={'type':'string'}
    decoded = wire.decode_output(json.dumps(value), count, contract=wire.V7_STRUCTURED_OUTPUT)
    old = wire.decode_output(json.dumps(_wire(items)), count, contract=wire.V5_STRUCTURED_OUTPUT)
    v6 = wire.decode_output(json.dumps(_keyed(items)), count, contract=wire.V6_STRUCTURED_OUTPUT)
    assert decoded == old == v6
    records = [_records(v,count,c) for v,c in [(value,wire.V7_STRUCTURED_OUTPUT),
        (_wire(items),wire.V5_STRUCTURED_OUTPUT),(_keyed(items),wire.V6_STRUCTURED_OUTPUT)]]
    assert records[0].score == records[1].score == records[2].score
    assert records[0].evaluation['criteria'] == records[1].evaluation['criteria'] == records[2].evaluation['criteria']
    assert records[0].evaluation['total_score'] == records[1].evaluation['total_score'] == records[2].evaluation['total_score']


@pytest.mark.parametrize('count', COUNTS)
@pytest.mark.parametrize('damage', ['missing-block','extra-block','missing-line','duplicate-line',
    'reordered','wrong-global-index','extra-index','negative-level','noninteger-level',
    'level-out-of-range','empty-reason','empty-overall','nonstring-block'])
def test_v7_never_repairs_incomplete_or_ambiguous_judgments(count, damage):
    value = _strings(['0|evidence'] * count)
    blocks=value['criteria']; key=next(iter(blocks)); lines=blocks[key].split('\n')
    if damage=='missing-block': del blocks[key]
    elif damage=='extra-block': blocks['block_extra']='0|0|evidence'
    elif damage=='missing-line': blocks[key]='\n'.join(lines[1:])
    elif damage=='duplicate-line':
        lines[-1]=lines[0] if len(lines)>1 else '0|0|evidence\n0|0|evidence'
        blocks[key]='\n'.join(lines)
    elif damage=='reordered':
        if len(lines)>1: lines[0],lines[1]=lines[1],lines[0]
        else: lines[0]='1|0|evidence'
        blocks[key]='\n'.join(lines)
    elif damage=='extra-index': blocks[key]+='\n999|0|extra'
    elif damage=='empty-overall': value['overall_reasoning']=' \n '
    elif damage=='nonstring-block': blocks[key]=[]
    else:
        lines[0]={'wrong-global-index':'999|0|evidence','negative-level':'0|-1|evidence',
                  'noninteger-level':'0|false|evidence','level-out-of-range':'0|2|evidence',
                  'empty-reason':'0|0|   '}[damage]
        blocks[key]='\n'.join(lines)
    with pytest.raises(FullRubricJudgeError):
        _records(value,count)


@pytest.mark.parametrize('bad', ['|0|reason','01|0|reason','+0|0|reason','0|01|reason',
    '0|0','0|0|','0|0| \t','\n0|0|reason','0|0|reason\n\n'])
def test_v7_indices_and_lines_must_be_explicit(bad):
    with pytest.raises(FullRubricJudgeError):
        _records({'criteria':{'tail':bad},'overall_reasoning':'overall'},1)


def test_v7_duplicate_json_key_fails_before_object_collapse():
    with pytest.raises(FullRubricJudgeError, match='duplicate JSON key'):
        wire.decode_output('{"criteria":{"tail":"0|0|a","tail":"0|0|a"},"overall_reasoning":"x"}',1,contract=wire.V7_STRUCTURED_OUTPUT)


def test_sol_schema_payload_and_system_instructions_are_wire_version_independent():
    rubric=_many_criterion_rubric(67)
    specs=[]
    for contract in [wire.V5_STRUCTURED_OUTPUT,wire.V6_STRUCTURED_OUTPUT,wire.V7_STRUCTURED_OUTPUT,wire.STRUCTURED_OUTPUT]:
        spec=judge.build_rubric_score_run_spec(rubric_text=rubric,review_text='evidence',answer_text='',
            requested_model='gpt-5.6-sol',seed=4,indexed_contract=contract)
        specs.append(spec.as_json())
        assert judge._system_prompt('openai',contract)==judge.RUBRIC_SCORE_SYSTEM_PROMPT
        assert judge.rubric_score_output_schema(67,2,provider='openai',indexed_contract=contract)==judge.rubric_score_output_schema(67,2,provider='openai')
    assert specs[0]==specs[1]==specs[2]==specs[3]


def test_single_terminal_line_ending_does_not_change_canonical_judgment():
    value=_strings(['0|reason']*67)
    with_terminators=deepcopy(value)
    for key in with_terminators['criteria']:
        with_terminators['criteria'][key]+='\n'
    assert wire.decode_output(json.dumps(with_terminators),67,contract=wire.V7_STRUCTURED_OUTPUT)==wire.decode_output(json.dumps(value),67,contract=wire.V7_STRUCTURED_OUTPUT)
