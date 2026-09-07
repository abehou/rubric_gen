"""Private full-trajectory recovery via the current production API.

Operator prerequisite: no other writer may own this direct window.
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
    root = Path(str(experiment.dag['detect']['output_dir'])) / 'direct_full_trajectory'
    summaries = list(root.glob('evaluations/*/summary.json'))
    if len(summaries) != 1:
        raise ValueError('Require one existing terminal full-trajectory summary')
    summary = json.loads(summaries[0].read_text())
    if not summary.get('records') or any(
        r['status'] not in {'completed', 'skipped', 'failed'} for r in summary['records']
    ):
        raise ValueError('Full-trajectory panel is not terminal')
    before = snapshot(root)
    print(json.dumps({'time': datetime.now().astimezone().isoformat(),
                      'event': 'resume', 'concurrency': 2,
                      'preserved_scores': len(before)}), flush=True)
    try:
        status = run_direct_detection(DirectDetectionConfig(
            experiment=experiment, study_dir=study, output_dir=root,
            max_concurrency=2, resume=True,
            window=RevisionDetectionWindow.FULL_TRAJECTORY,
        ))
    finally:
        after = snapshot(root)
        changed = [str(p) for p, digest in before.items() if after.get(p) != digest]
        if changed:
            raise RuntimeError(f'Existing successful scores changed: {changed}')
        print(json.dumps({'time': datetime.now().astimezone().isoformat(),
                          'event': 'preservation_checked',
                          'unchanged_scores': len(before),
                          'new_scores': len(after) - len(before)}), flush=True)
    print(json.dumps({'full_trajectory_exit_status': int(status)}), flush=True)
    return int(status)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Supply the existing experiment YAML path')
    raise SystemExit(main(sys.argv[1]))
