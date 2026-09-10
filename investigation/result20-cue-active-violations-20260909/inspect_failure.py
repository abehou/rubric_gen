import pathlib,json,collections
b=pathlib.Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
o=next((b/'owners/trace-results20').glob('10373129-*'))
p=o/'result.json';print(p.read_text() if p.exists() else 'no receipt')
for p in o.glob('*.log'):print(p.name,p.read_text()[-10000:])
ss=[json.loads(p.read_text()) for p in (b/'trace/study').glob('*/experiments/*/*/*/*/state.json')]
print(dict(collections.Counter(s.get('phase') for s in ss)))
