import json
from pathlib import Path
from context import ea,ep

def apply_sol(ctx):
 ctx=dict(ctx);source=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909/sol-gap-impact-v1')/f"context-{ctx['row']['context']:02d}.json";d=json.loads(source.read_text());raw=d['comparisons']['comparisons']
 def score(r):return ea.RubricScore(r['artifact_id'],r['base_score'],tuple((v['criterion_id'],v['level']) for v in r['criterion_levels']),r['total_score'],r['reason'])
 pairs=[]
 for c in raw:
  a=c['active_rubric'];v=c['development_rubric'];pairs.append(ea.PairComparison(c['pair_id'],c['preferred_artifact_id'],c['rejected_artifact_id'],c['rubric_free_reason'],a['preference'],a['reason'],(score(a['preferred']),score(a['rejected'])),v['preference'],v['reason'],(score(v['preferred']),score(v['rejected'])),tuple(ea.AssessmentView(i) for i in c['gap_views'])))
 ctx['pairs']=tuple(pairs);ctx['induction']=tuple(p for p,c in zip(pairs,raw,strict=True) if c['subset']=='induction' and p.gap_views)
 ctx['request']={**ctx['request'],'evidence':d['derived_induction_evidence'],'response_schema':ep.induction_schema(ep.required_level_labels(ctx['original']),ctx['induction'],ctx['current'])}
 history=json.loads((ctx['g']/'artifact-history.json').read_text());ctx['artifact_ids']=ea.validation_artifact_ids(ctx['pairs']);ctx['artifacts']={a['artifact_id']:{'artifact_id':a['artifact_id'],'content':a['content']} for a in history['artifacts'] if a['artifact_id'] in ctx['artifact_ids']};assert set(ctx['artifacts'])==set(ctx['artifact_ids'])
 assert json.loads(ctx['request']['evidence'])['current_rubric']==ctx['current'].rubric.content
 return ctx
