"""Publish compact dev3 tables while retaining full application payloads on NFS."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
import dev_report

ROOT = Path(__file__).resolve().parents[2]


def collect(subversion):
    suffix = Path('docs/reports/2026-09-10/trace-attack-defense-v2/dev3')/subversion
    owner = dev_report.RUN/'dev3'/subversion/'report/owners'/os.environ['SLURM_JOB_ID']
    owner.mkdir(parents=True, exist_ok=True)
    write_json_atomic(owner/'launch.json', {'job': os.environ['SLURM_JOB_ID'],
        'time': datetime.now(timezone.utc).isoformat(), 'provider_calls': 0,
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'report_source_hashes': {str(p.relative_to(ROOT)): sha256_file(p)
                                for p in Path(__file__).parent.glob('dev_*.py')},
        'execution_freeze_sha256': sha256_file(Path(__file__).parent/(subversion+'-freeze.json'))})
    # The frozen collector's scientific counts are unchanged; only its reporting
    # destination is redirected before it writes potentially large payload tables.
    dev_report.ROOT = dev_report.RUN/'dev3'/subversion/'report/collector'
    dev_report.summarize(subversion)
    raw, public = dev_report.ROOT/suffix, ROOT/suffix
    public.mkdir(parents=True, exist_ok=True)
    receipts = {}
    for path in raw.iterdir():
        receipts[path.name] = {'path': str(path), 'sha256': sha256_file(path), 'bytes': path.stat().st_size}
        if path.stem not in {'candidates', 'attempts'}:
            shutil.copyfile(path, public/path.name)
    candidates = json.loads((raw/'candidates.json').read_bytes())
    compact, applications = [], []
    for candidate in candidates:
        compact.append({k: v for k, v in candidate.items() if k != 'applications'})
        for application in candidate['applications']:
            response = application['response']
            applications.append({k: candidate[k] for k in ('arm', 'task_id', 'replicate', 'assignment_id', 'generation', 'criterion_id')}
                | {'artifact_id': application['artifact_id'], 'contract_status': application['status'],
                   'applicability': response['applicability'] if response else None,
                   'level': response['level'] if response else None,
                   'source_receipt': candidate['source_receipt']})
    attempts = json.loads((raw/'attempts.json').read_bytes())
    attempts = [{k: v for k, v in attempt.items() if k != 'generation'} for attempt in attempts]
    for name, rows in [('candidates', compact), ('application-matrix', applications), ('attempts', attempts)]:
        write_json_atomic(public/(name+'.json'), rows)
        dev_report.dump_csv(public/(name+'.csv'), rows)
    write_json_atomic(public/'raw-table-receipts.json', receipts)
    for path in public.glob('*.csv'):
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))


if __name__ == '__main__':
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('saved compute tables require Slurm')
    parser = argparse.ArgumentParser()
    parser.add_argument('subversion')
    collect(parser.parse_args().subversion)
