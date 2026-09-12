"""Provider-free selected-criterion and feedback evidence from the nine-case control."""
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path('/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/queue2/diagnostics')


def read(path):
    return json.loads(path.read_text())


rows = read(ROOT/'docs/reports/2026-09-12/trace-user-parallel-diagnostics/control-outcomes.json')['rows']
cases = {}
for row in rows:
    key = f"{row['task_id']}/rep-{row['replicate']:03d}"
    exp = Path(row['state_path']).parent
    audit = Path(row['quality_path']).parents[2]
    evaluation = read(Path(row['score_composition_path']))
    weak = exp/'judgments'/row['submission_id']/evaluation['feedback_reference']['rubric_sha256']
    summary = read(audit/'rubric_score/summary.json')
    selected = [r for r in summary['records'] if r['assignment_id']==row['assignment_id']
                and r['model']==row['model'] and r['artifact']=='final'
                and any(x['name']=='selected' for x in r['rubric_roles'])]
    assert len(selected)==1
    raw_path = audit/'rubric_score/records'/f"{selected[0]['judgment_key']}.json"
    raw = read(raw_path)
    assert raw['rubric_sha256']==evaluation['feedback_reference']['rubric_sha256']
    if key not in cases:
        turns=[]
        state=read(exp/'state.json')
        for sid in state['submission_ids']:
            ws=exp/'submissions'/sid/'workspace'
            public='\n'.join(f'FILE {n}\n'+(ws/n).read_text() for n in ('answer.txt','trace.md'))
            feedback_path=exp/'feedback-generations'/f'{sid}.json'
            reminder_path=exp/'trace-defense-reminders'/f'{sid}.json'
            prompt_path=exp/'turns'/f'turn-{int(sid[1:])+1:03d}'/'prompt.txt'
            changes='' if not turns else '\n'.join(difflib.unified_diff(previous.splitlines(),public.splitlines()))
            feedback=read(feedback_path) if feedback_path.is_file() else None
            turns.append({'submission_id':sid,'public_paths':[str(ws/n) for n in ('answer.txt','trace.md')],
                'public_change_from_previous':changes[:10000], 'change_chars':len(changes),
                'feedback_path':str(feedback_path),'feedback_output':feedback.get('output') if feedback else None,
                'reminder_path':str(reminder_path),'reminder':read(reminder_path) if reminder_path.is_file() else None,
                'solver_prompt_path':str(prompt_path),'solver_prompt':prompt_path.read_text() if prompt_path.is_file() else None})
            previous=public
        cases[key]={'task_id':row['task_id'],'replicate':row['replicate'],'root':str(exp),
            'weak_path':str(weak/'evaluation.json'),'weak':read(weak/'evaluation.json'),
            'weak_validation':read(weak/'score_validation.json'),'strong':{},'outcomes':{},
            'final_public':public,'turns':turns}
    cases[key]['strong'][row['model']]={'path':str(raw_path),'record':raw,
        'evaluation':read(Path(raw['evaluation_path']))}
    cases[key]['outcomes'][row['model']]={'values':row['values'],'direct':row['direct']}

OUT.mkdir(parents=True,exist_ok=True)
(OUT/'control-evidence.json').write_text(json.dumps({'provider_calls':0,'cases':cases},indent=2)+'\n')
for key,case in cases.items():
    reminders=[t['reminder'] for t in case['turns'] if t['reminder']]
    print(json.dumps({'case':key,'weak_keys':list(case['weak']),'strong_keys':list(next(iter(case['strong'].values()))['record']),
        'reminders':len(reminders),'selected':sum(r['selection'] is not None for r in reminders),
        'corrective':sum(bool(r['selection'] and r['selection']['corrective']) for r in reminders),
        'prompt_exposures':sum(bool(t['solver_prompt']) for t in case['turns']),
        'W_S':{model:out['values']['W_minus_S'] for model,out in case['outcomes'].items()}}))
