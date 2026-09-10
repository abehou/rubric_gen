"""Canonical task-input arithmetic check only; do not alter any artifact or grade."""
import csv,gzip,hashlib,json,os,socket
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
ROOT=Path('/home/aydanh/repos/rubric_gen');rel='da-15-1/environment/data/Cervical_Spinal_Cord_gene_counts.tsv.gz';p=ROOT/'data/biomnibench-da'/rel
receipt=json.loads((ROOT/'runs/results45-data-prepare-10372571/result.json').read_text());record=next(x for x in receipt['files'] if x['path']==rel)
h=hashlib.sha256(p.read_bytes()).hexdigest();assert h==record['sha256']
def rows():
 with gzip.open(p,'rt') as f:
  reader=csv.reader(f,delimiter='\t');header=next(reader);idx=[i for i,x in enumerate(header) if x.startswith('sample_')];assert len(idx)==174
  for row in reader:yield [float(row[i]) for i in idx]
sums=[0.0]*174;n=0
for row in rows():
 n+=1
 for i,v in enumerate(row):sums[i]+=v
assert all(v>0 for v in sums)
retained={10:0,20:0}
for row in rows():
 k=sum(v/s*1e6>=1 for v,s in zip(row,sums))
 for threshold in retained:retained[threshold]+=k>=threshold
result={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'hostname':socket.gethostname(),'input':str(p),'input_sha256':h,'canonical_receipt_sha256':hashlib.sha256((ROOT/'runs/results45-data-prepare-10372571/result.json').read_bytes()).hexdigest(),'genes':n,'samples':174,'library_min':min(sums),'library_max':max(sums),'retained_CPM_ge_1_by_min_samples':retained,'scope':'Canonical raw-count arithmetic, no grading or outcome changes'}
out=Path('/data/user_data/aydanh/rubric_gen/runs')/f"cue-filter-data-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False);(out/'result.json').write_text(json.dumps(result,indent=2));(ROOT/'docs/reports/2026-09-09/cue-filter-data-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
