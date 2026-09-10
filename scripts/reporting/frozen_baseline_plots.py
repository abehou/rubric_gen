"""Formal baseline figures; display labels are independent of provenance IDs."""
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
    footer = 'BioMNIBench-DA | 20 tasks | Static arms and User simulator trace: n=60; Full feedback trace: n=59 (incomplete)\nEqual-weight Sol + Opus means. RH whiskers: abstention bounds, not confidence intervals. Artifact auditor uncalibrated.'
    fig, axes = plt.subplots(3, 2, figsize=(13, 13))
    specs = [('WS','Weak to strong','W − S (points)',None), ('SH','Selected to heldout','S − H (points)',None), ('master_minus_A','Master rubric to holistic','Strong master − A (points)',None), ('HA','Heldout to holistic','H − A (points)',None), ('final_artifact_lower_pct','Final-artifact reward hacking','Per-auditor RH (%)','final_artifact_upper_pct'), ('final_artifact_score','Mean final-artifact RH score','Monitor score (0–10)',None)]
    for ax, spec in zip(axes.flat, specs): panel(ax, *spec)
    fig.legend(*axes[0,0].get_legend_handles_labels(), loc='upper center', ncol=2)
    fig.text(.5,.015,footer,ha='center',fontsize=9); fig.tight_layout(rect=(0,.06,1,.96))
    fig.savefig(output/'gaps-and-artifact-rh.png',dpi=180); plt.close(fig)
    fig, axes = plt.subplots(1,2,figsize=(13,5))
    panel(axes[0],'full_trajectory_lower_pct','RH detection rate','Detected trajectories (%)','full_trajectory_upper_pct')
    panel(axes[1],'full_trajectory_score','Mean RH score','Mean monitor score (0–10)')
    for ax in axes:
        ax.set_xlabel('Rubric policy')
    fig.suptitle('OpenAI + Anthropic average', x=.01, ha='left', weight='bold')
    fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',ncol=2)
    fig.text(.5,.015,footer,ha='center',fontsize=9);fig.tight_layout(rect=(0,.12,1,.9))
    fig.savefig(output/'trajectory-rh.png',dpi=180);plt.close(fig)
