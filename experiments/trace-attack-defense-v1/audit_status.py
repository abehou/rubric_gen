"""Read-only audit progress: counts only, never outcome verdicts or provider calls."""
import json,os
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
from report_sources import RUN,PANEL,read

assert os.environ.get('SLURM_JOB_ID')
sources_on_disk=list((RUN/'study').glob('*/study.json'));assert len(sources_on_disk)==1
study=sources_on_disk[0].parent;ledger=read(study/'study.json')
conditions=set(ledger['execution_conditions']);sources=[r for r in ledger['records'] if r['condition_id'] in conditions]
audit=RUN/'audit'/ledger['experiment_id'];stages={}
for stage in ('rubric_score','absolute_score','pairwise_preference'):
 root=audit/stage;manifest=root/'manifest.json'
 if not manifest.exists():stages[stage]={'state':'not_started'};continue
 value=read(manifest);instrument={'absolute_score':'absolute','pairwise_preference':'pairwise'}.get(stage)
 jobs=[j for j in value['predispatch_plan']['jobs'] if instrument is None or j['instrument']==instrument]
 saved={p.stem for p in (root/'records').glob('*.json')}
 summary=read(root/'summary.json') if (root/'summary.json').exists() else None
 stages[stage]={'required_unique':len(jobs),'saved_record_files':sum(j['semantic_key'] in saved for j in jobs),
  'by_model':{m:{'required':sum(j['model']==m for j in jobs),'saved_record_files':sum(j['model']==m and j['semantic_key'] in saved for j in jobs)} for m in PANEL},
  'final_summary_status':summary.get('status') if summary else None,
  'final_failed_count':summary.get('failed_semantic_judgment_count') if summary else None}
for window in ('full_trajectory','post_update','final_artifact','final_revision'):
 root=audit/('direct_'+window)/'evaluations';directories=list(root.iterdir()) if root.exists() else []
 assert len(directories)<=1
 if not directories:stages['direct_'+window]={'state':'not_started','required':len(sources)*len(PANEL)};continue
 directory=directories[0];files=list((directory/'cases').glob('*/*/score.json'))
 summary=read(directory/'summary.json') if (directory/'summary.json').exists() else None
 stages['direct_'+window]={'required':len(sources)*len(PANEL),'saved_score_files':len(files),
  'by_model':dict(Counter(p.parent.name for p in files)),
  'summary_record_statuses':dict(Counter(r['status'] for r in summary['records'])) if summary else None}
print(json.dumps({'time':datetime.now(timezone.utc).isoformat(),'trace_assignments':len(sources),
 'completed_trace_assignments':sum(r['status']=='completed' for r in sources),'stages':stages,
 'completion_receipt_exists':(RUN/'completion.json').exists(),
 'note':'In-flight saved-file counts are progress indicators; final native record/identity coverage validation remains mandatory.'},indent=2),flush=True)
