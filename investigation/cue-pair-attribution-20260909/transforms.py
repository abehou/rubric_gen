"""Private paired diagnostic transformations; never mutate saved requests."""
import copy
import difflib
import json

CLARIFICATION = """Before comparing quality, resolve each pair's artifact_A and artifact_B references to their exact artifact_id entries. Check each claimed difference against that artifact's own text and unchanged context. In assessment_A and assessment_B, name the referenced artifact_id and quote the shortest relevant text supporting the distinction. Verify that your preference names the artifact supported by those assessments. A minus line belongs to A and a plus line to B in the supplied A-to-B diff; the diff alone does not establish which version is correct. If the evidence does not establish a quality difference, return tie."""

def difference(a, b):
    text = '\n'.join(difflib.unified_diff(a.splitlines(), b.splitlines(), fromfile='artifact_A', tofile='artifact_B', n=2, lineterm=''))
    raw = text.encode('utf-8')
    return {'format': 'unified_diff_A_to_B', 'text': raw[:8192].decode('utf-8', errors='ignore'), 'truncated': len(raw) > 8192}

def swap(evidence):
    source = json.loads(evidence)
    if source.get('assessment_view') != 'rubric_free':
        raise ValueError('Only rubric-free induction assessments are eligible')
    result = copy.deepcopy(source)
    artifacts = {a['artifact_id']: a['content'] for a in source['artifacts']}
    if len(artifacts) != len(source['artifacts']):
        raise ValueError('Duplicate artifact identity')
    for pair in result['pairs']:
        a, b = pair['artifact_A']['artifact_id'], pair['artifact_B']['artifact_id']
        if pair['visible_difference'] != difference(artifacts[a], artifacts[b]):
            raise ValueError('Saved navigation diff does not match full artifact text')
        pair['artifact_A'], pair['artifact_B'] = pair['artifact_B'], pair['artifact_A']
        pair['visible_difference'] = difference(artifacts[b], artifacts[a])
    return result

def preferred_ids(evidence, response):
    ev = json.loads(evidence) if isinstance(evidence, str) else evidence
    pairs = {p['pair_id']: p for p in ev['pairs']}
    records = response['assessments']
    if len(records) != len(pairs) or {r['pair_id'] for r in records} != set(pairs):
        raise ValueError('Incomplete or duplicate pair judgments')
    out = {}
    for r in records:
        pref = r['preference']
        if pref not in {'artifact_A', 'artifact_B', 'tie'}:
            raise ValueError('Invalid preference')
        out[r['pair_id']] = None if pref == 'tie' else pairs[r['pair_id']][pref]['artifact_id']
    return out
