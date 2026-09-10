import json,hashlib,os,re
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
a=json.loads((b/'comparison-recovered-v3/analysis.json').read_text())
cases={('da-15-1',2),('da-10-1',3),('da-15-2',2),('da-15-7',3)}
rows=[];seen=set()
pattern=re.compile(r'timed? out|timeout|Traceback|broadcast|placeholder|header.only|NB GLM|negative.binomial|limma.voom|make_artifacts|TMM|killed|Active rubric requirements',re.I)
for r in a['rows']:
 arm=r['analysis_condition'].split('/')[0];key=(arm,r['task_id'],r['replicate'])
 if arm not in {'active','trace'} or key in seen or key[1:] not in cases:continue
 seen.add(key);root=Path(r['state_path']).parent;turns=[]
 for turn in sorted((root/'turns').glob('turn-*')):
  sources=[]
  for p in turn.glob('*'):
   if not p.is_file() or p.suffix not in {'.jsonl','.txt'}:continue
   raw=p.read_bytes();text=raw.decode(errors='replace');hits=[]
   for i,line in enumerate(text.splitlines()):
    if pattern.search(line):hits.append(dict(line=i+1,text=line[:4500]))
   if hits:sources.append(dict(path=str(p),sha256=hashlib.sha256(raw).hexdigest(),matches=hits[:25],total_matches=len(hits)))
  turns.append(dict(turn=turn.name,sources=sources))
 rows.append(dict(arm=arm,task=key[1],replicate=key[2],root=str(root),turns=turns))
out=b/'case-evidence-v1';out.mkdir(exist_ok=False);(out/'evidence.json').write_text(json.dumps(rows,indent=2))
report=Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-active-case-index.json')
report.write_text(json.dumps([dict(arm=r['arm'],task=r['task'],replicate=r['replicate'],root=r['root'],turns=[dict(turn=t['turn'],sources=[dict(path=s['path'],sha256=s['sha256'],total_matches=s['total_matches'],examples=s['matches'][:2]) for s in t['sources']]) for t in r['turns']]) for r in rows],indent=2))
print('Matched cases',len(rows),'full evidence',out/'evidence.json','index',report)
