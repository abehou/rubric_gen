"""Read-only current-format online policy exposure from a native validated report."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def learned_generation(manifest):
    """Shared offline g1 is excluded; explicit initial-sidecar g1 is learned here."""
    return manifest['generation_round'] >= 2 or (
        manifest['generation_round'] == 1 and manifest['policy'] == 'red_team_trace_early'
    )


def inspect_report(report):
    artifacts={}
    def read(p):
        artifacts[str(p.resolve())]=digest(p)
        return json.loads(p.read_text())
    data=read(report);seen=set();rows=[];generations=[]
    for row in data['rows']:
        state=Path(row['state_path'])
        assert digest(state)==row['state_sha256']
        if str(state) in seen:continue
        seen.add(str(state));exp=state.parent;c=Counter();rejections=Counter();accepted=set();gm={}
        for g in sorted((exp/'rubric-generations').glob('generation-*')):
            m=read(g/'manifest.json');gr=m['generation_round'];gm[gr]=m
            criteria=read(g/'criteria.json')
            if not learned_generation(m):continue
            e=read(g/'evolution.json');proposal=read(g/'criterion-proposal.json')['criteria']
            validation=read(g/'criterion-validation.json')['validations'];adm=read(g/'aggregate-margins.json')
            history=read(g/'artifact-history.json')
            c.update(generations=1,gaps=e['rubric_gap_count'],preferences=e['rubric_free_preference_count'],proposed=len(proposal),validated=len(validation),accepted=len(e['accepted_candidate_ids']),pair_assessments=len(history['pairs']),observable_nonredundant=sum(v['observable'] and v['nonredundant'] for v in validation))
            c['empty_proposals_with_gaps']+=bool(e['rubric_gap_count'] and not proposal)
            c['fallback_generations']+=any(v for k,v in e.items() if k.endswith('_fallback_reason'))
            if gr==1:
                c['initial_sidecar_generations']+=1
                c['initial_sidecar_accepted']+=len(e['accepted_candidate_ids'])
            accepted.update(e['accepted_candidate_ids'])
            rejections.update(d['reason'] for d in adm['decisions'] if not d['accepted'])
            rejections.update('not observable' for v in validation if not v['observable'])
            rejections.update('redundant' for v in validation if not v['nonredundant'])
            generations.append(dict(assignment=row['assignment_id'],condition=row['condition_id'],generation=gr,path=str(g),proposed=len(proposal),accepted=e['accepted_candidate_ids'],retained=criteria,decisions=adm['decisions']))
        # Sidecars are method evidence, never natural-RH outcome assignments.
        for path in sorted((exp/'red-team').glob('checkpoint-*/manifest.json')):
            sidecar=read(path);checkpoint=sidecar['checkpoint']
            assert sidecar['active_generation_sha256']==gm[checkpoint]['generation_sha256']
            assert sidecar['active_rubric_sha256']==gm[checkpoint]['rubric_sha256']
            prompt=path.parent/'prompt.txt'
            assert digest(prompt)==sidecar['file_sha256s']['prompt.txt']
            artifacts[str(prompt.resolve())]=digest(prompt)
            assert type(sidecar['included']) is bool
            c['sidecars']+=1
            c['included_sidecars']+=sidecar['included']
        penalized=set()
        for p in sorted((exp/'rubric-evaluations').glob('*.json')):
            ev=read(p);gr=ev['generation_round'];m=gm[gr]
            assert ev['generation_sha256']==m['generation_sha256'] and ev['rubric_sha256']==m['rubric_sha256']
            c['negative_penalty_checkpoints']+=ev['elicited_penalty']<0
            if not learned_generation(m):continue
            cr=read(exp/'rubric-generations'/f'generation-{gr:04d}'/'criteria.json')
            c['checkpoints_with_online_criteria']+=bool(cr)
            if not cr:continue
            ep=exp/'judgments'/ev['submission_id']/ev['rubric_sha256']/'evaluation.json'
            assert digest(ep)==ev['evaluation_sha256'];evaluation=read(ep)
            base=len(evaluation['criteria'])-len(cr)
            for i,criterion in enumerate(cr,start=base+1):
                if criterion['criterion_id'] in accepted and evaluation['criteria'][f'criterion_{i}']['points']<0:
                    penalized.add(criterion['criterion_id'])
        last=max(gm);final=read(exp/'rubric-generations'/f'generation-{last:04d}'/'criteria.json')
        c['distinct_online_accepted']=len(accepted)
        c['accepted_retained_final']=len(accepted & {x['criterion_id'] for x in final})
        c['accepted_ids_observed_negative']=len(penalized)
        rows.append(dict(assignment=row['assignment_id'],condition=row['condition_id'],task=row['task_id'],counts=dict(c),rejections=dict(rejections),state_path=str(state)))
    summary={}
    for cond in sorted({r['condition'] for r in rows}):
        subset=[r for r in rows if r['condition']==cond];counts=Counter();reasons=Counter()
        for r in subset:counts.update(r['counts']);reasons.update(r['rejections'])
        summary[cond]=dict(counts=counts,rejections=reasons,assignments=len(subset),assignments_with_online_admission=sum(r['counts']['distinct_online_accepted']>0 for r in subset),assignments_with_online_penalty=sum(r['counts']['accepted_ids_observed_negative']>0 for r in subset))
    return dict(conditions=summary,assignments=rows,generations=generations,source_artifact_sha256s=artifacts,scope='Complete native outcome report; deduplicated assignment exposure, generations>=2 plus explicit red_team_trace_early g1, with initial-sidecar counts separate; shared offline g1 remains excluded. Repeated pair assessments are not unique pairs. Active penalties do not alone prove simulator feedback used a criterion. Sidecars are counted separately and never contribute natural-RH outcomes.',diagnostic_sha256=digest(__file__))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--analysis',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=inspect_report(a.analysis);a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'policy-exposure.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['conditions'],indent=2))

if __name__=='__main__':main()
