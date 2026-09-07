from dataclasses import replace,asdict
import json
import pytest
from chunk_cache import ChunkCache,install
from rubric_gen.runtime.llm import StructuredRequest,GenerationResult

def request(text='one'):
    return StructuredRequest('fixed monitor',text,'score',{},4096)
def result(model='gpt-5.6-sol',text='{"score": 2, "reason": "valid evidence"}'):
    return GenerationResult(text,'openai',model,model,'response-123',{}, {'usage':{'input_tokens':10,'output_tokens':5}})

def test_completed_chunk_survives_later_failure_and_process_reload(tmp_path):
    calls=[]
    def generate(model, req):
        calls.append(req.evidence)
        if req.evidence=='two':raise ConnectionError('transport')
        return result(model)
    cache=ChunkCache(tmp_path,generate,'rh',{'frozen':'run'})
    first=cache('gpt-5.6-sol',request())
    with pytest.raises(ConnectionError):cache('gpt-5.6-sol',request('two'))
    def forbidden(*args):raise AssertionError('completed request was dispatched again')
    recovered=ChunkCache(tmp_path,forbidden,'rh',{'frozen':'run'})
    assert asdict(recovered('gpt-5.6-sol',request()))==asdict(first)
    assert calls==['one','two']
    assert len(list(tmp_path.glob('*.json')))==1
    assert ('gpt-5.6-sol','response-123') in recovered.hits

def test_invalid_response_not_saved_and_changed_request_not_reused(tmp_path):
    cache=ChunkCache(tmp_path,lambda *args:result(text='not json'),'rh',{})
    with pytest.raises((ValueError,RuntimeError)):cache('gpt-5.6-sol',request())
    assert not list(tmp_path.glob('*.json'))
    calls=[]
    cache=ChunkCache(tmp_path,lambda model,req:(calls.append(req.evidence) or result(model)),'rh',{})
    cache('gpt-5.6-sol',request());cache('gpt-5.6-sol',request('changed'))
    assert calls==['one','changed']

def test_corrupt_cache_fails_closed(tmp_path):
    cache=ChunkCache(tmp_path,lambda *args:result(),'rh',{})
    cache('gpt-5.6-sol',request())
    path=next(tmp_path.glob('*.json'));data=json.loads(path.read_text());data['generation']['text']='{"score":9,"reason":"changed"}';path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError,match='hash mismatch'):cache('gpt-5.6-sol',request())

def test_cache_hits_do_not_add_new_cost(tmp_path,monkeypatch):
    from rubric_gen.detection import job_runner
    from types import SimpleNamespace
    original_init=job_runner.DetectionJobRunner.__init__
    original_add=job_runner._GeneratedArtifacts.add_cost
    calls=[]
    monkeypatch.setattr(job_runner.DetectionJobRunner,'__init__',original_init)
    monkeypatch.setattr(job_runner._GeneratedArtifacts,'add_cost',lambda *args:calls.append(args))
    install(tmp_path)
    runner=job_runner.DetectionJobRunner(SimpleNamespace(detection='rh'),{},lambda *args:result(),lambda *args:10,lambda *args:None)
    artifacts=job_runner._GeneratedArtifacts()
    generation=runner.generate_response('gpt-5.6-sol',request());artifacts.add_cost('gpt-5.6-sol',generation)
    cached=runner.generate_response('gpt-5.6-sol',request());artifacts.add_cost('gpt-5.6-sol',cached)
    assert len(calls)==1
    assert generation==cached


def test_bounded_transport_retry_and_success_cache(tmp_path,monkeypatch):
    import openai,httpx,chunk_cache
    monkeypatch.setattr(chunk_cache.time,'sleep',lambda _:None)
    calls=[]
    def generate(model,req):
        calls.append(req.evidence)
        if len(calls)<3:raise openai.APIConnectionError(request=httpx.Request('POST','https://example.invalid'))
        return result(model)
    cache=ChunkCache(tmp_path,generate,'rh',{})
    cache('gpt-5.6-sol',request());cache('gpt-5.6-sol',request())
    assert len(calls)==3
    assert len((tmp_path/'transport-failures.jsonl').read_text().splitlines())==2


def test_transport_retry_exhaustion_preserves_failure_evidence(tmp_path,monkeypatch):
    import openai,httpx,chunk_cache
    monkeypatch.setattr(chunk_cache.time,'sleep',lambda _:None)
    calls=[]
    def fail(*args):
        calls.append(1)
        raise openai.APIConnectionError(request=httpx.Request('POST','https://example.invalid'))
    cache=ChunkCache(tmp_path,fail,'rh',{})
    with pytest.raises(openai.APIConnectionError):cache('gpt-5.6-sol',request())
    assert len(calls)==4
    assert not list(tmp_path.glob('*.json'))
    assert len((tmp_path/'transport-failures.jsonl').read_text().splitlines())==4


def test_distinct_requests_run_concurrently_and_duplicates_reuse(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    rendezvous=threading.Barrier(2)
    calls=[]
    def generate(model, req):
        calls.append(req)
        rendezvous.wait(timeout=5)
        return result(model)
    cache=ChunkCache(tmp_path,generate,'rh',{})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(cache,'gpt-5.6-sol',request(text)) for text in ['a','b']]
        for f in futures:f.result()
    cache('gpt-5.6-sol',request('a'))
    assert len(calls)==2
