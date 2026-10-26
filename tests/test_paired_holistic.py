from copy import deepcopy
import json

import pytest

from rubric_gen.submission_revision.evaluation.paired_holistic import (
    DIMENSIONS, build_request, summarize_orders, validate_verdict,
)


def verdict(a, b):
    def response(score):
        return {'dimensions': {d: {'score': 4, 'explanation': 'Dimension evidence.'}
                               for d in DIMENSIONS},
                'overall': {'score': score, 'explanation': 'Overall comparison.'}}
    return {'response_A': response(a), 'response_B': response(b)}


def test_reversal_unblinds_before_averaging_and_overall_is_independent():
    result = summarize_orders({'static_first': verdict(2, 6), 'rtt_first': verdict(4, 4)})
    assert result['static']['overall_0to10'] == 3
    assert result['rtt']['overall_0to10'] == 5
    assert result['static']['A'] == 30
    assert result['rtt']['A'] == 50
    assert result['preference'] == 'rtt'
    assert result['static']['dimensions_0to10']['completeness'] == 4


def test_order_bias_cancels_and_tie_is_retained():
    result = summarize_orders({'static_first': verdict(10, 0), 'rtt_first': verdict(10, 0)})
    assert result['static']['A'] == result['rtt']['A'] == 50
    assert result['preference'] == 'tie'


def test_missing_order_rejected():
    with pytest.raises(ValueError):
        summarize_orders({'static_first': verdict(2, 6)})


@pytest.mark.parametrize('bad', [-1, 11, True, 3.5, '4'])
def test_invalid_overall_rejected(bad):
    value = verdict(2, 6)
    value['response_A']['overall']['score'] = bad
    with pytest.raises(ValueError):
        validate_verdict(value)


def test_dimension_missing_or_empty_reason_rejected():
    value = verdict(2, 6)
    broken = deepcopy(value)
    del broken['response_A']['dimensions']['safety']
    with pytest.raises(ValueError):
        validate_verdict(broken)
    value['response_B']['overall']['explanation'] = ' '
    with pytest.raises(ValueError):
        validate_verdict(value)


def test_only_task_and_anonymous_responses_sent_and_both_orders_exact():
    a = json.loads(build_request('Task', 'First artifact', 'Second artifact', 'static_first').evidence)
    b = json.loads(build_request('Task', 'First artifact', 'Second artifact', 'rtt_first').evidence)
    assert set(a) == {'task_instruction', 'response_A', 'response_B'}
    assert a['response_A'] == b['response_B'] == 'First artifact'
    assert a['response_B'] == b['response_A'] == 'Second artifact'


def test_scale_endpoints_and_schema_match_normalization():
    request = build_request('Task', 'First', 'Second', 'static_first')
    for response in request.schema['properties'].values():
        assert response['properties']['overall']['properties']['score'] == {
            'type': 'integer', 'minimum': 0, 'maximum': 10}
        for dimension in response['properties']['dimensions']['properties'].values():
            assert dimension['properties']['score']['minimum'] == 0
            assert dimension['properties']['score']['maximum'] == 10
    result = summarize_orders({'static_first': verdict(0, 10), 'rtt_first': verdict(10, 0)})
    assert result['static']['A'] == 0
    assert result['rtt']['A'] == 100
    assert 'from 0 (worst) to 10 (best)' in request.instructions
