"""Read-only allocation inventory; no downloads, model calls or secret output."""
import json
import os
from pathlib import Path
import shutil
from dotenv import load_dotenv
from huggingface_hub import get_token

ROOT = Path('/home/aydanh/repos/rubric_gen')
assert os.environ.get('SLURM_JOB_ID')
load_dotenv(ROOT / '.env.local', override=False)
inventory = json.loads((ROOT / 'investigation/biomnibench-results45-20260908/inventory.json').read_text())
metadata = json.loads((ROOT / inventory['metadata_path']).read_text())
roots = [ROOT / 'data/biomnibench-da', Path('/data/user_data/aydanh/rubric_gen/data/biomnibench-da-results45-e1c8ca5e11a6')]
coverage = {}
for root in roots:
    tasks = {}
    for task in inventory['results45']:
        files = [f for f in metadata['files'] if f['path'].startswith(task + '/')]
        missing = [f['path'] for f in files if not (root / f['path']).is_file() or (root / f['path']).stat().st_size != f['size']]
        tasks[task] = dict(expected_files=len(files), missing_or_wrong_size=missing)
    coverage[str(root)] = dict(exists=root.exists(), free_bytes=shutil.disk_usage(root).free if root.exists() else None, tasks=tasks)
result = dict(job_id=os.environ['SLURM_JOB_ID'], hf_credential_present=bool(get_token()), coverage=coverage, limitation='Size/presence only; generation requires full pinned hash validation.')
out = ROOT / ('runs/confirmation-pool-data-check-' + os.environ['SLURM_JOB_ID'])
out.mkdir(exist_ok=False)
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(dict(output=str(out), hf_credential_present=result['hf_credential_present'])))
