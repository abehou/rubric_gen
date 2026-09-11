"""Read-only compute-storage inventory; no provider calls."""
import csv,json,os
from pathlib import Path
r=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910')
with (r/'report/quote-binding-requests.csv').open() as f: rows=list(csv.DictReader(f))
print('job',os.environ['SLURM_JOB_ID'],'rows',len(rows),'fields',list(rows[0]))
for stage in ('quality','diagnosis','application'):
 row=next(x for x in rows if x['stage']==stage)
 print('row',row)
 d=json.loads(Path(row['path']).read_text());e=json.loads(d['request']['evidence'])
 print('stage',stage,'request',list(d['request']),'evidence',list(e),'outcome',list(d['outcome']))
 if stage=='diagnosis':
  print('currentcrit',e['current_criteria']);print('comparison',e['comparison'])
  root=Path(row['path']).parents[2]
  print('assignmentfiles',sorted(x.name for x in root.iterdir()))
  print('g0files',[x.name for x in (root/'rubric-generations/generation-0000').glob('*')])
for p in [Path('/home/aydanh/repos/rubric_gen/seeds/biomnibench/native-prompt-dev3'),Path('/home/aydanh/repos/rubric_gen/runs/rubric-paraphrases/biomnibench/red-team-dev3')]:
 print('dev input',str(p),p.exists(),list(p.glob('manifest.json')))
