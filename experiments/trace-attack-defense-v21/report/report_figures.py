"""Standalone scientific plot from the sealed task-cluster analysis only."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from report_sources import PUBLIC,read
from metrics import THRESHOLDS

r=read(PUBLIC/'results.json');assert r['complete']
fig,axes=plt.subplots(1,3,figsize=(11,3.0),layout='constrained')
for ax,(metric,title,unit) in zip(axes,[('RH','Full-trajectory RH','percentage points'),('W_minus_S','W−S','score points'),('W_minus_A','W−A','score points')]):
 for y,arm,color in [(0,'full','#1764ab'),(1,'user','#c56b14')]:
  s=r['contrasts'][arm+'_minus_static'][metric];value=s['mean'];lo,hi=s['ci95']
  ax.errorbar(value,y,xerr=[[value-lo],[hi-value]],fmt='o',color=color,capsize=4,markersize=6)
 ax.axvline(0,color='#888888',lw=1)
 ax.axvline(THRESHOLDS[metric],color='#555555',ls='--',lw=1)
 ax.set_yticks([0,1],['Full','User']);ax.set_ylim(1.65,-.65)
 ax.set_xlabel('Candidate − static ('+unit+')');ax.set_title(title);ax.grid(axis='x',alpha=.2)
 ax.spines[['top','right']].set_visible(False)
fig.suptitle('attack_defense_v1: paired effects and task-cluster 95% intervals\nDashed lines: prespecified practical thresholds; negative primary effects are favorable',fontsize=10)
for suffix in ('png','svg'):fig.savefig(PUBLIC/('paired-primary-differences.'+suffix),dpi=180)
svg=PUBLIC/'paired-primary-differences.svg'
svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
plt.close(fig)
