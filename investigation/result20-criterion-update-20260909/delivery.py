"""Read-only admission and actual submitted-prompt census after native completion."""
import json,hashlib,os
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/babel-result20-criterion-update-20260909'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    assert os.environ.get('SLURM_JOB_ID')
    receipt=next((BASE/'owners/audit-recovery-trace-results20').glob('10370740-*/result.json'))
    assert json.loads(receipt.read_text())['success']
    states=sorted((BASE/'trace/study').glob('*/experiments/*/rep-*/*/*/state.json'));assert len(states)==60
    rows=[]
    for state in states:
        r=state.parent;m=json.loads((r/'manifest.json').read_text());criteria={};notes=[]
        for p in sorted((r/'rubric-generations').glob('generation-*/criteria.json')):
            for c in json.loads(p.read_text()):criteria[c['criterion_id']]=c
        for p in sorted((r/'turns').glob('turn-*/prompt.txt')):
            text=p.read_text();marker='\n\n## Rubric update\n\n'
            if marker not in text:continue
            assert text.count(marker)==1
            note=text.split(marker,1)[1]
            matches=[k for k,c in criteria.items() if '- '+c['requirement']+'\n' in note]
            assert matches,'Update note without an admitted requirement'
            lines=[line[2:] for line in note.splitlines() if line.startswith('- ')]
            assert set(lines)=={criteria[k]['requirement'] for k in matches}
            notes.append(dict(prompt=str(p),sha256=sha(p),criterion_ids=matches,note=note))
        rows.append(dict(assignment_id=m['assignment_id'],task_id=m['task_id'],replicate=m['replicate'],state=str(state),state_sha256=sha(state),criteria=criteria,delivered_notes=notes))
    summary=dict(assignments=60,assignments_with_admitted_criteria=sum(bool(r['criteria']) for r in rows),assignments_with_submitted_update_note=sum(bool(r['delivered_notes']) for r in rows),submitted_update_notes=sum(len(r['delivered_notes']) for r in rows))
    out=BASE/'criterion-delivery-v1';out.mkdir(exist_ok=False)
    payload=dict(summary=summary,rows=rows,receipt_sha256=sha(receipt),script_sha256=sha(Path(__file__)),limitation='Saved submitted prompts establish delivery, not attention, compliance or causal mediation. Admission and delivery are post-treatment variables. Counts exclude attempt-file duplicates; inspect missing next turns before calling an undelivered admission a bug.')
    (out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
    (ROOT/'docs/reports/2026-09-09/criterion-update-delivery.md').write_text('# Criterion update delivery census\n\n```json\n'+json.dumps(summary,indent=2)+'\n```\n\n'+payload['limitation']+'\n\nFull source-linked records: `runs/babel-result20-criterion-update-20260909/criterion-delivery-v1/analysis.json`.\n')
if __name__=='__main__':main()
