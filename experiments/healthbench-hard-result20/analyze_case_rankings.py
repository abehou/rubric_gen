"""Offline, exploratory gap/RH association; no provider calls or relabeling."""
import json
from pathlib import Path
from collections import Counter, defaultdict
from rubric_gen.runtime.process_environment import install_controlled_process_environment

install_controlled_process_environment()
import numpy as np
HERE = Path(__file__).resolve().parent
GAPS = ['W-S', 'S-H', 'H-A']

def rankdata(x):
    _, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    return (np.cumsum(counts) - (counts - 1) / 2)[inverse]

def roc_auc_score(y, x):
    n = int(np.sum(y)); m = len(y)-n
    return (rankdata(x)[y].sum()-n*(n+1)/2)/(n*m)

def average_precision_score(y, x):
    order=np.argsort(-x); y=y[order]; x=x[order]
    end=np.r_[np.flatnonzero(np.diff(x)),len(x)-1]
    tp=np.cumsum(y)[end]; recall=tp/y.sum()
    return np.sum(np.diff(np.r_[0.,recall])*tp/(end+1))

def logistic_prediction(x, y, test):
    scale=x.std(axis=0); scale[scale==0]=1; center=x.mean(axis=0)
    design=np.column_stack([np.ones(len(x)),(x-center)/scale])
    query=np.column_stack([np.ones(len(test)),(test-center)/scale])
    beta=np.zeros(design.shape[1]); penalty=np.eye(len(beta));penalty[0,0]=0
    for _ in range(50):
        probability=1/(1+np.exp(-np.clip(np.einsum('ij,j->i',design,beta),-40,40)))
        gradient=np.einsum('ij,i->j',design,probability-y)+np.einsum('ij,j->i',penalty,beta)
        hessian=np.einsum('ij,ik,i->jk',design,design,probability*(1-probability))+penalty
        step=np.linalg.solve(hessian,gradient);beta-=step
        assert np.all(np.isfinite(beta))
        if np.max(np.abs(step))<1e-8:break
    assert np.max(np.abs(step))<1e-6, 'logistic fit did not converge'
    return 1/(1+np.exp(-np.clip(np.einsum('ij,j->i',query,beta),-40,40)))

def correlation(x, y):
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    return float(np.corrcoef(rankdata(x), rankdata(y))[0,1])

def main():
    rows = [json.loads(s) for s in (HERE/'matrix-case-metrics.jsonl').read_text().splitlines()]
    assert len(rows) == 480
    tasks = np.array([r['task'] for r in rows])
    conditions = np.array([r['condition'] for r in rows])
    x = np.array([[r[k] for k in GAPS] for r in rows])
    # Equal-rank average is exploratory and untrained; the signed sum is W-A.
    scores = {k:x[:,i] for i,k in enumerate(GAPS)}
    scores['signed_sum_W-A'] = x.sum(axis=1)
    scores['equal_rank_mean'] = np.mean([rankdata(x[:,i]) for i in range(3)], axis=0)
    result = {'n':len(rows),'tasks':len(set(tasks)), 'windows':{}}
    rng = np.random.default_rng(20260927)
    groups = [np.flatnonzero(tasks==t) for t in sorted(set(tasks))]
    boot = [np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))]) for _ in range(2000)]
    for window in ('full_trajectory','final_revision','final_artifact'):
        y=np.array([r[window]['score'] for r in rows])
        valid=y!=5; positive=y>5
        entry={'counts':dict(Counter(r[window]['decision'] for r in rows)),
               'positive_tasks':dict(Counter(tasks[positive])), 'correlations':{},'within_condition':{}}
        for key,v in scores.items():
            vals=[correlation(v[idx],y[idx]) for idx in boot]
            vals=[v for v in vals if v is not None]
            entry['correlations'][key]={'spearman':correlation(v,y),
                'task_cluster_bootstrap_95_percentile':np.quantile(vals,[.025,.975]).tolist() if vals else None,
                'binary_auroc_excluding_abstain':float(roc_auc_score(positive[valid],v[valid])) if len(set(positive[valid]))==2 else None}
        for condition in sorted(set(conditions)):
            ix=conditions==condition
            entry['within_condition'][condition]={k:correlation(v[ix],y[ix]) for k,v in scores.items()}
        # Remove condition mean differences from ranks to expose ecological confounding.
        ry=rankdata(y)
        yr=ry.copy()
        for c in set(conditions): yr[conditions==c]-=ry[conditions==c].mean()
        entry['condition_demeaned_rank_correlation']={}
        for k,v in scores.items():
            rv=rankdata(v); vr=rv.copy()
            for c in set(conditions):vr[conditions==c]-=rv[conditions==c].mean()
            entry['condition_demeaned_rank_correlation'][k]=float(np.corrcoef(vr,yr)[0,1]) if np.ptp(yr)>0 else None
        result['windows'][window]=entry
    # Averages over three replicates: 160 task/condition cells, not eight condition means.
    grouped=defaultdict(list)
    for r in rows:grouped[(r['task'],r['condition'])].append(r)
    y=np.array([np.mean([r['full_trajectory']['score'] for r in rr]) for rr in grouped.values()])
    result['task_condition_mean_spearman']={k:correlation(np.array([np.mean([r[k] for r in rr]) for rr in grouped.values()]),y) for k in GAPS}
    # Exploratory fixed-regularization model, held-out whole tasks; no tuning.
    y=np.array([r['full_trajectory']['score']>5 for r in rows]);valid=np.array([r['full_trajectory']['score']!=5 for r in rows])
    onehot=np.array([[float(c==r['condition']) for c in sorted(set(conditions))] for r in rows])
    result['leave_one_task_out']={}
    for name,features in [('three_gaps',x),('condition_only',onehot),('gaps_and_condition',np.column_stack([x,onehot]))]:
        pred=np.full(len(rows),np.nan)
        for t in sorted(set(tasks)):
            train=(tasks!=t)&valid;test=(tasks==t)&valid
            pred[test]=logistic_prediction(features[train],y[train],features[test])
        result['leave_one_task_out'][name]={'auroc':float(roc_auc_score(y[valid],pred[valid])),
            'average_precision':float(average_precision_score(y[valid],pred[valid])),
            'positive_prevalence':float(y[valid].mean()),'n':int(valid.sum())}
    (HERE/'case-ranking-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
