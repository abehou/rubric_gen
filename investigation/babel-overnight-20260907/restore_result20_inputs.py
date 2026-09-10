"""Restore verified public Result20 input files into a fresh immutable archive namespace."""
import hashlib,json,os,socket,tarfile,tempfile,time,urllib.request
from pathlib import Path,PurePosixPath
ROOT=Path('/home/aydanh/repos/rubric_gen')
URL='https://github.com/abehou/rubric_gen/releases/download/aydan-red-team-backup-20260906/revision-seeds-paraphrases.tar.gz'
EXPECTED='155706072d6c4f5647c7b8f8b409fe3abc005049c23b99175fb23324fbfee24a'
PREFIXES=('seeds/biomnibench/native-prompt-results20/','runs/rubric-paraphrases/biomnibench/red-team-results20/')
def main():
 job=os.environ['SLURM_JOB_ID'];out=ROOT/f'runs/babel-result20-input-restore-{job}';out.mkdir(exist_ok=False);start=time.time()
 (out/'launch.json').write_text(json.dumps({'job':job,'hostname':socket.gethostname(),'url':URL,'archive_sha256':EXPECTED,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Restore saved inputs only;no provider calls or old-run resume;fresh namespace.'},indent=2)+'\n')
 files=[];directories=[]
 with tempfile.TemporaryDirectory(prefix=f'rubric-r20-{job}-',dir=os.environ.get('SLURM_TMPDIR','/tmp')) as temp:
  archive=Path(temp)/'inputs.tar.gz';h=hashlib.sha256();size=0
  with urllib.request.urlopen(URL,timeout=120) as response,archive.open('wb') as f:
   while block:=response.read(2**20):f.write(block);h.update(block);size+=len(block)
  assert h.hexdigest()==EXPECTED and size==1619400925,'archive integrity mismatch'
  with tarfile.open(archive,'r:gz') as tar:
   for m in tar:
    name=m.name.removeprefix('./');rel=PurePosixPath(name)
    if not name.startswith(PREFIXES):continue
    assert not rel.is_absolute() and '..' not in rel.parts,'unsafe member path'
    if any(part.startswith('._') for part in rel.parts):continue
    if m.isdir():
     (out/'archive-inputs'/Path(*rel.parts)).mkdir(parents=True,exist_ok=True)
     directories.append(name)
     continue
    assert m.isfile(),'nonregular input member'
    dest=out/'archive-inputs'/Path(*rel.parts);dest.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256()
    with tar.extractfile(m) as src,dest.open('xb') as dst:
     while block:=src.read(2**20):dst.write(block);h.update(block)
    assert dest.stat().st_size==m.size
    files.append({'path':name,'size':m.size,'sha256':h.hexdigest()})
 (out/'directories.json').write_text(json.dumps(directories,indent=2)+'\n')
 (out/'files.json').write_text(json.dumps(files,indent=2)+'\n')
 (out/'result.json').write_text(json.dumps({'success':True,'files':len(files),'elapsed_seconds':time.time()-start,'archive_sha256':EXPECTED,'native_validation':'pending;original manifests unchanged'},indent=2)+'\n')
 print(json.dumps({'job':job,'output':str(out),'files':len(files)}))
if __name__=='__main__':main()
