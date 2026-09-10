import pathlib,json,collections,hashlib
b=pathlib.Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/trace/study')
for p in b.glob('*/experiments/*/*/*/*/state.json'):
 s=json.loads(p.read_text())
 if s['phase']=='completed':continue
 print('assignment',str(p.parent),'state',s)
 print('children',[x.name for x in p.parent.iterdir()])
 m=json.loads((p.parent/'manifest.json').read_text());print('manifest',m)
 for q in p.parent.glob('red-team/*/*.json'):
  print('sidecar',str(q.relative_to(p.parent)),q.read_text()[:2500])
