#!/bin/bash
# Provider-free gate for the complete fresh input pool.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-clean-preflight
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/clean-preflight-%j.log
set -euo pipefail
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
ROOT=/home/aydanh/runs/rtt-clean-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/clean-matched-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
mkdir -p "$ROOT" "$ROOT/logs"
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
"$PY" - "$CFG" "$ROOT" "$RUN" <<'PY'
import json, sys
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.seeds import resolve_seed
cfg, root, run = map(Path, sys.argv[1:])
exp=load_experiment(cfg)
if set(exp.task_ids)!={'da-3-4','da-11-1','da-18-1'} or exp.replicates != 3:
    raise SystemExit('canonical task/replicate scope changed')
expected={f'{feedback}-{rubric}' for feedback in ('full','user-simulator') for rubric in ('static','red-team-trace')}
if {a.condition_id for a in exp.execution_assignments} != expected or len(exp.execution_assignments)!=36:
    raise SystemExit('expected exactly 36 assignments')
if exp.protocol.get('red_team_trace_version') != 'attack_defense_v2.1_task_paraphrase_required_completion':
    raise SystemExit('candidate identity changed')
for stage in ('seed','paraphrase','revise','detect'):
    p=Path(str(exp.dag[stage]['output_dir'])).resolve()
    if not str(p).startswith(str(root.resolve())+('/') if p != root.resolve() else str(root.resolve())):
        raise SystemExit(f'{stage} output escapes clean root: {p}')
seed_root=Path(str(exp.dag['seed']['output_dir']))
for task in exp.task_ids:
    for rep in range(1,exp.replicates+1):
        resolve_seed(seed_root, exp.task_dir(task), rep, seed_generator=exp.seed_agent_config(), prompt_profile=exp.protocol['prompt'], benchmark=exp.benchmark)
validate_paraphrase_run(Path(str(exp.dag['paraphrase']['output_dir'])),exp)
payload={'status':'pass','provider_calls':0,'experiment_id':exp.experiment_id,'commit':__import__('subprocess').check_output(['git','-C',str(run),'rev-parse','HEAD'],text=True).strip(),'tasks':list(exp.task_ids),'assignments':36,'candidate':exp.protocol['red_team_trace_version'],'inputs_on_clean_root':True}
(root/'preflight.json').write_text(json.dumps(payload,indent=2)+'\n')
print(json.dumps(payload,sort_keys=True))
PY

