"""Inspect public backup manifests in Slurm; never restore production artifacts."""
import hashlib,json,os,socket,tarfile,tempfile,time,urllib.request
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen')
URL='https://github.com/abehou/rubric_gen/releases/download/aydan-red-team-backup-20260906/revision-seeds-paraphrases.tar.gz'
EXPECTED='155706072d6c4f5647c7b8f8b409fe3abc005049c23b99175fb23324fbfee24a'
SIZE=1619400925
PREFIXES=('seeds/biomnibench/native-prompt-results20/','runs/rubric-paraphrases/biomnibench/red-team-results20/')
def main():
 job=os.environ.get('SLURM_JOB_ID')
 if not job:raise RuntimeError('Slurm allocation required')
 out=ROOT/f'runs/babel-overnight-20260907/input-backup-inspection-{job}';out.mkdir(exist_ok=False)
 start=time.time();launch={'job_id':job,'hostname':socket.gethostname(),'url':URL,'expected_sha256':EXPECTED,'expected_bytes':SIZE,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'resources':{'partition':'preempt','qos':'preempt_cpu_qos','cpus':1,'memory':'8G','time':'01:00:00','gpus':0,'account_flag':None},'scope':'Read archive members and saved input manifests only;no provider calls or production restore.'}
 (out/'launch.json').write_text(json.dumps(launch,indent=2)+'\n')
 with tempfile.TemporaryDirectory(prefix=f'rubric-backup-{job}-',dir=os.environ.get('SLURM_TMPDIR','/tmp')) as temp:
  archive=Path(temp)/'backup.tar.gz';sha=hashlib.sha256();size=0
  with urllib.request.urlopen(URL,timeout=120) as response,archive.open('wb') as dest:
   while block:=response.read(2**20):dest.write(block);sha.update(block);size+=len(block)
  if sha.hexdigest()!=EXPECTED or size!=SIZE:raise RuntimeError('backup size/hash mismatch')
  manifests=[];members=[];dev=[];total=0
  with tarfile.open(archive,'r:gz') as tar:
   for member in tar:
    total+=1;name=member.name.removeprefix('./')
    if 'da-18-1' in name or '/luna-dev3/' in name or '/native-prompt-dev3/' in name:dev.append(name)
    if not member.isfile() or not name.startswith(PREFIXES):continue
    members.append({'path':name,'size':member.size})
    if name.endswith('/manifest.json'):
     stream=tar.extractfile(member)
     if stream is None:raise RuntimeError('missing manifest stream')
     content=stream.read();manifests.append({'path':name,'sha256':hashlib.sha256(content).hexdigest(),'manifest':json.loads(content)})
  result={'archive_verified':True,'sha256':sha.hexdigest(),'bytes':size,'archive_members':total,'input_members':members,'input_manifests':manifests,'dev3_named_members':dev,'elapsed_seconds':time.time()-start,'restored_files':[],'current_native_compatibility':'Not established;manifest-only forensic inspection,not a production resume validation.'}
  (out/'inventory.json').write_text(json.dumps(result,indent=2)+'\n')
  (out/'result.json').write_text(json.dumps({'success':True,'input_members':len(members),'input_manifests':len(manifests),'dev3_named_members':len(dev),'elapsed_seconds':result['elapsed_seconds'],'restored_files':[]},indent=2)+'\n')
  print(json.dumps({'job':job,'input_members':len(members),'input_manifests':len(manifests),'dev3_named_members':len(dev),'restored_files':[]}))
if __name__=='__main__':main()
