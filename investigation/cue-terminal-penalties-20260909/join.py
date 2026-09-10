from pathlib import Path
import json,hashlib,collections,statistics
R=Path('/home/aydanh/repos/rubric_gen');D=R/'docs/reports/2026-09-09'
paths=[D/'rubric-cue-gap-census.json',D/'rubric-cue-penalty-census.json'];g,p=[json.loads(x.read_text()) for x in paths]
assert hashlib.sha256(Path(g['source']).read_bytes()).hexdigest()==g['source_sha256']
idx={(x['task'],x['replicate']):x for x in p['assignments']};assert len(idx)==60 and len(g['cases'])==120
rows=[];groups=collections.defaultdict(list)
for c in g['cases']:
 a=idx[(c['task'],c['replicate'])];group='no criteria' if a['criteria']==0 else 'criteria, never penalized' if not a['penalized_checkpoints'] else 'ever penalized'
 row=dict(task=c['task'],replicate=c['replicate'],auditor=c['model'],group=group,delta=c['delta']);rows.append(row);groups[group].append(row)
summary={k:dict(assignments=len(v)//2,delta={m:statistics.mean(x['delta'][m] for x in v) for m in ['W','S','A','WS','WA']}) for k,v in groups.items()}
(D/'cue-coverage-gap-join.json').write_text(json.dumps(dict(source_hashes={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in paths},summary=summary,rows=rows),indent=2)+'\n')
lines=['# Criterion coverage and paired gap changes','','2026-09-09 10:02 EDT. Descriptive join of all60frozen cue assignments, two auditors each. Groups are defined by trace treatment exposure, not random assignment. These are post-treatment associations, not causal penalty effects. No exclusions or endpoint changes.','','| Trace exposure | Assignments | ΔW | ΔS | ΔA | Δ(W−S) | Δ(W−A) |','|---|---:|---:|---:|---:|---:|---:|']
for k,v in summary.items():lines.append('| '+k+' | '+str(v['assignments'])+' | '+' | '.join(f'{v["delta"][m]:.3f}' for m in ['W','S','A','WS','WA'])+' |')
lines+=['','The25criteria-but-never-penalized assignments contribute the adverse aggregate gap direction; the other groups improve on average. This locates a diagnostic stratum, not a causal explanation or license to exclude cases. Separate irrelevant/incomplete learned criteria from lenient/mistaken application.','', 'Inspect highest paired W−A deterioration cases in this stratum: da15-1rep3 and da14-8rep3 (both+50), da18-7rep3 (+34.5), da18-7rep1 (+26), da19-6rep3 (+23). Selection is diagnostic and outcome-informed; any subsequent experiment must retain all tasks and use prospective endpoints. Include favorable cases to test whether the suspected mechanism distinguishes failures.','','[Complete joined rows](cue-coverage-gap-join.json). No new scientific completion checkbox is supported.']
(D/'cue-coverage-gap-join.md').write_text('\n'.join(lines)+'\n')
