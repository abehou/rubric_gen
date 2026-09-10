"""Provider-free post-report checks; preserve separate original/new exposure arms."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path('/home/aydanh/repos/rubric_gen')
BASE = ROOT / 'runs/babel-result20-cue-ranking-20260909/comparison-v1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    assert os.environ.get('SLURM_JOB_ID'), 'Run saved-artifact census on Slurm'
    report = BASE / 'analysis.json'
    receipt = json.loads((BASE / 'receipt.json').read_text())
    assert receipt['success'] and receipt['analysis_sha256'] == digest(report)
    output = BASE / ('joint-and-exposure-' + os.environ['SLURM_JOB_ID'])
    output.mkdir(exist_ok=False)
    gates_path = Path(__file__).with_name('evaluate.py')
    gates = load('prospective_gates', gates_path).evaluate(json.loads(report.read_text())['rows'])
    gates.update(analysis_sha256=digest(report), script_sha256=digest(gates_path))
    (output / 'joint-gates.json').write_text(json.dumps(gates, indent=2) + '\n')
    helper = ROOT / 'runs/babel-code/result20-cue-ranking/investigation/babel-overnight-20260907/policy_exposure.py'
    census = load('policy_exposure', helper)
    sources = {
        'original_trace': ROOT / 'runs/babel-result20-cue-contrast-20260908/comparison-v1/trace-native/analysis.json',
        'ranking_trace': BASE / 'ranking-native/analysis.json',
    }
    for arm, source in sources.items():
        result = census.inspect_report(source)
        assert len(result['assignments']) == 60
        result['input_report_sha256'] = digest(source)
        (output / f'{arm}-exposure.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'receipt.json').write_text(json.dumps(dict(success=True, job_id=os.environ['SLURM_JOB_ID'], script_sha256=digest(Path(__file__))), indent=2) + '\n')
    print(json.dumps(dict(output=str(output), gates=gates['gates']), indent=2))


if __name__ == '__main__':
    main()
