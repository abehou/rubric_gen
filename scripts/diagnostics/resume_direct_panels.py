"""Private recovery invocation of existing direct stages; no protocol changes.

Run only after all four direct panels are terminal and no other process can
write those panels. A later rubric/quality stage may run in separate directories.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.direct import DirectDetectionConfig, run_direct_detection
from rubric_gen.submission_revision.experiment import load_experiment


def snapshot(root):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.glob('evaluations/*/cases/*/*/score.json')}


def main(experiment_path):
    experiment = load_experiment(Path(experiment_path).resolve())
    study = Path(str(experiment.dag['revise']['output_dir']))
    audit = Path(str(experiment.dag['detect']['output_dir']))
    roots = {window: audit / f'direct_{window.value}'
             for window in RevisionDetectionWindow}
    # This recovery path may not start a new or unfinished direct panel.
    for window, root in roots.items():
        summaries = list(root.glob('evaluations/*/summary.json'))
        if len(summaries) != 1:
            raise ValueError(f'{window.value}: require one terminal panel summary')
        summary = json.loads(summaries[0].read_text())
        if not summary.get('records') or any(
            row['status'] not in {'completed', 'skipped', 'failed'}
            for row in summary['records']
        ):
            raise ValueError(f'{window.value}: panel is not terminal')
    results = {}
    for window, root in roots.items():
        before = snapshot(root)
        print(json.dumps({'time': datetime.now().astimezone().isoformat(),
                          'stage': window.value, 'event': 'resume',
                          'concurrency': 1, 'preserved_scores': len(before)}), flush=True)
        try:
            status = run_direct_detection(DirectDetectionConfig(
                experiment=experiment, study_dir=study, output_dir=root,
                max_concurrency=1, resume=True, window=window,
            ))
        finally:
            after = snapshot(root)
            changed = [str(p) for p, digest in before.items()
                       if after.get(p) != digest]
            if changed:
                raise RuntimeError(f'Existing successful score changed: {changed}')
            print(json.dumps({'time': datetime.now().astimezone().isoformat(),
                              'stage': window.value, 'event': 'preservation_checked',
                              'unchanged_scores': len(before),
                              'new_scores': len(after) - len(before)}), flush=True)
        results[window.value] = int(status)
    print(json.dumps({'direct_stage_exit_statuses': results}), flush=True)
    return int(any(results.values()))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Supply the existing experiment YAML path')
    raise SystemExit(main(sys.argv[1]))
