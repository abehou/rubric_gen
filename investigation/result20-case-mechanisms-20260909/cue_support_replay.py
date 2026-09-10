"""Native admission replay on frozen cases; hypothetical citation repair only."""
from pathlib import Path
from dataclasses import replace
import collections,hashlib,json,os
from rubric_gen.submission_revision import evolution_protocol as ep, evolution_assessment as ea
from rubric_gen.submission_revision.rubric_generation import CompleteRubric,RubricGeneration,parse_elicited_criterion
ROOT=Path('/home/aydanh/repos/rubric_gen');OUT=ROOT/'docs/reports/2026-09-09'
def read(p):return json.loads(p.read_text())
def main():
 if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm required')
 source=OUT/'rubric-cue-support-census.json';data=read(source)
 chosen=[r for r in data['rows'] if r['decision']=='criterion_support_failed' and r['support_counts'].get('supports') and r['support_counts'].get('tie') and not r['support_counts'].get('inversion') and not r['replaces']]
 rows=[];counts=collections.Counter()
 for row in chosen:
  g=Path(row['path']);n=int(g.name.split('-')[-1]);prev=g.parent/f'generation-{n-1:04d}'
  for directory in [g,prev]:
   m=read(directory/'manifest.json')
   assert all(hashlib.sha256((directory/k).read_bytes()).hexdigest()==v for k,v in m['file_sha256s'].items())
  m=read(prev/'manifest.json');current=RubricGeneration(m['generation_round'],m['source_checkpoint'],CompleteRubric.from_content((prev/'rubric.txt').read_text()),tuple(parse_elicited_criterion(c) for c in read(prev/'criteria.json')),m['proposer_call_budget'])
  assert current.generation_sha256==m['generation_sha256']
  original=CompleteRubric.from_content((g.parent/'generation-0000/rubric.txt').read_text())
  def score(r):return ea.RubricScore(r['artifact_id'],r['base_score'],tuple((v['criterion_id'],v['level']) for v in r['criterion_levels']),r['total_score'],r['reason'])
  raw=read(g/'pairwise-comparisons.json')['comparisons'];pairs=[]
  for c in raw:
   a=c['active_rubric'];d=c['development_rubric']
   pairs.append(ea.PairComparison(c['pair_id'],c['preferred_artifact_id'],c['rejected_artifact_id'],c['rubric_free_reason'],a['preference'],a['reason'],(score(a['preferred']),score(a['rejected'])),d['preference'],d['reason'],(score(d['preferred']),score(d['rejected'])),tuple(ea.AssessmentView(v) for v in c['gap_views'])))
  pairs=tuple(pairs);induction=tuple(c for c,r in zip(pairs,raw,strict=True) if r['subset']=='induction' and c.gap_views)
  cs=ep.validated_induction_response((g/'criterion-proposal.json').read_text(),original_rubric=original,current_generation=current,generation_round=n,level_labels=ep.required_level_labels(original),induction_gaps=induction)
  vs=ep.validated_validation_response((g/'criterion-validation.json').read_text(),candidates=cs,artifact_ids=ea.validation_artifact_ids(pairs))
  accepted,decisions=ep.admit_candidates(cs,vs,pairs,current)
  saved=read(g/'aggregate-margins.json')
  assert [d.reason for d in decisions]==[d['reason'] for d in saved['decisions']]
  assert [c.criterion.criterion_id for c in accepted]==saved['accepted_candidate_ids']
  idx=next(i for i,c in enumerate(cs) if c.criterion.criterion_id==row['criterion_id'])
  keep=tuple(p['pair_id'] for p in row['pairs'] if p['relation']=='supports')
  altered=list(cs);altered[idx]=replace(cs[idx],criterion=replace(cs[idx].criterion,provenance_pair_ids=keep))
  newaccepted,newdecisions=ep.admit_candidates(tuple(altered),vs,pairs,current)
  dec=newdecisions[idx];counts[dec.reason]+=1
  rows.append(dict(path=str(g),criterion_id=row['criterion_id'],title=row['title'],old_citations=cs[idx].criterion.provenance_pair_ids,hypothetical_citations=keep,decision=dec.reason,failed_margin_checks=[c.as_dict() for c in dec.margin_checks if not c.passed]))
 payload=dict(job_id=os.environ['SLURM_JOB_ID'],source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),counts=dict(counts),rows=rows,interpretation='Hypothetical removal of tied citations in one candidate at a time. All candidate wording, applications, prior accepted candidates, score floors and aggregate checks unchanged. Original decisions replay exactly. No revised scientific artifact, model call, real admission, or outcome prediction.')
 for suffix in ['json','md']:
  if (OUT/f'rubric-cue-support-replay.{suffix}').exists():raise FileExistsError('preserve previous report')
 (OUT/'rubric-cue-support-replay.json').write_text(json.dumps(payload,indent=2)+'\n')
 lines=['# Rubric-cue native admission replay','',payload['interpretation'],'',f'Cases: {len(rows)}; resulting decisions: {dict(counts)}.','', 'This diagnostic tests whether citation precision could matter with every substantive validation gate retained. It does not justify silently pruning evidence or claiming new criteria reduce RH. A proposer-only citation clarification would still need fresh independent validation, prospective behavioral criteria, and a trace-only experiment before adoption.','']
 (OUT/'rubric-cue-support-replay.md').write_text('\n'.join(lines));print('\n'.join(lines))
if __name__=='__main__':main()
