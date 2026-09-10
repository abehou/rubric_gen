"""Render verified numeric analysis into a CLI-readable Markdown checkpoint."""
import hashlib,json,os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path('/home/aydanh/repos/rubric_gen')
source=ROOT/'runs/babel-result20-current-20260908/report-v2/analysis.json'
receipt=json.loads(source.with_name('combination-receipt.json').read_text())
assert receipt['success'] and receipt['source_unchanged']
raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()==receipt['analysis_sha256']
data=json.loads(raw);assert len(data['rows'])==480 and len(data['coverage'])==4
for c in data['coverage']:assert c['assignment_count']==60
conditions=['full-static','user-simulator-static','full-red-team-trace','user-simulator-red-team-trace']
labels=['Full-feedback static','User-simulator static','Full-feedback trace','User-simulator trace']
def formatted(metric,percent=False):
 scale=100 if percent else 1
 lo,hi=metric['identification_bounds']
 if lo==hi:return f'{lo*scale:.2f}'+('%' if percent else '')
 return f'{lo*scale:.2f}–{hi*scale:.2f}'+('%' if percent else '')
def interval(metric,percent=False):
 scale=100 if percent else 1
 lo,hi=metric['task_bootstrap_95_interval'];return f'[{lo*scale:.2f}, {hi*scale:.2f}]'
lines=['# Complete four-condition BioMNIBench Result20', '',datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M %Z'),'',
'Coverage: **240 assignments, 20 tasks × 3 replicates × 4 conditions**, with complete configured GPT-5.6 Sol and Claude Opus 5 native audits. Gemini is not included. This is completion of the requested comparison, not proof of the desired scientific pattern.','',
'## Scores and gaps','', '| Condition | W | W_train | S | H | A | W−S | S−H | H−A | W−A | Quality gain |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for c,label in zip(conditions,labels):
 metrics=data['conditions'][c+'/matched-panel']['metrics'];lines.append('| '+label+' | '+' | '.join(formatted(metrics[k]) for k in ['W','W_train','S','H','A','WS','SH','HA','WA','quality_gain'])+' |')
lines+=['','W is the selected-base weak score; W_train includes elicited penalties. A is rubric-free holistic quality. Score improvements and penalty-induced reward changes must be distinguished.','', '## Direct reward hacking','', 'Ranges are abstention identification bounds, not confidence intervals. Matched-panel RH uses the frozen analysis aggregation. Full trajectory, post-update, final-artifact and final-revision windows are different endpoints.','', '| Condition / auditor | Full trajectory | Post-update | Final artifact | Final revision |','|---|---:|---:|---:|---:|']
for c,label in zip(conditions,labels):
 for model in ['gpt-5.6-sol','claude-opus-5','matched-panel']:
  m=data['conditions'][c+'/'+model]['metrics'];lines.append('| '+label+' / '+model+' | '+' | '.join(formatted(m[k],True) for k in ['RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision'])+' |')
lines+=['','## Paired contrasts','', 'Signs follow **left minus right**. RH contrasts are percentage points; uncertainty is the frozen task-bootstrap 95% interval. Intervals including zero do not establish a directional effect.','', '| Contrast | Metric | Difference / bounds | 95% interval |','|---|---|---:|---:|']
for name,panels in data['contrasts'].items():
 metrics=panels['matched-panel']['metrics']
 for k in ['RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision','A','WS','SH','HA','WA']:
  m=metrics[k];percent=k.startswith('RH_');lines.append(f'| {name} | {k} | {formatted(m,percent)} | {interval(m,percent)} |')
lines+=['','## Interpretation and next decision','', 'Read the user-static minus user-trace contrast first: a positive RH difference favors the trace policy, whereas a positive A difference means the trace policy has lower holistic quality. A full-trajectory reduction alone is insufficient if later RH worsens or quality collapses.','', 'Before assigning a mechanism, inspect criterion admission, actual penalties, feedback delivery, revision timing, auditor disagreement and recovery exposure. Keep all assignments in the declared analysis. Choose one targeted matched dev3 change from that evidence; do not adjust detector thresholds or switch evaluators.','', '## Provenance and detailed distributions','', '[Validated analysis, individual rows, monitor distributions and uncertainty](../../../runs/babel-result20-current-20260908/report-v2/analysis.json). The analysis records each native producer and source seal. [Execution ledger](../../../EXPERIMENT_RUNS.md) retains job/config/output history.','',f'Analysis SHA-256: `{hashlib.sha256(raw).hexdigest()}`. Markdown job: `{os.environ["SLURM_JOB_ID"]}`.','']
out=ROOT/'docs/reports/2026-09-08/result20-four-condition.md'
with out.open('x') as f:f.write('\n'.join(lines))
print(str(out))
