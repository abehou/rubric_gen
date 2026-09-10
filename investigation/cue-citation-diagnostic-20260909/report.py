"""Summarize complete stage-only diagnostic without behavioral claims."""
from pathlib import Path
import collections,hashlib,json
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/cue-citation-diagnostic-10370826'
d=json.loads((BASE/'result.json').read_text());assert d['success'] and d['source_unchanged'] and len(d['results'])==8
lines=['# Cue citation-precision diagnostic: no admitted criteria','','Job10370826; frozen base0fbe0bb, diagnostic implementationde36226. Four saved online contexts, fresh matched control versus the one citation clarification. No revisions or outcome audits.','','| Task / replicate | Arm | Proposed | Admitted | Admission failures |','|---|---|---:|---:|---|']
for r in d['results']:
 counts=collections.Counter(x['reason'] for x in r['decisions']);lines.append(f"| {r['task']}/{r['replicate']} | {r['arm']} | {r['proposed']} | {r['accepted']} | {dict(counts)} |")
outputs=list(BASE.glob('*/calls/*/output-*.json'));fail=list(BASE.glob('*/calls/*/failure-*.json'));assert len(outputs)==96 and not fail
validation_calls=0
for p in BASE.glob('*/calls/*/request.json'):
 r=json.loads(p.read_text())
 if r['stage']=='validation':
  e=json.loads(r['evidence']);assert set(e)=={'task','current_rubric','current_active_criteria','candidates','artifacts'} and len(e['artifacts'])==1
  for c in e['candidates']:assert 'provenance_pair_ids' not in c['criterion']
  validation_calls+=1
lines += ['',f'All8cells complete; {len(outputs)}successful provider calls, including{validation_calls}independent single-artifact validations;0recorded failures. Recorded validation payloads contain no pair/preference/provenance fields. Both arms keep frozen provider/model/settings, scoring and admission safeguards.','','## Mechanism and decision','','The clarification produces fewer candidates in da12-4 but does not turn the diagnosed citation behavior into effective exposure. Every modified-prompt candidate fails criterion support. Fresh controls also admit none; three control candidates pass initial support but fail global margin checks. This does not show that the new policy reduces or increases RH: no criteria are admitted in this diagnostic and no solver ran.','','Stop this prompt candidate before revisions. Do not relax validation or claim success from shorter citation lists. The prior native replay operated on fixed original proposals and original application judgments; these fresh calls changed both proposals and their independently generated applications. Therefore this diagnostic cannot yet distinguish proposal variability from application-judge instability. The minimum next diagnostic is an exact saved-candidate validation repeat, preserving original candidate text and all original blind artifact inputs; no new induction, revision or outcome audit.','','The contexts were selected for this failure mechanism, so these counts cannot estimate overall Result20 admission rates. Original outputs, fresh controls and all negative cells remain preserved.','','[Prospective plan](cue-citation-diagnostic-plan.md) · [Policy decision note](cue-citation-policy-decision.md) · [Original native replay](rubric-cue-support-replay.md)','','Result SHA256: `'+hashlib.sha256((BASE/'result.json').read_bytes()).hexdigest()+'`.','']
p=ROOT/'docs/reports/2026-09-09/cue-citation-diagnostic-result.md'
with p.open('x') as f:f.write('\n'.join(lines))
print('Complete diagnostic report written; no revision promotion')
