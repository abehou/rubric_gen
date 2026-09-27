"""Offline audit estimate from saved plans and Dev3 token use; no provider calls."""
import contextlib
import io
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()
from rubric_gen.submission_revision.evaluation.evidence import revision_detection_source
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow

def read(p):return json.loads(p.read_text())

def estimate():
    run=ROOT/'runs/healthbench-hard-challenge20-local-20260926'
    eid='healthbench-hard-factorial-r3-01eb8a5a9277'
    audit=run/'audits'/eid
    dev=ROOT/'runs/healthbench-hard-local-mac-20260925-v4'
    old=dev/'audits/healthbench-hard-factorial-r3-967d6a08c7ea'
    # No assumed prompt-cache discount; use cache-write rates for conservative input pricing.
    plans=read(audit/'rubric_score/manifest.json')['predispatch_plan']['jobs']
    usages=[read(p) for p in (old/'rubric_score/artifacts').rglob('usage.json')]
    old_tokens_per_byte=sum(x['call']['raw_usage']['input_tokens'] for x in usages)/sum(x['execution']['request_content_bytes_per_call'] for x in usages)
    output_per_criterion=sum(x['call']['raw_usage']['output_tokens'] for x in usages)/sum(x['execution']['criterion_count'] for x in usages)
    result={}
    inp=sum(x['shape']['total_request_content_bytes'] for x in plans)*old_tokens_per_byte
    out=sum(min(4096,x['shape']['criterion_count']*output_per_criterion) for x in plans)
    result['rubric']={'calls':len(plans),'input_tokens':inp,'output_tokens':out,'usd':(inp*.125+out*.5)/1e6,
        'tokens_per_byte':old_tokens_per_byte,'output_per_criterion':output_per_criterion}
    jobs=read(audit/'absolute_score/manifest.json')['predispatch_plan']['jobs']
    for instrument,folder in [('absolute',dev/'absolute-sol/absolute_score'),('pairwise',old/'pairwise_preference')]:
        records=[read(p) for p in (folder/'records').glob('*.json')]
        usage=[x['generation']['provider_metadata']['usage'] for x in records]
        # Input byte/token ratio is from matching structured requests in old plans.
        old_jobs=read(folder/'manifest.json')['predispatch_plan']['jobs']
        old_jobs=[x for x in old_jobs if x['instrument']==instrument]
        ratio=sum(x['input_tokens'] for x in usage)/sum(x['request_bytes'] for x in old_jobs)
        js=[x for x in jobs if x['instrument']==instrument]
        inp=sum(x['request_bytes'] for x in js)*ratio
        out=len(js)*mean(x['output_tokens'] for x in usage)
        result[instrument]={'calls':len(js),'input_tokens':inp,'output_tokens':out,'usd':(inp*2.5+out*10)/1e6,
            'tokens_per_byte':ratio,'output_per_call':mean(x['output_tokens'] for x in usage),
            'output_source':'Sol high Dev3' if instrument=='absolute' else 'Luna high Dev3, token-matched to Sol; unverified model transfer'}
    study=run/'studies'/eid
    dirs=tuple(study/r['experiment_dir'] for r in read(study/'study.json')['records'])
    cache={}
    for window in RevisionDetectionWindow:
        old_attempts=[read(p) for p in (old/f'direct_{window.value}').rglob('attempt-001.json')]
        old_attempts=[x for x in old_attempts if 'generation' in x]
        def size(req):return len((req['instructions']+req['evidence']+json.dumps(req['schema'])).encode())
        ratio=sum(x['generation']['provider_metadata']['usage']['input_tokens'] for x in old_attempts)/sum(size(x['identity']['request']) for x in old_attempts)
        output=mean(x['generation']['provider_metadata']['usage']['output_tokens'] for x in old_attempts)
        src=revision_detection_source(dirs,tasks_dir=run/'tasks',experiment_ids=(eid,),window=window,shared_inputs=cache)
        sizes=[]
        # Suppress operational telemetry during a provider-free read-only measurement.
        with patch('rubric_gen.runtime.capacity.emit'),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            for case in src.cases:
                p=src.prompt(case,'rh')
                # approximate one-chunk envelope; 1500 bytes extra instruction/schema overhead.
                sizes.append(len((p.instructions+p.evidence+p.task_context).encode())+1500)
        inp=sum(sizes)*ratio;out=len(sizes)*output
        result[window.value]={'calls':len(sizes),'input_tokens':inp,'output_tokens':out,'usd':(inp*.125+out*.5)/1e6,
            'max_input_tokens_estimated':max(sizes)*ratio,'tokens_per_byte':ratio,'output_per_call':output}
    result['total_usd']=sum(v['usd'] for v in result.values())
    result['caveat']='No providers. First-attempt forecast, not upper bound; new rubric length scaled by criteria. Pairwise Sol output extrapolated from Luna. RH input estimated from actual rendered windows and Dev3 byte/token ratio; no cache savings assumed. Output includes reasoning.'
    return result

if __name__=='__main__':
    result=estimate()
    Path(__file__).with_name('audit-cost-estimate.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
