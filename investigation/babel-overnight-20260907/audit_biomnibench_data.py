"""Read-only local data integrity against a saved, pinned public HF inventory."""
from pathlib import Path
import hashlib,json,yaml
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runs/babel-overnight-20260907/biomnibench-data-audit-20260908'
source=json.loads((OUT/'hf-main.json').read_text())
rows=[];tiers={}
for tier in ('dev3','results20'):
 config=ROOT/f'experiments/biomnibench-{tier}.yaml';payload=yaml.safe_load(config.read_text());tiers[tier]={'tasks':payload['tasks'],'replicates':payload['randomization']['replicates'],'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'seed_pool_exists':(config.parent/payload['dag']['seed']['output_dir']).exists(),'paraphrase_pool_exists':(config.parent/payload['dag']['paraphrase']['output_dir']).exists()}
 for task in payload['tasks']:
  files=[]
  for remote in source['files']:
   if not remote['path'].startswith(task+'/'):continue
   local=ROOT/'data/biomnibench-da'/remote['path'];row=dict(path=remote['path'],expected_size=remote['size'],exists=local.is_file())
   if local.is_file():
    size=local.stat().st_size;sha=hashlib.sha256();blob=hashlib.sha1(f'blob {size}\0'.encode())
    with local.open('rb') as stream:
     for block in iter(lambda:stream.read(2**20),b''):sha.update(block);blob.update(block)
    expected=remote['lfs']['sha256'] if remote['lfs'] else remote['blob_id'];actual=sha.hexdigest() if remote['lfs'] else blob.hexdigest()
    row.update(size=size,sha256=sha.hexdigest(),git_blob_sha1=blob.hexdigest(),expected_content_hash=expected,hash_algorithm='sha256' if remote['lfs'] else 'git-blob-sha1',matches_upstream=size==remote['size'] and actual==expected)
    meta=ROOT/'data/biomnibench-da/.cache/huggingface/download'/f"{remote['path']}.metadata"
    if meta.exists():
     fields=meta.read_text().splitlines();row['transferred_download_metadata']={'revision':fields[0],'etag':fields[1],'metadata_sha256':hashlib.sha256(meta.read_bytes()).hexdigest()}
   files.append(row)
  rows.append({'tier':tier,'task':task,'complete':bool(files) and all(f.get('matches_upstream') for f in files),'files':files})
result={'upstream_repo':source['repo_id'],'upstream_sha':source['sha'],'source_inventory_sha256':hashlib.sha256((OUT/'hf-main.json').read_bytes()).hexdigest(),'tiers':tiers,'tasks':rows,'restored_files':[],'scope':'Canonical benchmark bytes only;generated seeds/paraphrases require separate provenance and current workflow validation. No historical outputs mutated.'}
p=OUT/'inventory.json'
with p.open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
print(json.dumps({'tasks':len(rows),'files':sum(len(x['files']) for x in rows),'all_complete':all(x['complete'] for x in rows),'tiers':tiers},indent=2))
