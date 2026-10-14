"""Prepare A-only paired requests and estimates without constructing an API client."""
from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()
from collections import Counter
from pathlib import Path
import json
from math import ceil
from rubric_gen.artifacts.serialization import write_json_atomic as write
from rubric_gen.runtime.llm import StructuredRequest
from rubric_gen.submission_revision.evaluation.absolute_score import validate_verdict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def read(path):
    return json.loads(Path(path).read_text())

def main():
    scope = read(HERE / 'scope.json')
    out = ROOT / scope['output']
    prompt = (HERE / 'prompt-v2.txt').read_text()
    ids = {t['id'] for t in scope['tasks']}
    rows = [r for r in read(ROOT / scope['source_comparison'])
            if r['panel'] == scope['panel'] and r['task_id'] in ids
            and r['condition_id'] in scope['conditions']]
    expected = {(t, c, n) for t in ids for c in scope['conditions'] for n in scope['replicates']}
    assert Counter((r['task_id'], r['condition_id'], r['replicate']) for r in rows) == Counter(expected)
    estimates = {'openai': [], 'anthropic': []}
    baselines = []
    for n, row in enumerate(sorted(rows, key=lambda r: (r['task_id'], r['replicate'], r['condition_id'])), 1):
        source = ROOT / scope['source_jobs'] / row['jobs']['A']
        old = read(source / 'input.json')
        request = {**old['request'], 'instructions': prompt, 'max_output_tokens': scope['max_output_tokens']}
        evidence = json.loads(request['evidence'])
        assert set(evidence) == {'response', 'task_instruction'}
        # The evidence bytes are reused, with no rubric or audit metadata added.
        assert request['evidence'] == old['request']['evidence']
        StructuredRequest(**request)
        gpt = read(old['source_record'])
        claude = read(source / 'result.json')
        validate_verdict(gpt['verdict']); validate_verdict(claude['verdict'])
        assert gpt['generation']['effective_model'] == scope['providers']['openai']['model']
        assert claude['actual_model'] == scope['providers']['anthropic']['model']
        gu = gpt['generation']['provider_metadata']['usage']
        cu = read(source / 'response-001.json')['response']['usage']
        delta = ceil((len(prompt) - len(old['request']['instructions'])) / 4)
        gi = gu['input_tokens'] + delta
        ci = cu['input_tokens'] + cu.get('cache_read_input_tokens', 0) + cu.get('cache_creation_input_tokens', 0) + delta
        # Reasoning is already included in output_tokens. New defect explanations
        # may take longer: central 1.5x plus 200 tokens; range 1x..3x plus 100..400.
        for provider, inp, output, irate, orate in [
            ('openai', gi, gu['output_tokens'], 2., 10.),
            ('anthropic', ci, cu['output_tokens'], .1, .5),
        ]:
            estimates[provider].append({
                'input_tokens_estimate': inp, 'old_output_tokens': output,
                'central_usd': (inp * irate + (output * 1.5 + 200) * orate) / 1e6,
                'low_usd': (inp * irate + (output + 100) * orate) / 1e6,
                'high_usd': (inp * irate + (output * 3 + 400) * orate) / 1e6,
            })
        key = f'artifact-{n:03d}'
        write(out / 'inputs' / (key + '.json'), {'request': request})
        baselines.append({
            'key': key, 'task_id': row['task_id'], 'replicate': row['replicate'],
            'condition_id': row['condition_id'], 'assignment_id': row['assignment_id'],
            'source_root': row['root'], 'source_input': str(source / 'input.json'),
            'source_record': old['source_record'],
            'gpt_native_A': gpt['verdict'], 'claude_native_A': claude['verdict'],
            'gpt_current': row['gpt_final'], 'claude_current': row['claude_final'],
        })
    write(out / 'baselines.json', baselines)
    write(out / 'scope.json', scope)
    summaries = {p: {k: sum(x[k] for x in items) for k in ('central_usd', 'low_usd', 'high_usd')}
                 for p, items in estimates.items()}
    for p in summaries:
        summaries[p]['high_usd'] *= 1.20  # plausible retry/usage headroom, not calibrated CI
        summaries[p]['proposed_cap_usd'] = scope['providers'][p]['proposed_cap_usd']
    estimate = {'providers': summaries, 'total_central_usd': sum(v['central_usd'] for v in summaries.values()),
                'total_low_usd': sum(v['low_usd'] for v in summaries.values()),
                'total_high_usd': sum(v['high_usd'] for v in summaries.values()),
                'basis': 'Exact matched old A token usage; all output includes reasoning; no cache savings assumed. GPT rates retained from saved native relay; Claude rates verified 2026-10-14.',
                'token_estimator': 'English system-prompt length delta / 4 characters per token; old complete request counts are observed usage', 'details': estimates,
                'expected_minutes': [5, 15], 'time_basis': '60 calls/provider, 6 concurrent/provider, assumed 15–60 seconds/call plus tail/retries; planning range, no live latency probe'}
    write(out / 'estimate.json', estimate)
    write(out / 'verification.json', {'prepared': True, 'paid_calls': 0, 'tasks': len(ids),
          'artifacts': len(rows), 'jobs_per_provider': len(rows), 'total_jobs': len(rows) * 2,
          'paired_coverage_complete': True, 'old_native_A_valid': True,
          'judge_input_fields': ['task_instruction', 'response'], 'source_evidence_reused_exactly': True})
    print(json.dumps({k: v for k, v in estimate.items() if k != 'details'}, indent=2))

if __name__ == '__main__':
    main()
