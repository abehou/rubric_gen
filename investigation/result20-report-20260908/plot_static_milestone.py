"""Interim plot of complete static conditions only; no pending outcomes implied."""
import hashlib,json,os
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
ROOT=Path('/home/aydanh/repos/rubric_gen')
source=ROOT/'runs/babel-result20-current-20260908/static-comparison-v1/analysis.json'
d=json.loads(source.read_text());assert len(d['rows'])==240 and all(c['assignment_count']==60 for c in d['coverage'])
conditions=['full-static','user-simulator-static'];labels=['Full feedback','User simulator'];colors=['#007cb5','#cc489e']
fig,axes=plt.subplots(1,3,figsize=(15,4.6),layout='constrained')
for ax in axes:
 ax.set_axisbelow(True);ax.grid(axis='y',alpha=.22);ax.spines[['top','right']].set_visible(False)
for i,c in enumerate(conditions):
 for j,model in enumerate(['gpt-5.6-sol','claude-opus-5']):
  m=d['conditions'][c+'/'+model]['metrics']['RH_full_trajectory'];lo,hi=np.array(m['identification_bounds'])*100;x=j+(i-.5)*.34
  axes[0].bar(x,lo,width=.32,color=colors[i],label=labels[i] if j==0 else None)
  axes[0].bar(x,hi-lo,bottom=lo,width=.32,color=colors[i],alpha=.25,hatch='///')
  axes[0].text(x,hi+.6,f'{lo:.1f}–{hi:.1f}%',ha='center',fontsize=9)
axes[0].set_xticks([0,1],['Sol','Opus']);axes[0].set_ylim(0,30);axes[0].set_ylabel('Detected trajectories (%)');axes[0].set_title('Full-trajectory RH');axes[0].legend(frameon=False,fontsize=9)
quality=[d['conditions'][c+'/matched-panel']['metrics']['A']['mean'] for c in conditions]
axes[1].bar(labels,quality,color=colors,width=.6)
for i,v in enumerate(quality):axes[1].text(i,v+1,f'{v:.2f}',ha='center')
axes[1].set_ylim(0,100);axes[1].set_ylabel('Rubric-free quality (points)');axes[1].set_title('Final artifact quality')
contrast=d['contrasts']['full-static minus user-simulator-static']['matched-panel']['metrics']['A'];ci=contrast['task_bootstrap_95_interval']
axes[1].text(.5,.12,f'Paired user gain: {-contrast["mean"]:.2f}\n95% interval: {-ci[1]:.2f} to {-ci[0]:.2f}',transform=axes[1].transAxes,ha='center',fontsize=10)
metrics=['WS','SH','HA','WA'];x=np.arange(4)
for i,c in enumerate(conditions):
 values=[d['conditions'][c+'/matched-panel']['metrics'][m]['mean'] for m in metrics]
 axes[2].bar(x+(i-.5)*.36,values,width=.34,color=colors[i])
 for a,v in zip(x+(i-.5)*.36,values):axes[2].text(a,v+.5,f'{v:.2f}',ha='center',fontsize=8)
axes[2].set_xticks(x,['W−S','S−H','H−A','W−A']);axes[2].set_ylim(0,34);axes[2].set_ylabel('Gap (points)');axes[2].set_title('Final score decomposition')
fig.suptitle('Completed static Result20 baseline · 20 tasks × 3 replicates',fontsize=16)
fig.supxlabel('Trace-policy results pending. Hatched RH portions are abstention bounds, not confidence intervals. Both S−H intervals include zero.',fontsize=10)
out=ROOT/'runs/babel-result20-current-20260908/static-milestone-figure';out.mkdir(exist_ok=False)
fig.savefig(out/'static-baseline.png',dpi=180);fig.savefig(out/'static-baseline.pdf');plt.close(fig)
(out/'provenance.json').write_text(json.dumps(dict(job=os.environ['SLURM_JOB_ID'],source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),assignments=120,scope='Complete static conditions only;dynamic results pending;no new provider calls'),indent=2)+'\n')
print(out/'static-baseline.png')
