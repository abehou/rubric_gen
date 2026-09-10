"""Read-only command failure signals in canonical, completed revision trajectories."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def command_signals(events):
    counts=Counter();errors=Counter();seen=set()
    for index,event in enumerate(events):
        item=event.get('item',{})
        if event.get('type')!='item.completed' or item.get('type')!='command_execution':continue
        key=item.get('id') or ('line',index)
        if key in seen:continue
        seen.add(key);counts['completed_command_records']+=1
        code=item.get('exit_code')
        if type(code) is not int:
            counts['unknown_exit_code']+=1;continue
        if code==0:counts['zero_exit']+=1;continue
        counts['nonzero_exit']+=1
        output=item.get('aggregated_output','')
        names=set(re.findall(r'^\s*([A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception)):',str(output),re.M))
        errors.update(names or ['no_named_python_exception'])
        if code in (137,143,-9,-15):counts['termination_exit_not_proof_of_oom']+=1
        if re.search(r'\b(?:Killed|out of memory|timed out)\b',str(output),re.I):counts['resource_or_timeout_text_not_verified']+=1
    return dict(counts),dict(errors)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis',type=Path,action='append',required=True)
    parser.add_argument('--label',action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();assert len(args.analysis)==len(args.label)
    rows=[];seen=set();groups={}
    for report,label in zip(args.analysis,args.label,strict=True):
        source=json.loads(report.read_text())
        for row in source['rows']:
            state=Path(row['state_path']);key=str(state.resolve())
            if key in seen:continue
            seen.add(key);assert digest(state)==row['state_sha256']
            cohort=label+'/'+row.get('analysis_condition',row['condition_id'])
            counts=Counter();errors=Counter();files=[]
            for path in sorted(state.parent.glob('turns/*/trajectory.stream.jsonl')):
                events=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                c,e=command_signals(events);counts.update(c);errors.update(e)
                files.append(dict(path=str(path),sha256=digest(path)))
            record=dict(cohort=cohort,task_id=row['task_id'],replicate=row['replicate'],state_path=str(state),state_sha256=row['state_sha256'],turn_files=files,counts=dict(counts),exception_signals=dict(errors))
            rows.append(record)
            group=groups.setdefault(cohort+'/'+row['task_id'],dict(assignments=0,counts=Counter(),exception_signals=Counter()))
            group['assignments']+=1;group['counts'].update(counts);group['exception_signals'].update(errors)
    result=dict(rows=rows,groups=groups,source_sha256=digest(Path(__file__)),inputs=[dict(path=str(p),sha256=digest(p),label=l) for p,l in zip(args.analysis,args.label,strict=True)],limitations='Canonical completed revision turns only,excluding initial seeds and failed infrastructure attempts. Nonzero shell exits include harmless negative checks. Exception/termination text is a diagnostic signal,not proof of infrastructure failure,OOM,intent,or reward hacking. No commands or raw output are copied into this report.')
    args.output.mkdir(parents=True,exist_ok=False);(args.output/'execution-failures.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(groups,indent=2))


if __name__=='__main__':main()
