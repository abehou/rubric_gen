"""Read-only pre-revision variation in three completed package-control cohorts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'runs/babel-overnight-20260907'
COHORTS = {
    'original': 'analysis-package-context-10353356',
    'policy-cohort': 'analysis-package-policy-10354567',
    'replication': 'analysis-package-replication-10356064',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze():
    sources = {}
    def read(path):
        sources[str(path)] = digest(path)
        return json.loads(path.read_text())
    rows = []
    for cohort, directory in COHORTS.items():
        report = read(RUNS / directory / 'analysis.json')
        assert report['analysis_source_sha256'] == digest(Path(__file__).with_name('analyze_babel.py'))
        selected = [r for r in report['rows'] if r['condition_id'] == 'user-simulator-static']
        assert len(selected) == 6
        assert {(r['replicate'], r['model']) for r in selected} == {
            (rep, model) for rep in (1, 2, 3) for model in ('gpt-5.6-sol', 'claude-opus-5')}
        for r in selected:
            state_path = Path(r['state_path'])
            assert digest(state_path) == r['state_sha256']
            state = read(state_path)
            initial_eval = read(state_path.parent / 'judgments/s000' / r['selected_rubric_sha256'] / 'evaluation.json')
            feedback = read(state_path.parent / 'feedback-generations/s000.json')
            criteria = initial_eval['criteria']
            points = {key: value['points'] for key, value in criteria.items()}
            rows.append(dict(cohort=cohort, replicate=r['replicate'], model=r['model'],
                task=r['task_id'], initial_artifact_sha256=r['initial_submission_sha256'],
                selected_rubric_sha256=r['selected_rubric_sha256'],
                initial_W=state['scores'][0], initial_S=r['values']['S']-r['values']['selected_gain'],
                initial_A=r['values']['A']-r['values']['quality_gain'], criterion_points=points,
                criterion_content_sha256=hashlib.sha256(json.dumps(criteria,sort_keys=True).encode()).hexdigest(),
                full_feedback_sha256=feedback['full_feedback_sha256'],
                simulator_artifact_sha256=feedback['current_artifact_sha256'],
                history_sha256=feedback['history_sha256'],
                feedback_characters=sum(len(c['feedback']) for c in feedback['output']['concerns'])))
    summary = []
    for rep in (1, 2, 3):
        for model in ('gpt-5.6-sol', 'claude-opus-5'):
            subset = [r for r in rows if r['replicate'] == rep and r['model'] == model]
            assert len(subset) == 3
            for key in ('initial_artifact_sha256','selected_rubric_sha256','simulator_artifact_sha256','history_sha256','initial_W'):
                assert len({r[key] for r in subset}) == 1
            assert all(r['criterion_points'] == subset[0]['criterion_points'] for r in subset)
            summary.append(dict(replicate=rep, model=model, initial_W=subset[0]['initial_W'],
                initial_A=[r['initial_A'] for r in subset],
                initial_A_range=max(r['initial_A'] for r in subset)-min(r['initial_A'] for r in subset),
                initial_S=[r['initial_S'] for r in subset],
                distinct_criterion_content=len({r['criterion_content_sha256'] for r in subset}),
                distinct_private_feedback=len({r['full_feedback_sha256'] for r in subset})))
    return dict(rows=rows, summary=summary, sources=sources, diagnostic_sha256=digest(Path(__file__)),
        scope='Completed controls only; identical initial artifacts/points, not guaranteed identical full auditor requests. Variation cannot be assigned to simulator stochasticity alone because private feedback text differs. Preserve quality guards and all outcomes; no evaluator rescore or scientific definition change.')


if __name__ == '__main__':
    result = analyze()
    out = RUNS / 'initial-package-control-variation-10356064'
    out.mkdir(exist_ok=False)
    (out / 'variation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['summary'], indent=2))
