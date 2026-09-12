"""Run existing reports with the reviewed native mixed-provenance validator."""
import runpy
import sys
from pathlib import Path

scope = sys.argv[1]
if scope == 'queue2':
    original = Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-appendix-queue2-20260912')
    runtime = Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q2-original-20260912')
elif scope == 'queue3':
    original = Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-feedback-matrix-queue3-20260912')
    runtime = Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q3-reviewed-20260912')
else:
    raise ValueError('queue2 or queue3 required')
# Retain original config/output paths while using the already reviewed checker.
sys.path.insert(0, str(runtime / 'scripts/diagnostics'))
import check_audit_coverage  # noqa: F401,E402
bundle = original / f'experiments/biomnibench-v21-to45/{scope}'
sys.path.insert(0, str(bundle))
if scope == 'queue2':
    runpy.run_path(str(bundle / 'report.py'), run_name='__main__')
else:
    module = runpy.run_path(str(bundle / 'report.py'), run_name='existing_policy_report')
    for cell in (*module['CELLS'], 'user_simulator-trace'):
        module['one_cell'](cell)
    module['comparison']()
