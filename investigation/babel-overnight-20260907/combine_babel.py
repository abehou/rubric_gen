"""Combine reports validated under their own frozen code, never rewrite run identity."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from analyze_babel import aggregate, paired_contrast, digest


def combine(reports,labels,source_sha):
    rows=[];coverage=[];definitions=None
    for report,label in zip(reports,labels,strict=True):
        assert report['analysis_source_sha256']==source_sha, 'analysis definitions changed'
        if definitions is None:definitions=report['definitions']
        assert report['definitions']==definitions
        seen=set()
        for row in report['rows']:
            key=(row['condition_id'],row['task_id'],row['replicate'],row['model'])
            assert key not in seen, 'input must be a single native cohort, not an already combined comparison'
            seen.add(key)
            for path_key,sha_key in [('state_path','state_sha256'),('score_composition_path','score_composition_sha256')]:
                assert digest(Path(row[path_key]))==row[sha_key], 'source artifact changed since native validation'
            value=dict(row);value['analysis_condition']=f"{label}/{row['condition_id']}";rows.append(value)
        coverage.extend(report['coverage'])
    return rows,coverage,definitions


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',type=Path,action='append',required=True)
    p.add_argument('--label',action='append',required=True)
    p.add_argument('--contrast',nargs=2,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();assert len(a.analysis)==len(a.label) and len(set(a.label))==len(a.label)
    inputs=[json.loads(path.read_text()) for path in a.analysis]
    source_sha=digest(HERE/'analyze_babel.py')
    rows,coverage,definitions=combine(inputs,a.label,source_sha)
    panel=['gpt-5.6-sol','claude-opus-5']
    conditions,distributions=aggregate(rows,panel)
    contrasts={f'{left} minus {right}':paired_contrast(rows,left,right,panel) for left,right in a.contrast}
    result=dict(rows=rows,coverage=coverage,conditions=conditions,monitor_distributions=distributions,
        contrasts=contrasts,definitions=definitions,uncertainty=inputs[0]['uncertainty'],
        analysis_source_sha256=source_sha,combination_source_sha256=digest(Path(__file__)),
        input_reports=[dict(path=str(path.resolve()),sha256=digest(path),label=label) for path,label in zip(a.analysis,a.label,strict=True)],
        validation='Each input was reconstructed with its own compatible frozen native code. This read-only combination does not claim cross-version or cross-machine resume compatibility.')
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in contrasts.items()},indent=2))


if __name__=='__main__':main()
