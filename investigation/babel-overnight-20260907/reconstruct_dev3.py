"""Read-only reconstruction of selected-base W/S/H/A and direct RH evidence."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def local(value):
    return Path(value.replace('/Users/yuenanhuang/Desktop/rubric_gen',str(ROOT)))


def read(p):return json.loads(p.read_text())


def main():
    manifest=read(ROOT/'investigation/static-neutral-20260907/manifest.json')
    endpoints={}
    for config in manifest['configs']:
        study=local(config['study'])
        for record in read(study/'study.json')['records']:
            endpoints[config['tag'],record['assignment_id']]=study/record['experiment_dir']
    source=ROOT/'investigation/static-neutral-20260907/results.json'
    old=read(source)['rows']
    def reconstruct(r):
        path=endpoints[r['tag'],r['assignment']]/'state.json';state=read(path)
        assert state['submission_ids'][-1]==r['submission_id']
        W=state['scores'][-1]  # All these conditions are static; no learned penalties.
        assert state['fixed_original_scores'][-1]==r['weak']
        p=local(r['full_trajectory_path']);raw=read(p)
        row={k:r[k] for k in ('arm','task','replicate','condition','model','assignment')}
        row.update(W=W,S=r['selected'],H=r['holdout'],A=r['quality'],weak_master_legacy=r['weak'],strong_master=r['original'],
            WS=W-r['selected'],SH=r['selected']-r['holdout'],HA=r['holdout']-r['quality'],WA=W-r['quality'],
            full_trajectory_rh=r['full_trajectory_rh'],final_artifact_rh=r['final_artifact_rh'],verdict=raw['verdict'],evidence=raw['compact_evidence'],
            state_path=str(path.relative_to(ROOT)),state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),detector_path=str(p.relative_to(ROOT)))
        assert abs(row['WA']-(row['WS']+row['SH']+row['HA']))<1e-8
        return row
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(reconstruct,old))
    groups=[]
    for key in sorted({(r['arm'],r['condition'],r['model']) for r in rows}):
        selected=[r for r in rows if (r['arm'],r['condition'],r['model'])==key]
        groups.append(dict(arm=key[0],condition=key[1],model=key[2],n=len(selected),
            means={k:mean(r[k] for r in selected) for k in ('W','S','H','A','WS','SH','HA','WA','full_trajectory_rh','final_artifact_rh')},
            monitor_distribution=dict(sorted(Counter(r['verdict']['score'] for r in selected).items())),
            chunks=sum(r['verdict']['chunk_count'] for r in selected)))
    result=dict(definitions='W=state.scores final selected-base training score (all static); S=strong selected; H=mean strong heldouts2–4; A=strong rubric-free absolute quality. Historical weak_original and original-quality summaries are separate measurements.',source=str(source.relative_to(ROOT)),rows=rows,groups=groups)
    (HERE/'dev3-reconstruction.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(groups,indent=2))


if __name__=='__main__':main()
