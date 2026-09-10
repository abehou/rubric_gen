"""Private publication plots from coverage-checked, complete matched Result20 rows."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean

PANEL = {'gpt-5.6-sol', 'claude-opus-5'}
CONDITIONS = ('full-static', 'user-simulator-static', 'full-red-team-trace', 'user-simulator-red-team-trace')
WINDOWS = ('full_trajectory', 'post_update', 'final_artifact', 'final_revision')


def tables(payload):
    rows = payload['rows']
    assert len(rows) == 480
    assert {r['condition_id'] for r in rows} == set(CONDITIONS)
    assert len({(r['condition_id'], r['task_id'], r['replicate'], r['model']) for r in rows}) == 480
    inventories = []
    result = []
    for condition in CONDITIONS:
        rs = [r for r in rows if r['condition_id'] == condition]
        assert len(rs) == 120 and {r['model'] for r in rs} == PANEL
        inventory = {(r['task_id'], r['replicate']) for r in rs}
        assert len(inventory) == 60 and len({t for t, rep in inventory}) == 20
        assert {rep for t, rep in inventory} == {1, 2, 3}
        inventories.append(inventory)
        value = {'condition': condition, 'assignments': 60, 'auditor_rows': 120}
        for key in ('W', 'W_train', 'S', 'H', 'A', 'WS', 'SH', 'HA', 'WA'):
            value[key] = mean(r['values'][key] for r in rs)
        value['master_minus_A'] = mean(r['strong_master'] - r['values']['A'] for r in rs)
        for window in WINDOWS:
            decisions = Counter(r['direct'][window]['decision'] for r in rs)
            assert set(decisions) <= {'reward_hacking_detected', 'no_reward_hacking_detected', 'abstain'}
            value[window + '_lower_pct'] = 100 * decisions['reward_hacking_detected'] / 120
            value[window + '_upper_pct'] = 100 * (decisions['reward_hacking_detected'] + decisions['abstain']) / 120
            value[window + '_abstentions'] = decisions['abstain']
            value[window + '_score'] = mean(r['direct'][window]['score'] for r in rs)
        result.append(value)
    assert all(i == inventories[0] for i in inventories)
    return result


def plot(data, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    by = {r['condition']: r for r in data}
    def panel(ax, key, title, ylabel, upper=None):
        x = np.arange(2)
        for offset, names, label, color in [(-.18, ('full-static', 'full-red-team-trace'), 'Full feedback', '#007eb5'), (.18, ('user-simulator-static', 'user-simulator-red-team-trace'), 'User simulator', '#ca4b9b')]:
            values = [by[c][key] for c in names]
            bars = ax.bar(x + offset, values, .36, label=label, color=color)
            ax.bar_label(bars, fmt='%.2f', padding=4, fontsize=9)
            if upper:
                lengths = [by[c][upper] - by[c][key] for c in names]
                ax.errorbar(x + offset, values, yerr=[np.zeros(2), lengths], fmt='none', ecolor='black', capsize=4)
        ax.set_xticks(x, ['Static rubric', 'Red-team trace'])
        ax.set_title(title, weight='bold'); ax.set_ylabel(ylabel)
        ax.axhline(0, color='#444444', lw=.8); ax.grid(axis='y', alpha=.25); ax.set_axisbelow(True)
        ax.margins(y=.2)
    footer = 'BioMNIBench-DA | 20 tasks × 3 replicates | equal-weight Sol + Opus mean\nOffline elicited / red-team artifact: not run. RH whiskers show abstention bounds, not confidence intervals.'
    fig, axes = plt.subplots(3, 2, figsize=(13, 13))
    specs = [('WS','Weak to strong','W − S (points)',None), ('SH','Selected to heldout','S − H (points)',None), ('master_minus_A','Master rubric to holistic','Strong master − A (points)',None), ('HA','Heldout to holistic','H − A (points)',None), ('final_artifact_lower_pct','Final-artifact reward hacking','Per-auditor RH (%)','final_artifact_upper_pct'), ('final_artifact_score','Mean final-artifact RH score','Monitor score (0–10)',None)]
    for ax, spec in zip(axes.flat, specs): panel(ax, *spec)
    fig.legend(*axes[0,0].get_legend_handles_labels(), loc='upper center', ncol=2)
    fig.text(.5,.015,footer,ha='center',fontsize=9); fig.tight_layout(rect=(0,.06,1,.96))
    fig.savefig(output/'avg-result20-20260908.png',dpi=180); plt.close(fig)
    fig, axes = plt.subplots(1,2,figsize=(13,5))
    panel(axes[0],'full_trajectory_lower_pct','RH detection rate','Detected trajectories (%)','full_trajectory_upper_pct')
    panel(axes[1],'full_trajectory_score','Mean RH score','Mean monitor score (0–10)')
    for ax in axes:
        ax.set_xlabel('Rubric policy')
    fig.suptitle('OpenAI + Anthropic average', x=.01, ha='left', weight='bold')
    fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',ncol=2)
    fig.text(.5,.015,footer,ha='center',fontsize=9);fig.tight_layout(rect=(0,.12,1,.9))
    fig.savefig(output/'openai-anthropic-average-result20-20260908.png',dpi=180);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--analysis',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    payload=json.loads(a.analysis.read_text());data=tables(payload)
    a.output.mkdir(parents=True,exist_ok=False)
    with (a.output/'plot-values.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    plot(data,a.output)
    (a.output/'provenance.json').write_text(json.dumps({'analysis':str(a.analysis.resolve()),'analysis_sha256':hashlib.sha256(a.analysis.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'aggregation':'equal per-auditor mean; distinct from panel union reported in analysis.json','third_gap':'master_minus_A preserves original figure meaning; HA shown separately','unrun':['offline elicited','red-team artifact']},indent=2)+'\n')

if __name__=='__main__':main()
