"""Run the unchanged two-auditor protocol with exact semantic/chunk reuse."""
import sys
sys.dont_write_bytecode=True
import argparse, fcntl, importlib.util, json, os, time
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from dotenv import dotenv_values
import openai, anthropic
from rubric_gen.submission_revision.commands import run_detect
from rubric_gen.submission_revision.artifacts import sha256_file
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',type=int,required=True);parser.add_argument('--tags',nargs='*');args=parser.parse_args()
    manifest=json.loads((HERE/'manifest.json').read_text());rows=[r for r in manifest['configs'] if not args.tags or r['tag'] in args.tags]
    assert rows
    # User's updated cap: settle the solver studies before auditing; audit
    # studies execute serially with at most 16 requests in the one active study.
    for row in manifest['configs']:
        ledger=json.loads((Path(row['study'])/'study.json').read_text())
        assert not any(r['status']=='running' for r in ledger['records']), 'Solver work must settle before audit dispatch'
    for row in rows:
        study=json.loads((Path(row['study'])/'study.json').read_text())
        assert study['status']=='completed' and all(r['status']=='completed' for r in study['records'])
    for key,value in dotenv_values(ROOT/'.env.local').items():
        if key in ['OPENAI_API_KEY','ANTHROPIC_API_KEY'] and value:os.environ[key]=value
    reuse=module('bounded_audit_reuse',ROOT/'investigation/autonomous-dev3-20260907/exposure-calibration/audit_reuse.py')
    reuse.SOURCES += [Path(r['audit']) for r in manifest['configs']]
    for task,identity in [('da-3-4','biomnibench-da-factorial-r10-f1268754291f'),('da-11-1','biomnibench-da-factorial-r10-ac19f8be2fe3')]:
        reuse.SOURCES.append(ROOT/f'runs/autonomous-dev3-20260907/exposure-{task}/audit/{identity}')
    reuse.install()
    cache=module('bounded_chunk_cache',HERE/'chunk_cache.py');cache.install(HERE/'direct-chunk-cache')
    import rubric_gen.detection.runner as detection
    original=detection.count_input_tokens
    def count(model,request):
        for attempt in range(4):
            try:return original(model,request)
            except (openai.APIConnectionError,openai.APITimeoutError,anthropic.APIConnectionError,anthropic.APITimeoutError) as exc:
                print('TOKEN COUNT TRANSPORT RETRY',model,attempt+1,type(exc).__name__,flush=True)
                if attempt==3:raise
                time.sleep(2**attempt)
    detection.count_input_tokens=count
    launch=HERE/f'audit-{args.attempt:02d}-launch.json';assert not launch.exists()
    hashes={str(p.relative_to(ROOT)):sha256_file(p) for p in (ROOT/'src').rglob('*.py')}
    workers=16
    launch.write_text(json.dumps(dict(pid=os.getpid(),started_at=datetime.now().astimezone().isoformat(),tags=[r['tag'] for r in rows],
        aggregate_concurrency=workers,max_audit_studies=1,workers_per_study=workers,source_hashes=hashes,
        wrapper_sha256=sha256_file(Path(__file__)),cache_sha256=sha256_file(HERE/'chunk_cache.py'),
        reuse_helper_sha256=sha256_file(ROOT/'investigation/autonomous-dev3-20260907/exposure-calibration/audit_reuse.py')),indent=2)+'\n')
    def run(row):
        print('AUDIT START',row['tag'],flush=True)
        try:
            status=run_detect(SimpleNamespace(experiment=row['config'],study_dir=row['study'],max_concurrency=workers,resume=True))
            return dict(tag=row['tag'],exit_code=status)
        except Exception as exc:
            import traceback;traceback.print_exc()
            return dict(tag=row['tag'],exit_code=1,error_type=type(exc).__name__,error=str(exc))
    results=[run(row) for row in rows]
    assert all(sha256_file(ROOT/p)==h for p,h in hashes.items())
    (HERE/f'audit-{args.attempt:02d}-results.json').write_text(json.dumps(results,indent=2)+'\n')
    raise SystemExit(int(any(r['exit_code'] for r in results)))
if __name__=='__main__':
    with (HERE/'.audit-dispatch.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
