#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-attack-defense-report
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v1/experiments/trace-attack-defense-v1/report-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v1
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910/tmp
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v1
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v1/matplotlib
unset OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY
report_python=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
for report in report_outcomes report_pipeline report_timing report_costs report_accounting report_gaps report_positives report_quote_binding report_case_review report_gap_review report_figures render_report; do
  "$report_python" "experiments/trace-attack-defense-v1/${report}.py"
done
"$report_python" - <<'PY'
import os,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
bundle=Path('experiments/trace-attack-defense-v1')
payload={'job':os.environ['SLURM_JOB_ID'],'time':datetime.now(timezone.utc).isoformat(),'provider_calls':0,
 'raw_output_root':'/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910/report',
 'report_source_sha256s':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(bundle.glob('report_*.py'))},
 'status':'complete'}
Path('docs/reports/2026-09-10/trace-attack-defense-v1/report-job.json').write_text(json.dumps(payload,indent=2)+'\n')
print(json.dumps(payload),flush=True)
PY
