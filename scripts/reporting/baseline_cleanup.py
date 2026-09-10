import hashlib,json,os,shutil
from pathlib import Path
R=Path('/home/aydanh/repos/rubric_gen');out=R/'docs/archive/baseline-freeze-20260909';assert os.environ.get('SLURM_JOB_ID')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
cache_dirs=[R/'.pytest_cache',R/'tests/__pycache__',R/'scripts/reporting/__pycache__']+list((R/'src').rglob('__pycache__'))
cache_dirs=sorted({p for p in cache_dirs if p.exists()})
files=[]
for d in cache_dirs:
 assert not d.is_symlink() and (d.name=='__pycache__' or d==R/'.pytest_cache')
 for p in d.rglob('*'):
  assert not p.is_symlink(),p
  if p.is_file():files.append({'path':str(p.relative_to(R)),'bytes':p.stat().st_size,'sha256':sha(p),'action':'remove disposable Python/pytest cache'})
figs=[];dest=out/'reference-figures';dest.mkdir(exist_ok=True)
for source,target in [('avg.png','original-gap-artifact-reference.png'),('Openal + Anthropic averace.png','original-trajectory-reference.png')]:
 p=R/source;q=dest/target;assert p.is_file() and not p.is_symlink() and not q.exists()
 figs.append({'source':source,'destination':str(q.relative_to(R)),'sha256':sha(p),'bytes':p.stat().st_size,'action':'archive unchanged supplied reference figure'})
runs=[{'path':str(p.relative_to(R)),'kind':'directory' if p.is_dir() else 'file','action':'retain unchanged; scientific evidence, provenance or reproducibility dependency not deleted'} for p in sorted((R/'runs').iterdir())]
receipt={'job':os.environ['SLURM_JOB_ID'],'hostname':os.uname().nodename,'phase':'planned','removed':files,'archived':figs,'runs_inventory':runs,'raw_evidence_removed':False}
path=out/'cleanup-manifest.json';assert not path.exists();path.write_text(json.dumps(receipt,indent=2)+'\n')
for row in figs:
 p=R/row['source'];q=R/row['destination'];assert sha(p)==row['sha256'];p.rename(q);assert sha(q)==row['sha256']
for d in cache_dirs:shutil.rmtree(d)
receipt.update(phase='completed',removed_bytes=sum(x['bytes'] for x in files),removed_files=len(files),archived_bytes=sum(x['bytes'] for x in figs))
path.write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:receipt[k] for k in ['job','removed_bytes','removed_files','archived_bytes','raw_evidence_removed']}))
