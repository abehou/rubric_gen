"""Saved dev3 learning mechanics only: no outcome panel or efficacy-based selection."""
import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic

BUNDLE=Path(__file__).resolve().parent
ROOT=BUNDLE.parents[1]
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')


def dump_csv(path,rows):
    if not rows:return
    with path.open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in rows)


def read(path):return json.loads(path.read_text())


def summarize(subversion):
    cohort=RUN/'dev3'/subversion
    completion=read(cohort/'completion.json')
    if completion['completed']!=18:raise RuntimeError('mechanism readiness requires all 18 assignments')
    out=ROOT/'docs/reports/2026-09-10/trace-attack-defense-v2/dev3'/subversion
    out.mkdir(parents=True,exist_ok=True)
    requests,appearances,candidates,deliveries,assignments,attempt_rows=[],[],[],[],[],[]
    arm_counts={arm:Counter() for arm in ['full','user']}
    for assignment in completion['assignments']:
        root=Path(assignment['root']);manifest=read(root/'manifest.json')
        arm='user' if 'user-simulator' in assignment['assignment_id'] else 'full'
        counts=arm_counts[arm];counts['assignments']+=1
        task=manifest['task_id'];replicate=int(assignment['assignment_id'].split('--rep-')[1].split('--')[0])
        common={'arm':arm,'task_id':task,'replicate':replicate,'assignment_id':assignment['assignment_id']}
        new_rules={};native_ids=set();first_admission=None
        for p in sorted((root/'red-team').glob('checkpoint-*/manifest.json')):
            m=read(p);counts['sidecars_attempted']+=1;counts['sidecars_execution_valid']+=bool(m['included'])
            attack=read(p.parent/'attack-record-v2.json');counts['sidecars_nonidentical']+=bool(attack['public_nonidentical'])
        for p in sorted((root/'trace-defense-v2-requests').glob('*/result.json')):
            r=read(p);stage=r['request']['stage'];outcome=r['outcome'];value=outcome['value']
            row={**common,'request_sha256':p.parent.name,'stage':stage,'status':outcome['status'],
                 'first_response_valid':r['accounting']['first_response_valid'],'receipt':str(p),'receipt_sha256':sha256_file(p),
                 'accounting':r['accounting'],'action':value.get('action') if value else None,
                 'scientific_null':bool(value and (value.get('preferred_artifact_id','ordered') is None or value.get('action') in ['NO_SUPPORTED_RELATION','PREFERENCE_CONFLICT']
                                                 or value.get('applicability')=='undecidable' or value.get('criteria')==[])),
                 'source_binding_status':outcome['source_binding_status']}
            requests.append(row)
            for a in sorted(p.parent.glob('attempt-*.json')):
                v=read(a);attempt_rows.append({**common,'request_sha256':p.parent.name,'stage':stage,'attempt':v['attempt'],
                    'request_kind':v['request_kind'],'status':v['status'],'validation_errors':v.get('validation_errors',[]),
                    'provider_error_type':v.get('error_type'),'wall_seconds':v['wall_seconds'],
                    'cost':v.get('output',{}).get('cost'),'generation':v.get('output',{}).get('generation')})
        for path in sorted((root/'rubric-generations').glob('generation-*/evolution.json')):
            generation=int(path.parent.name.split('-')[-1])
            if generation<2:continue
            e=read(path);proposal=read(path.parent/'criterion-proposal.json');validation=read(path.parent/'criterion-validation.json')
            margin=read(path.parent/'aggregate-margins.json');comparison=read(path.parent/'pairwise-comparisons.json')
            counts['updates']+=1;counts['quality_gap_appearances']+=e['rubric_gap_count'];counts['selected_induction_pairs']+=len(proposal['selection'])
            for r in e['requests']:
                appearances.append({**common,'generation':generation,'stage':r['stage'],'request_sha256':r['request_sha256'],
                    'status':r['outcome']['status'],'cache_hit':r['cache_hit'],'actual_calls':r['actual_calls']})
            for d in proposal['diagnoses']:
                if d['response']:counts['diagnosis_'+d['response']['action'].split(':')[0]]+=1
                else:counts['diagnosis_contract_exhausted']+=1
            for c in proposal['compilations']:
                value=c['response']
                if value is None:counts['compilation_contract_exhausted']+=1
                elif value['criteria']:counts['compiled_candidates']+=len(value['criteria'])
                else:counts['empty_compilations']+=1
            decisions={d['criterion_id']:d for d in margin['decisions']}
            comparisons={p['pair_id']:p for p in comparison['comparisons']}
            # Host-native criterion identity depends on content and fixed points, never evaluator outcomes.
            raw_by_id={}
            for c in proposal['criteria']:
                levels=tuple((x['label'],{'A':0,'B':-5,'C':-10}[x['label']],x['description']) for x in c['levels'])
                identity='elicited_'+sha256_text(json.dumps({'title':c['title'],'requirement':c['requirement'],'levels':levels},ensure_ascii=False,sort_keys=True,separators=(',',':')))[:16]
                raw_by_id[identity]=c
            for review in validation['reviews']:
                identity=review['criterion_id'];raw=raw_by_id[identity];pair=comparisons[raw['provenance_pair_ids'][0]]
                applications={a['artifact_id']:a['response'] for a in review['applications']}
                pref=applications.get(pair['preferred_artifact_id']);rej=applications.get(pair['rejected_artifact_id'])
                pref_level=pref.get('level') if pref else None;rej_level=rej.get('level') if rej else None
                complete=not review['ineligibility'];decision=decisions.get(identity)
                if complete!=(decision is not None):raise RuntimeError('complete candidate/native decision accounting differs')
                strict=pref_level is not None and rej_level is not None and ('ABC'.index(pref_level)<'ABC'.index(rej_level))
                counts['complete_native_candidates']+=complete
                counts['strict_witness_complete_candidates']+=bool(complete and strict)
                counts['required_applications']+=len(review['required_artifact_ids'])
                counts['complete_applications']+=sum(a is not None and a['applicability']!='undecidable' for a in applications.values())
                if decision:counts[decision['reason']]+=1
                first_failure=next((m for m in decision['margin_checks'] if not m['passed']),None) if decision else None
                candidates.append({**common,'generation':generation,'criterion_id':identity,'criterion':raw,'complete_native_decision':complete,
                    'witness_preferred_level':pref_level,'witness_rejected_level':rej_level,'strict_witness':strict,
                    'semantic':review['semantic'],'ineligibility':review['ineligibility'],'native_decision':decision['reason'] if decision else None,
                    'first_binding_margin_failure':first_failure,'applications':review['applications'],
                    'source_receipt':str(path.parent/'criterion-validation.json')})
                if decision and decision['accepted']:
                    native_ids.add(identity);new_rules[identity]={'requirement':raw['requirement'],'generation':generation,'first_exposure':None}
                    first_admission=generation if first_admission is None else min(first_admission,generation)
        for p in sorted((root/'turns').glob('turn-*/prompt.txt')):
            turn=int(p.parent.name.split('-')[-1]);text=p.read_text();reminder_path=root/'trace-defense-reminders'/f's{turn-1:03d}.json'
            reminder=read(reminder_path);selection=reminder['selection'];block=reminder['message_component']
            if sha256_file(p)!=reminder['final_prompt_sha256']:raise RuntimeError('actual reminder prompt hash mismatch')
            ordinary=text[:-len('\n\n'+block)] if block else text
            for identity,rule in new_rules.items():
                # Generation g can inform turn g-1, never earlier.
                if turn<rule['generation']-1:continue
                ordinary_offset=ordinary.find(rule['requirement']);focused=bool(selection and selection['criterion_id']==identity)
                if ordinary_offset>=0 or focused:
                    if rule['first_exposure'] is None:rule['first_exposure']=turn
                    deliveries.append({**common,'criterion_id':identity,'source_generation':rule['generation'],'solver_turn':turn,
                        'ordinary_verbatim_exposure':ordinary_offset>=0,'ordinary_offset':ordinary_offset,'focused_reminder':focused,
                        'corrective':selection['corrective'] if focused else None,'prompt':str(p),'prompt_sha256':sha256_file(p)})
        online_exposed=sum(x['first_exposure'] is not None for x in new_rules.values())
        counts['assignments_with_online_admission']+=bool(native_ids);counts['new_online_rules']+=len(native_ids)
        counts['assignments_with_online_exposure']+=bool(online_exposed);counts['online_rules_exposed']+=online_exposed
        counts['pre_turn1_online_admission']+=first_admission==2
        counts['pre_turn1_online_exposure']+=any(x['first_exposure']==1 for x in new_rules.values())
        assignments.append({**common,'online_admitted':len(native_ids),'online_exposed':online_exposed,'first_admission_generation':first_admission,
            'first_online_exposure_turn':min((x['first_exposure'] for x in new_rules.values() if x['first_exposure'] is not None),default=None),
            'root':str(root)})
    phase=read(RUN/'phase-a'/f'{subversion}-001/result.json')
    gates={};contract_rates={}
    for arm,c in arm_counts.items():
        subset=[r for r in requests if r['arm']==arm and r['stage'] in ['quality','diagnosis','application']]
        apps=[r for r in subset if r['stage']=='application']
        valid_rate=sum(r['status']=='valid_result' for r in subset)/len(subset) if subset else 0
        app_rate=sum(r['status']=='valid_result' for r in apps)/len(apps) if apps else 0
        complete=c['complete_native_candidates']/c['compiled_candidates'] if c['compiled_candidates'] else 0
        strict=c['strict_witness_complete_candidates']/c['complete_native_candidates'] if c['complete_native_candidates'] else 0
        contract_rates[arm]={'overall_valid':valid_rate,'overall_denominator':len(subset),'application_valid':app_rate,'application_denominator':len(apps),
                             'complete_native_fraction':complete,'compiled_denominator':c['compiled_candidates'],'strict_witness_fraction':strict,'complete_denominator':c['complete_native_candidates']}
        gates[arm]={'phase_a':phase['gate_passed'],'contracts':valid_rate>=.98,'application_contracts':app_rate>=.98,'native_complete':complete>=.8,
                    'strict_witness':strict>=.6,'admitted_assignments':c['assignments_with_online_admission']>=2,'actual_online_exposure':c['assignments_with_online_exposure']>=1}
    result={'method':'attack_defense_v2.'+subversion,'full_iteration':completion['iteration'],'completion':completion,
            'counts':{a:dict(c) for a,c in arm_counts.items()},'rates_and_denominators':contract_rates,'gates':gates,
            'readiness_passed':all(all(flags.values()) for flags in gates.values()),'outcome_audits':0,
            'request_units':'unique assignment-local request-cache entries; generation appearances reported separately',
            'exact_request_hashes':len({r['request_sha256'] for r in requests}),'request_cache_entries':len(requests),'request_appearances':len(appearances)}
    for name,rows in [('requests',requests),('request-appearances',appearances),('candidates',candidates),('deliveries',deliveries),('assignments',assignments),('attempts',attempt_rows)]:
        write_json_atomic(out/(name+'.json'),rows);dump_csv(out/(name+'.csv'),rows)
    write_json_atomic(out/'mechanism.json',result);write_json_atomic(cohort/'mechanism.json',result)
    keys=sorted(set().union(*(c.keys() for c in arm_counts.values())))
    lines=[f'# Dev3 {subversion} — complete learning mechanism report','',f"Readiness: {'PASS' if result['readiness_passed'] else 'FAIL'}. Complete 18-assignment cohort; no outcome audits or efficacy-based selection.",'',
           '| Quantity | Full | User |','| --- | ---: | ---: |',*[f'| {k} | {arm_counts["full"][k]} | {arm_counts["user"][k]} |' for k in keys],'',
           'Every rate denominator and gate flag is in mechanism.json. Application levels are model judgments, not scientific ground truth; source-valid evidence does not establish factual accuracy.',
           'Exposure means a verified actual prompt occurrence. The absence of a verbatim requirement does not prove the simulator never conveyed a related concern. Post-treatment exposure strata do not establish causal effects.']
    (out/'README.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('compute-storage report requires Slurm')
    parser=argparse.ArgumentParser();parser.add_argument('subversion');args=parser.parse_args();summarize(args.subversion)
