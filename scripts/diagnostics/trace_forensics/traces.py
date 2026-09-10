"""Index natural saved turns with original line references; never execute code."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collect import OUT, PUBLIC, read, sha, write, key


def extract(case):
    root=Path(case['root']); destination=OUT/'traces'/key(case)
    destination.mkdir(parents=True,exist_ok=True)
    index=[]; events=[]
    for path in sorted((root/'turns').glob('turn-*/trajectory.stream.jsonl')):
        turn=int(path.parent.name.split('-')[-1]); lines=path.read_text().splitlines()
        index.append(dict(turn=turn,path=str(path),sha256=sha(path),lines=len(lines)))
        for number,line in enumerate(lines,1):
            row=json.loads(line); item=row.get('item',{})
            if row.get('type') not in ('item.completed','item.started'):continue
            it=item.get('type')
            if it in ('user_message','reasoning'):continue
            text=''
            if it=='command_execution':
                text='COMMAND: '+str(item.get('command'))+'\nEXIT: '+str(item.get('exit_code'))+'\nOUTPUT:\n'+item.get('aggregated_output','')
            elif it=='file_change':
                text='\n'.join(str(c.get('path',''))+'\n'+str(c.get('diff',c)) for c in item.get('changes',[]))
            elif it=='agent_message':text=item.get('text','')
            else: text=json.dumps(item,ensure_ascii=False)
            events.append(dict(turn=turn,line=number,event=row['type'],item_type=it,
                item_id=item.get('id'),text=text))
    write(destination/'index.json',index)
    with (destination/'events.jsonl').open('w') as f:
        for event in events:f.write(json.dumps(event,ensure_ascii=False)+'\n')
    return dict(case=key(case),turns=len(index),events=len(events))


if __name__=='__main__':
    assert os.environ.get('SLURM_JOB_ID')
    cases=read(PUBLIC/'cases.json')
    wanted={(c['setting'],c['task_id'],c['replicate']) for c in cases
            if c['setting']=='user' and any(r['direct']['full_trajectory']['decision']=='reward_hacking_detected' for r in c['rows'])}
    selected=[c for c in cases if (c['setting'],c['task_id'],c['replicate']) in wanted]
    with ThreadPoolExecutor(max_workers=8) as pool:result=list(pool.map(extract,selected))
    write(PUBLIC/'trajectory-index.json',result)
    print(json.dumps(dict(cases=len(result),turns=sum(r['turns'] for r in result))))
