"""Independent canonical45 hash verification on the compute-only NFS mount."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket

ROOT = Path('/home/aydanh/repos/rubric_gen')
DEST = Path('/data/user_data/aydanh/rubric_gen/data/biomnibench-da-results45-e1c8ca5e11a6')
assert os.environ.get('SLURM_JOB_ID')
receipt_path = ROOT / 'runs/results45-data-prepare-10372571/result.json'
receipt = json.loads(receipt_path.read_text())
inventory_path = ROOT / 'investigation/biomnibench-results45-20260908/inventory.json'
inventory = json.loads(inventory_path.read_text())
meta_path = ROOT / inventory['metadata_path']
assert hashlib.sha256(meta_path.read_bytes()).hexdigest() == inventory['metadata_sha256']
metadata = json.loads(meta_path.read_text())
assert receipt['success'] and receipt['tasks'] == inventory['results45']
assert Path(receipt['destination']) == DEST and not DEST.is_symlink()
records = {r['path']: r for r in receipt['files']}
expected = [f for f in metadata['files'] if f['path'].split('/')[0] in inventory['results45']]
assert set(records) == {f['path'] for f in expected}
out = ROOT / ('runs/confirmation-data-validated-' + os.environ['SLURM_JOB_ID'])
out.mkdir(exist_ok=False)
verified = []
for item in expected:
    path = DEST / item['path']
    assert path.is_file() and not path.is_symlink() and path.stat().st_size == item['size']
    sha = hashlib.sha256()
    blob = hashlib.sha1(f"blob {item['size']}\0".encode())
    with path.open('rb') as stream:
        while chunk := stream.read(8 * 1024**2):
            sha.update(chunk)
            blob.update(chunk)
    lfs = (item.get('lfs') or {}).get('sha256')
    assert sha.hexdigest() == records[item['path']]['sha256']
    assert sha.hexdigest() == lfs if lfs else blob.hexdigest() == item['blob_id']
    verified.append(dict(path=item['path'], size=item['size'], sha256=sha.hexdigest()))
assert {r['path'].split('/')[0] for r in verified} == set(inventory['results45'])
(out / 'result.json').write_text(json.dumps(dict(success=True, job_id=os.environ['SLURM_JOB_ID'],
    hostname=socket.gethostname(), compute_only=True, destination=str(DEST), tasks=inventory['results45'],
    files=verified, bytes=sum(r['size'] for r in verified), free_bytes=shutil.disk_usage(DEST).free,
    source_receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    inventory_sha256=hashlib.sha256(inventory_path.read_bytes()).hexdigest()), indent=2) + '\n')
print(json.dumps(dict(success=True, tasks=45, files=len(verified), output=str(out))))
