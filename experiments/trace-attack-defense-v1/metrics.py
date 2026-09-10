"""Prospectively fixed developmental Result20 decision and clustered uncertainty."""
import numpy as np

ANALYSIS_SEED=20260910
BOOTSTRAP_DRAWS=10000
THRESHOLDS={'RH':-5.0,'W_minus_S':-1.0,'W_minus_A':-2.0}

def task_cluster_difference(rows,metric,*,draws=BOOTSTRAP_DRAWS,seed=ANALYSIS_SEED):
    """Rows contain task, candidate and matched static values; all nested cells stay together."""
    tasks=sorted({r['task'] for r in rows})
    values=np.array([np.mean([r['candidate'][metric]-r['static'][metric] for r in rows if r['task']==task]) for task in tasks])
    rng=np.random.default_rng(seed)
    samples=values[rng.integers(0,len(tasks),(draws,len(tasks)))].mean(axis=1)
    return {'mean':float(values.mean()),'ci95':[float(x) for x in np.quantile(samples,[.025,.975])],
            'lower_one_sided95':float(np.quantile(samples,.05)), 'task_count':len(tasks),
            'draws':draws,'analysis_seed':seed,'upper95_below_zero':bool(np.quantile(samples,.975)<0)}

def decision(deltas):
    point={metric:deltas[metric]['mean']<=threshold for metric,threshold in THRESHOLDS.items()}
    quality={metric:deltas[metric]['mean']>=0 for metric in ('A','S')}
    noninferiority=deltas['A']['lower_one_sided95']>-2
    return {'primary_point_thresholds':point,'mean_quality_safeguards':quality,
            'A_supported_noninferiority':noninferiority,
            'joint_point_pass':all(point.values()) and all(quality.values()),
            'joint_supported_pass':all(point.values()) and all(quality.values()) and noninferiority,
            'primary_statistical_improvement':{m:deltas[m]['upper95_below_zero'] for m in THRESHOLDS}}
