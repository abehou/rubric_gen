#!/bin/bash
# Provider-free completion/lineage gate for the 18 candidate assignments.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --job-name=rtt-pass-gate
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915/experiments/trace-task-paraphrase-required/completion-pass-gate-%j.log
set -euo pipefail
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915
ROOT=/home/aydanh/runs/rtt-completion-pass-dev3-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/completion-pass-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src" PYTHONDONTWRITEBYTECODE=1
"$PY" - "$CFG" "$ROOT" <<'PY'
import json, sys
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.study_validation import validate_completed_revision
cfg, root = map(Path, sys.argv[1:])
exp = load_experiment(cfg)
rev = Path(str(exp.dag['revise']['output_dir']))
records = terminal_records(exp, json.loads((rev / 'study.json').read_text()))
if len(records) != 18 or any(r['status'] != 'completed' for r in records):
    raise SystemExit(f'expected 18 completed records, found {len(records)}')
assignments = {a.assignment_id: a for a in exp.assignments}
for rec in records:
    path = rev / rec['experiment_dir']
    validate_completed_revision(path, assignments[rec['assignment_id']], exp,
                                Path(str(exp.dag['seed']['output_dir'])),
                                Path(str(exp.dag['paraphrase']['output_dir'])))
    if not any((path / 'submissions').glob('*/workspace/answer.txt')):
        raise SystemExit(f'missing public artifact: {path}')
payload = {'status':'pass','provider_calls':0,'experiment_id':exp.experiment_id,
           'records':len(records),'candidate':exp.protocol['red_team_trace_version'],
           'revise_root':str(rev)}
(root / 'completion-gate.json').write_text(json.dumps(payload, indent=2) + '\n')
print(json.dumps(payload, sort_keys=True))
PY
