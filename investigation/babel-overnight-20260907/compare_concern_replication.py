"""Matched hard-task comparison after native concern1 replication coverage passes."""
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from analyze_babel import aggregate,paired_contrast,digest
ROOT=HERE.parents[1]
RUNS=ROOT/'runs/babel-overnight-20260907'


def selected_rows(report,labels):
    rows=[]
    for label,target in labels.items():
        selected=[r for r in report['rows'] if r['task_id']=='da-11-1' and r['analysis_condition']==label]
        assert len(selected)==6, 'complete three-seed two-auditor population required'
        assert {(r['replicate'],r['model']) for r in selected}=={(rep,model) for rep in (1,2,3) for model in ('gpt-5.6-sol','claude-opus-5')}
        for row in selected:
            for p,h in [('state_path','state_sha256'),('score_composition_path','score_composition_sha256')]:
                assert digest(Path(row[p]))==row[h], 'validated source changed'
            rows.append(dict(row,analysis_condition=target))
    return rows


def main():
    paths=[RUNS/'analysis-concern1-paired-10352036/analysis.json',RUNS/'analysis-concern1-replication-10356343/analysis.json']
    reports=[json.loads(p.read_text()) for p in paths]
    assert all(r['analysis_source_sha256']==digest(HERE/'analyze_babel.py') for r in reports)
    assert reports[0]['definitions']==reports[1]['definitions']
    labels=[{'control/full-static':'original/full-static','control/user-simulator-static':'original/user-simulator-static','concern1/user-simulator-static':'original-concern1/user-simulator-static'}, {'user-simulator-static':'replication-concern1/user-simulator-static'}]
    rows=[]
    for report,label in zip(reports,labels,strict=True):rows.extend(selected_rows(report,label))
    assert len({(r['state_path'],r['model']) for r in rows})==24
    panel=['gpt-5.6-sol','claude-opus-5']
    conditions,distributions=aggregate(rows,panel)
    treatment='replication-concern1/user-simulator-static'
    contrasts={f'{treatment} minus {control}':paired_contrast(rows,treatment,control,panel) for control in ('original-concern1/user-simulator-static','original/user-simulator-static')}
    result=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts=contrasts,definitions=reports[0]['definitions'],analysis_source_sha256=digest(HERE/'analyze_babel.py'),comparison_source_sha256=digest(Path(__file__)),input_reports=[dict(path=str(p),sha256=digest(p),selected_labels=label,selected_task='da-11-1') for p,label in zip(paths,labels,strict=True)],limitations='Each input was validated with its native frozen source. This is explicit population selection from a native multi-cohort report,not a resume compatibility claim. Same three saved seeds on one task;no new independent tasks. Original full/user and concern1 controls retained;do not select favorable execution draws or alter quality guards.')
    out=RUNS/'analysis-concern1-repeat-comparison-10356343';out.mkdir(exist_ok=False)
    (out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:{m:v['mean'] for m,v in c['metrics'].items() if m in ('W','S','H','A','RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision')} for k,c in conditions.items()},indent=2))


if __name__=='__main__':main()
