"""Prespecified saved-input contract microbench; never a revision or outcome audit."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
from dotenv import dotenv_values
from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution_serialization import canonical_sha256, canonical_json
from rubric_gen.submission_revision.rubric_generation import CompleteRubric, parse_elicited_criterion, render_augmented_rubric
from rubric_gen.submission_revision.trace_defense_evidence_v2 import PublicDocument, source_manifest, allowed_actions
from rubric_gen.submission_revision.trace_defense_schema import bind_quotes
from rubric_gen.submission_revision import trace_defense_v2_schema as schema
from rubric_gen.submission_revision.trace_defense_v2 import sources
from rubric_gen.submission_revision.trace_defense_v2_stage import TraceStagesV2

BUNDLE=Path(__file__).resolve().parent
ROOT=BUNDLE.parents[1]
V1=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910')
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')
VERSION='attack_defense_v2.dev1'
PHASE=RUN/'phase-a/dev1-001'
REPORT=ROOT/'docs/reports/2026-09-10/trace-attack-defense-v2/phase-a/dev1-001'
COHORT_FILE=BUNDLE/'phase-a-cohort.json'
FREEZE_FILE=BUNDLE/'dev1-freeze.json'


def select():
    path=V1/'report/quote-binding-requests.csv'
    rows=list(csv.DictReader(path.open()))
    groups={};seen=set()
    for row in sorted(rows,key=lambda x:(x['task_id'],int(x['replicate']),x['request_sha256'])):
        key=(row['arm'],row['stage'],row['request_sha256'])
        if key in seen:continue
        seen.add(key)
        failure=(row['invalid_diagnosis_replacement']=='True') if row['stage']=='diagnosis' else row['any_source_failure']=='True'
        group=(row['arm'],row['stage'],failure)
        groups.setdefault(group,[]).append(row)
    selected=[];strata=[]
    for arm in ('full','user'):
        for stage in ('quality','diagnosis','application'):
            for failed in (True,False):
                available=groups.get((arm,stage,failed),[])
                # report CSV excludes pure provider/no-response entries; verify selected raw receipts below.
                chosen=available[:4]
                selected.extend({**row,'stratum_failure':failed} for row in chosen)
                strata.append({'arm':arm,'stage':stage,'relevant_failure':failed,'available':len(available),'selected':len(chosen),'shortfall':4-len(chosen)})
    return selected,{'source_csv':str(path),'source_csv_sha256':sha256_file(path),'strata':strata}


def reconstruct(row):
    path=Path(row['path'])
    if sha256_file(path)!=row['sha256']:raise RuntimeError('v1 receipt bytes changed')
    receipt=json.loads(path.read_text());request=receipt['request'];old=receipt['outcome']['value']
    if canonical_sha256(request)!=row['request_sha256'] or old is None:raise RuntimeError('invalid/no-response source request')
    if canonical_sha256(receipt['outcome'])!=receipt['outcome_sha256']:raise RuntimeError('v1 response hash mismatch')
    e=json.loads(request['evidence']);stage=row['stage']
    def artifact(value):return SimpleNamespace(artifact_id=value['artifact_id'],content=value['content'])
    if stage=='quality':
        docs,ids,records=sources({k:artifact(e[k]) for k in ('artifact_A','artifact_B')})
        evidence={'task':e['task'],'pair_id':e['pair_id'],**records,'source_manifest':source_manifest(docs,ids),'visible_difference':e['visible_difference']}
        contract=schema.ResponseContract(stage,schema.quality_schema(tuple(ids.values()),docs),docs,ids)
        _,errors=bind_quotes(old['decisive_evidence'],{e[k]['artifact_id']:e[k]['content'] for k in ('artifact_A','artifact_B')},
                            required_ids=tuple(ids.values()) if old['preferred_artifact_id'] else ())
        failure=bool(errors)
    elif stage=='diagnosis':
        by_id={a['artifact_id']:artifact(a) for a in e['artifacts']};c=e['comparison']
        docs,ids,records=sources({'preferred':by_id[c['preferred_artifact_id']],'rejected':by_id[c['rejected_artifact_id']]})
        base_path=path.parents[2]/'rubric-generations/generation-0000/rubric.txt'
        base=CompleteRubric.from_content(base_path.read_text())
        learned=tuple(parse_elicited_criterion(x) for x in e['current_criteria'])
        if render_augmented_rubric(base,learned).content!=e['current_rubric']:raise RuntimeError('v1 diagnosis base/active context mismatch')
        active=tuple(c.criterion_id for c in learned)
        evidence={'task':e['task'],'public_sources':records,'source_manifest':source_manifest(docs,ids),
                  'comparison':e['comparison'],'immutable_base_rubric':base.content,'active_learned_rules':e['current_criteria'],
                  'replaceable_learned_rules':e['current_criteria'],'rules_already_accepted_this_update':[],
                  'allowed_actions':list(allowed_actions(active)),'private_attack_evidence':e['private_attack_evidence']}
        contract=schema.ResponseContract(stage,schema.diagnosis_schema(active,docs),docs,ids,active_ids=active)
        failure=len(set(old['replaces']))!=len(old['replaces']) or any(x not in active for x in old['replaces'])
    else:
        docs,ids,records=sources({'artifact':artifact(e['artifact'])})
        labels=tuple(x['label'] for x in e['criterion']['levels'])
        evidence={'task':e['task'],'criterion':e['criterion'],'artifact':records['artifact'],'source_manifest':source_manifest(docs,ids)}
        contract=schema.ResponseContract(stage,schema.application_schema(labels,docs),docs,ids,labels=labels)
        _,errors=bind_quotes(old['public_evidence'],{e['artifact']['artifact_id']:e['artifact']['content']})
        # The source report also flags missing mandatory public witness evidence.
        if old['applicability']=='applicable' and not old['public_evidence']:errors.append({'reason':'missing_required_public_witness'})
        failure=bool(errors)
    if failure!=row['stratum_failure']:raise RuntimeError('source stratum differs from raw v1 validation')
    original_texts=([e['artifact_A']['content'],e['artifact_B']['content']] if stage=='quality' else
                    [x['content'] for x in e['artifacts']] if stage=='diagnosis' else [e['artifact']['content']])
    if sorted(sha256_text(x) for x in original_texts)!=sorted(d.content_sha256 for d in docs.values()):
        raise RuntimeError('numbered source bytes differ from saved originals')
    return evidence,contract


def prepare():
    selected,cohort=select();inputs=[]
    for row in selected:
        evidence,contract=reconstruct(row)
        inputs.append({**row,'source_manifest':contract.identity()['sources'],'v2_evidence_sha256':canonical_sha256(evidence),
                       'v2_schema_sha256':canonical_sha256(contract.schema)})
    cohort.update(method=VERSION,rows=inputs,logical_requests=len(inputs),provider_calls=0,
                  selection='first four unique request hashes per arm/stage/failure stratum sorted by task, replicate, request hash',
                  source_v1_snapshot='106863b2ca1bfb543be3d6660aaeca56baec15af')
    destination=COHORT_FILE
    if destination.exists() and json.loads(destination.read_text())!=cohort:raise RuntimeError('fixed Phase-A cohort changed')
    write_json_atomic(destination,cohort)
    print(json.dumps({'phase':'A-inputs','logical_requests':len(inputs),'strata':cohort['strata'],'provider_calls':0}),flush=True)
    return cohort


def execute():
    if int(os.environ.get('SLURM_CPUS_PER_TASK','0'))!=32:raise RuntimeError('Phase A requires 32 allocated CPUs')
    frozen=json.loads((FREEZE_FILE).read_text())
    for name,digest in frozen['files'].items():
        if sha256_file(ROOT/name)!=digest:raise RuntimeError('execution snapshot changed: '+name)
    if subprocess.check_output(['git','status','--porcelain','--',*frozen['files']],cwd=ROOT,text=True).strip():
        raise RuntimeError('uncommitted execution files')
    cohort=prepare()
    runtime=policy()
    if runtime['aggregate_concurrency']!=60 or runtime['audit_studies']!=1:raise RuntimeError('shared capacity differs')
    key=dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get('OPENAI_API_KEY')
    if not key:raise RuntimeError('configured OpenAI credential absent')
    os.environ['OPENAI_API_KEY']=key
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    PHASE.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    write_json_atomic(PHASE/'launch.json',{'commit':commit,'job':os.environ['SLURM_JOB_ID'],'cohort_sha256':sha256_file(COHORT_FILE),
        'freeze_sha256':sha256_file(FREEZE_FILE),'runtime':runtime,'cpus':32,'workers':32,'method':VERSION})
    p=RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,model='gpt-5.6-luna',max_retries=5,red_team_trace_version=VERSION)
    stages=TraceStagesV2(p,PHASE/'requests');start=time.monotonic()
    def run(row):
        evidence,contract=reconstruct(row)
        request=stages.request(row['stage'],evidence,contract)
        key=canonical_sha256(request)
        value=stages.call(row['stage'],evidence,contract)
        result=json.loads((PHASE/'requests'/key/'result.json').read_text())
        return {'arm':row['arm'],'stage':row['stage'],'task_id':row['task_id'],'replicate':int(row['replicate']),
                'source_request_sha256':row['request_sha256'],'stratum_failure':row['stratum_failure'],
                'request_sha256':key,'receipt':str(PHASE/'requests'/key/'result.json'),'status':result['outcome']['status'],
                **result['accounting'],'scientific_null':(value is not None and (value.get('preferred_artifact_id','ordered') is None
                    or value.get('action') in {'NO_SUPPORTED_RELATION','PREFERENCE_CONFLICT'} or value.get('applicability')=='undecidable'))}
    with ThreadPoolExecutor(max_workers=32) as pool:rows=list(pool.map(run,cohort['rows']))
    rates={stage:sum(x['status']=='valid_result' for x in rows if x['stage']==stage)/sum(x['stage']==stage for x in rows)
           for stage in ('quality','diagnosis','application')}
    overall=sum(x['status']=='valid_result' for x in rows)/len(rows)
    result={'method':VERSION,'commit':commit,'job':os.environ['SLURM_JOB_ID'],'rows':rows,'rates':rates,'overall_final_valid':overall,
            'overall_first_valid':sum(x['first_response_valid'] for x in rows)/len(rows),'wall_seconds':time.monotonic()-start,
            'gate_passed':overall>=.98 and all(x>=.95 for x in rates.values()) and rates['application']>=.98,
            'interface_invalid_cached_successes':0,'native_metadata_mismatches':0,'scope':'Contract test only; no criterion activation, revisions, rubric scores or outcome audits.'}
    write_json_atomic(PHASE/'result.json',result);write_json_atomic(REPORT/'result.json',result)
    with (REPORT/'requests.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# Phase A — dev1 saved-input contract microbench','',f"Gate: {'PASS' if result['gate_passed'] else 'FAIL'}. {len(rows)} fixed logical requests; source strata and hashes are in the cohort manifest.",'',
           '| Stage | Final contract-valid |','| --- | ---: |',*[f'| {k} | {v:.2%} |' for k,v in rates.items()],'',
           'Valid scientific nulls count as interface-valid. Source references prove attribution, not judgment accuracy. No outputs seed dev3 or Result20 learning caches.']
    (REPORT/'README.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)


if __name__=='__main__':
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('compute-storage access requires Slurm')
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','execute'])
    parser.add_argument('--recipe',choices=['attack_defense_v2.dev1','attack_defense_v2.dev2'],default='attack_defense_v2.dev1')
    args=parser.parse_args()
    VERSION=args.recipe
    suffix=VERSION.rsplit('.',1)[-1]
    PHASE=RUN/'phase-a'/f'{suffix}-001'
    REPORT=ROOT/'docs/reports/2026-09-10/trace-attack-defense-v2/phase-a'/f'{suffix}-001'
    COHORT_FILE=BUNDLE/('phase-a-cohort.json' if suffix=='dev1' else f'phase-a-cohort-{suffix}.json')
    FREEZE_FILE=BUNDLE/f'{suffix}-freeze.json'
    prepare() if args.mode=='prepare' else execute()
