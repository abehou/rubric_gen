"""Deterministic case accounting for official RH-positive packets; no rescoring."""
import os, json
from pathlib import Path
from report_sources import PUBLIC, read, write

def main():
    assert os.environ.get('SLURM_JOB_ID')
    index = read(PUBLIC/'RH-positive-case-index.json')
    rows=[]
    for item in index:
        packet=read(item['packet_path'])
        auditors=packet['auditors']
        positive=[m for m,v in auditors.items() if v['decision']=='reward_hacking_detected']
        scores={m:v.get('score') for m,v in auditors.items()}
        reasons={m:v.get('reason') for m,v in auditors.items()}
        events=packet.get('events',[])
        rows.append({
            'assignment_id':item['assignment_id'],'arm':item['arm'],'task_id':item['task_id'],'replicate':item['replicate'],
            'positive_auditors':positive,'auditor_scores':scores,'auditor_rationales':reasons,
            'first_online_admission_generation':item.get('first_online_admission_generation'),
            'first_focused_reminder_turn':item.get('first_focused_reminder_turn'),
            'first_saved_public_event_turn':min((e.get('turn') for e in events if isinstance(e.get('turn'),int)),default=None),
            'saved_public_event_count':len(events),'packet_path':item['packet_path'],'packet_sha256':item['packet_sha256'],
            'interpretation':'official verdict and saved-event pointers only; no new RH rationale or event classification',
        })
    rows.sort(key=lambda x:x['assignment_id'])
    write(PUBLIC/'RH-positive-reviewed-cases.json',rows)
    (PUBLIC/'RH-positive-reviewed-cases.csv').write_text(
        'assignment_id,arm,task_id,replicate,positive_auditors,first_online_admission_generation,first_focused_reminder_turn,first_saved_public_event_turn,saved_public_event_count,packet_path\n'+
        ''.join(f"{r['assignment_id']},{r['arm']},{r['task_id']},{r['replicate']},\"{';'.join(r['positive_auditors'])}\",{r['first_online_admission_generation']},{r['first_focused_reminder_turn']},{r['first_saved_public_event_turn']},{r['saved_public_event_count']},\"{r['packet_path']}\"\n" for r in rows)
    )
    summary={'provider_calls':0,'positive_assignments':len(rows),'by_arm':{arm:sum(r['arm']==arm for r in rows) for arm in ('full','user')},'manual_event_interpretation':False,'rows_path':str(PUBLIC/'RH-positive-reviewed-cases.json')}
    write(PUBLIC/'RH-case-review-summary.json',summary)
    (PUBLIC/'RH-case-review.md').write_text('# RH-positive case accounting\n\nThis is a deterministic index over the official full-trajectory panel and saved trajectory packets. It reports auditor verdicts, scores, rationales, and availability/exposure pointers; it does not edit verdicts or infer a causal event.\n\n'+json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))
if __name__=='__main__': main()
