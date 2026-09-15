#!/bin/bash
# Provider-free scope and frozen-input gate for completion-pass RTT Dev3.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --job-name=rtt-pass-preflight
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915/experiments/trace-task-paraphrase-required/completion-pass-preflight-%j.log
set -euo pipefail
umask 077
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915
ROOT=/home/aydanh/runs/rtt-completion-pass-dev3-20260915
INPUT_ROOT=/home/aydanh/runs/rtt-clean-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/completion-pass-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
mkdir -p "$ROOT" "$ROOT/logs"
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
"$PY" - "$CFG" "$ROOT" "$INPUT_ROOT" "$RUN" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.seeds import resolve_seed

cfg, root, input_root, run = map(Path, sys.argv[1:])
exp = load_experiment(cfg)
expected_tasks = {'da-3-4', 'da-11-1', 'da-18-1'}
expected_conditions = {
    'full-red-team-trace',
    'user-simulator-red-team-trace',
}
expected_version = 'attack_defense_v2.1_task_paraphrase_required_completion_pass'
expected_seed = (input_root / 'seeds/native-dev3').resolve()
expected_paraphrase = (input_root / 'paraphrases/dev3').resolve()
expected_revise = (root / f'study/{exp.experiment_id}').resolve()
expected_detect = (root / f'detect/{exp.experiment_id}').resolve()

if set(exp.task_ids) != expected_tasks or exp.replicates != 3:
    raise SystemExit('canonical Dev3 task/replicate scope changed')
if {a.condition_id for a in exp.execution_assignments} != expected_conditions:
    raise SystemExit('condition scope changed')
if len(exp.execution_assignments) != 18:
    raise SystemExit(f'expected exactly 18 execution assignments, got {len(exp.execution_assignments)}')
if exp.protocol.get('red_team_trace_version') != expected_version:
    raise SystemExit('candidate identity changed')

actual = {
    stage: Path(str(exp.dag[stage]['output_dir'])).resolve()
    for stage in ('seed', 'paraphrase', 'revise', 'detect')
}
expected = {
    'seed': expected_seed,
    'paraphrase': expected_paraphrase,
    'revise': expected_revise,
    'detect': expected_detect,
}
if actual != expected:
    raise SystemExit(f'input/output roots changed: actual={actual!r} expected={expected!r}')

for task in exp.task_ids:
    for rep in range(1, exp.replicates + 1):
        resolve_seed(
            actual['seed'],
            exp.task_dir(task),
            rep,
            seed_generator=exp.seed_agent_config(),
            prompt_profile=exp.protocol['prompt'],
            benchmark=exp.benchmark,
        )
validate_paraphrase_run(actual['paraphrase'], exp)

study = actual['revise'] / 'study.json'
existing_records = 0
if study.exists():
    existing_records = len(json.loads(study.read_text()).get('assignments', []))

payload = {
    'status': 'pass',
    'provider_calls': 0,
    'experiment_id': exp.experiment_id,
    'commit': subprocess.check_output(
        ['git', '-C', str(run), 'rev-parse', 'HEAD'], text=True
    ).strip(),
    'tasks': list(exp.task_ids),
    'assignments': 18,
    'conditions': sorted(expected_conditions),
    'candidate': expected_version,
    'frozen_input_root': str(input_root),
    'new_output_root': str(root),
    'existing_study_records': existing_records,
}
(root / 'preflight.json').write_text(json.dumps(payload, indent=2) + '\n')
print(json.dumps(payload, sort_keys=True))
PY
