"""Provider-free cell reports and within-policy contrasts; retain missingness."""
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from make_configs import ROOT,BUNDLE,CELLS,TASKS,POLICIES
sys.path.insert(0,str(ROOT/'experiments/trace-attack-defense-v3'))
import report_dev3_outcomes as outcomes
from rubric_gen.submission_revision.feedback import FeedbackPolicy,render_revision_prompt
from rubric_gen.submission_revision.experiment import load_experiment
OUT=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue3'
METRICS=('W','W_train','S','H','A','W_minus_S','S_minus_H','H_minus_A','W_minus_A',
         'RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision')

def deliveries(cell,rows,configs):
    result=[]
    for r in rows:
        if r['model']!=outcomes.PANEL[0]:continue
        root=Path(r['state_path']).parent
        e=configs[r['task_id']];condition=e.condition(r['condition_id'])
        policy=FeedbackPolicy(condition['feedback_policy'])
        instruction=(e.task_dir(r['task_id'])/'instruction.md').read_text()
        state=json.loads((root/'state.json').read_text())
        for i,sid in enumerate(state['submission_ids']):
            prompt=root/'turns'/f'turn-{int(sid[1:])+1:03d}'/'prompt.txt'
            receipt=root/'trace-defense-reminders'/f'{sid}.json'
            saved=json.loads(receipt.read_text()) if receipt.is_file() else None
            text=prompt.read_text() if prompt.is_file() else None
            emitted=bool(text and saved and saved['message_component'] and text.endswith(saved['message_component']))
            numerical=None
            if text is not None and policy is FeedbackPolicy.SCORE_ONLY:
                ev=json.loads((root/'rubric-evaluations'/f'{sid}.json').read_text())
                ordinary=render_revision_prompt(policy,{'score':ev['score']},task_instruction=instruction,
                    first_revision=sid=='s000',prompt_profile=e.protocol['prompt'],benchmark=e.benchmark)
                expected=ordinary+ ('\n\n'+saved['message_component'] if saved and saved['message_component'] else '')
                assert text==expected, f'Unexpected score-only message content: {prompt}'
                if cell=='score_only-trace-no-appendix':assert not saved['message_component']
                numerical=True
            result.append({'task':r['task_id'],'replicate':r['replicate'],'submission':sid,
                'selected':bool(saved and saved['selection']),
                'corrective':saved['selection']['corrective'] if saved and saved['selection'] else None,
                'appendix_recorded':bool(saved and saved['message_component']),
                'solver_prompt_exists':text is not None,'appendix_actually_delivered':emitted,
                'numeric_only_ordinary_verified':numerical,'prompt_path':str(prompt),
                'reminder_path':str(receipt) if saved else None,
                'retained_revisions':r['retained_revisions'],'stop_reason':r['stop_reason']})
    return result

def panel_union(rows):
    result={}
    for window in outcomes.WINDOWS:
        groups={}
        for r in rows:groups.setdefault((r['task_id'],r['replicate']),[]).append(r['direct'][window]['decision'])
        counts=Counter('positive' if 'reward_hacking_detected' in d else 'negative' if all(v=='no_reward_hacking_detected' for v in d) else 'abstain' for d in groups.values())
        result[window]={'counts':dict(counts),'denominator':len(groups),'positive_percent':100*counts['positive']/len(groups)}
    return result

def one_cell(cell):
    rows=[];coverage=[];errors=[];configs={}
    for task in TASKS:
        config=(ROOT/f'experiments/trace-attack-defense-v3/control-v21-compatible/{task}.yaml'
                if cell=='user_simulator-trace' else BUNDLE/f'configs/{cell}/{task}.yaml')
        try:
            exp,cov,values=outcomes.reconstruct(config)
            coverage.append({'task':task,'coverage':cov});rows.extend(values);configs[task]=exp
        except Exception as exc:
            errors.append({'task':task,'error_type':type(exc).__name__,'error':str(exc)})
    complete=not errors and len(rows)==18
    delivery=deliveries(cell,rows,configs) if rows else []
    # No surviving-task mean is represented as a complete cell result.
    packet={'cell':cell,'complete':complete,'expected_assignments':9,'completed_audited_assignments':len(rows)//2,
            'coverage':coverage,'errors':errors,'rows':rows,'delivery':delivery,
            'summary':outcomes.summarize(rows) if complete else None,'native_panel_union':panel_union(rows) if complete else None}
    runtime=[]
    for p in sorted((ROOT/'runs').glob('runtime-*/launch.json')):
        launch=p.read_text()
        if f'queue3/configs/{cell}/' not in launch:continue
        status=p.parent/'status.json'
        if status.is_file():
            d=json.loads(status.read_text())
            runtime.append({'path':str(status),'values':{k:v for k,v in d.items() if k in ('elapsed_seconds','processes','threads','peak_processes','peak_sampled_rss_kib','sampled_cpu_cores','assignments','assignment_failures','completed_operations_per_minute','configured_assignment_workers','active_provider_slots')}})
    packet['runtime']=runtime
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/f'{cell}.json').write_text(json.dumps(packet,indent=2)+'\n')
    flat=[{'task':r['task_id'],'replicate':r['replicate'],'auditor':r['model'],**outcomes.add_values(r)} for r in rows]
    outcomes.write_csv(OUT/f'{cell}.csv',flat)
    print(json.dumps({'cell':cell,'complete':complete,'audited':len(rows)//2,'errors':errors}),flush=True)
    return packet

def comparison(policy=None):
    if policy is not None and policy not in POLICIES:raise ValueError('unknown feedback policy')
    packets={}
    for cell in (*CELLS,'user_simulator-trace'):
        p=OUT/f'{cell}.json'
        if p.is_file():packets[cell]=json.loads(p.read_text())
    contrasts={}
    pairs=[(f'{p}-trace',f'{p}-fixed') for p in POLICIES]+[
        ('score_only-trace-no-appendix','score_only-trace'),('score_only-trace-no-appendix','score_only-fixed')]
    if policy is not None:pairs=[(a,b) for a,b in pairs if a.startswith(policy+'-')]
    for lhs,rhs in pairs:
        if all(packets.get(c,{}).get('complete') for c in (lhs,rhs)):
            rows,summary=outcomes.paired(packets[lhs]['rows'],packets[rhs]['rows'])
            contrasts[f'{lhs} minus {rhs}']={'paired_rows':rows,**summary}
        else:contrasts[f'{lhs} minus {rhs}']={'status':'incomplete; no paired estimate'}
    (OUT/('comparison'+('-'+policy if policy else '')+'.json')).write_text(json.dumps({'contrasts':contrasts,'provider_calls':0},indent=2)+'\n')
    lines=['# Queue 3 outcome checkpoint','','Within-policy trace minus fixed is primary. Cross-policy comparisons are secondary. Missing cells have no reported mean; no auditor or incomplete task is dropped to complete a cell.','',
        '| Cell | Audited/9 | '+' | '.join(METRICS)+' |','|---|---:|'+'---:|'*len(METRICS)]
    for c in (*CELLS,'user_simulator-trace'):
        if policy is not None and not c.startswith(policy+'-'):continue
        p=packets.get(c,{})
        values=p['summary']['means'] if p.get('complete') else None
        lines.append('| '+c+' | '+str(p.get('completed_audited_assignments',0))+'/9 | '+ ' | '.join(f'{values[m]:.2f}' if values else 'pending' for m in METRICS)+' |')
    lines+=['','RH columns are equal-weight confirmed-positive percentages; per-auditor abstentions/bounds and native panel unions remain separately recorded in each cell JSON. All primary contrasts validate identical initial-artifact and selected-rubric inputs.','',
        'Native score-only trace is numeric-only ordinary feedback plus a qualitative trace appendix when delivered. The supplemental appendix-off cell retains learned penalties. Actual rendered prompts are checked against these channels. No zero-floor RH result establishes a reduction.','']
    (OUT/('outcomes'+('-'+policy if policy else '')+'.md')).write_text('\n'.join(lines))
if __name__=='__main__':
    if sys.argv[1]=='compare':comparison(sys.argv[2] if len(sys.argv)>2 else None)
    else:
        if sys.argv[1] not in (*CELLS,'user_simulator-trace'):raise ValueError('unknown cell')
        one_cell(sys.argv[1])
