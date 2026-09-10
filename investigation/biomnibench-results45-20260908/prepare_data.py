"""Stage exact pinned canonical data on shared storage; no model calls."""
import fcntl,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
assert os.environ.get('SLURM_JOB_ID')
inventory=BUNDLE/'inventory.json';m=json.loads(inventory.read_text());metadata=Path(m['metadata_path']);meta=json.loads(metadata.read_text())
assert hashlib.sha256(metadata.read_bytes()).hexdigest()==m['metadata_sha256']
DEST=Path('/data/user_data/aydanh/rubric_gen/data/biomnibench-da-results45-'+m['revision'][:12]);DEST.mkdir(parents=True,exist_ok=True)
lock=(DEST/'.prepare.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
identity=dict(revision=m['revision'],inventory_sha256=hashlib.sha256(inventory.read_bytes()).hexdigest(),tasks=m['results45'])
p=DEST/'.identity.json'
if p.exists():assert json.loads(p.read_text())==identity
else:p.write_text(json.dumps(identity,indent=2)+'\n')
files=[x for x in meta['files'] if x['path'].split('/')[0] in m['results45']]
missing=sum(x['size'] for x in files if not (DEST/x['path']).is_file())
assert shutil.disk_usage(DEST).free > missing+30*1024**3,'Insufficient shared storage headroom'
out=ROOT/f'runs/results45-data-prepare-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
(out/'launch.json').write_text(json.dumps(dict(job=os.environ['SLURM_JOB_ID'],destination=str(DEST),identity=identity,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),started=time.time()),indent=2)+'\n')
records=[]
for task in m['results45']:
    task_files=[x for x in files if x['path'].startswith(task+'/')]
    local=ROOT/'data/biomnibench-da'/task;target=DEST/task
    if not target.exists() and local.is_dir():shutil.copytree(local,target)
    if not all((DEST/x['path']).is_file() and (DEST/x['path']).stat().st_size==x['size'] for x in task_files):
        cmd=[str(ROOT/'.venv/bin/hf'),'download',m['repo_id'],'--repo-type','dataset','--revision',m['revision'],'--local-dir',str(DEST),'--max-workers','4','--quiet','--include',task+'/*']
        with (out/(task+'-download.log')).open('a') as stream:subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,check=True)
    for item in task_files:
        f=DEST/item['path'];assert f.is_file() and not f.is_symlink() and f.stat().st_size==item['size'],str(f)
        sha=hashlib.sha256();blob=hashlib.sha1();blob.update(f"blob {item['size']}\0".encode())
        with f.open('rb') as stream:
            while chunk:=stream.read(8*1024**2):sha.update(chunk);blob.update(chunk)
        expected=(item.get('lfs') or {}).get('sha256')
        assert (sha.hexdigest()==expected if expected else blob.hexdigest()==item['blob_id']),str(f)
        record=dict(path=item['path'],size=item['size'],sha256=sha.hexdigest(),upstream_match=True);records.append(record)
    with (out/'progress.jsonl').open('a') as stream:stream.write(json.dumps(dict(task=task,files=len(task_files),verified=True,time=time.time()))+'\n')
    print(task,'verified',len(task_files),'files',flush=True)
assert len({x['path'].split('/')[0] for x in records})==45
(out/'result.json').write_text(json.dumps(dict(success=True,destination=str(DEST),tasks=m['results45'],files=records,identity=identity,job=os.environ['SLURM_JOB_ID']),indent=2)+'\n')
