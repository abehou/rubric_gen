"""Prospective exact-request recovery cache; never imports historical chunk guesses."""
from dataclasses import asdict
import hashlib,json,threading,time
from datetime import datetime
import openai,anthropic
from pathlib import Path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.detection.prompts import _extract_model_output
from rubric_gen.runtime.llm import GenerationResult,request_parameters_for_model

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

class ChunkCache:
    def __init__(self, root, generate, detection, run_settings):
        self.root=Path(root); self.generate=generate; self.detection=detection; self.run_settings=run_settings
        self.hits=set(); self.lock=threading.Lock(); self.request_locks={}

    def __call__(self, model, request):
        identity={'model':model,'request':asdict(request),'parameters':request_parameters_for_model(model,max_output_tokens=request.max_output_tokens),'run':self.run_settings}
        key=digest(identity);path=self.root/(key+'.json')
        with self.lock:
            request_lock=self.request_locks.setdefault(key, threading.Lock())
        with request_lock:
            if path.is_symlink():raise RuntimeError('chunk cache is a symlink')
            if path.exists():
                saved=json.loads(path.read_text())
                if saved['identity']!=identity or digest(saved['generation'])!=saved['generation_sha256']:
                    raise RuntimeError('chunk cache identity or response hash mismatch')
                generation=GenerationResult(**saved['generation'])
                if generation.requested_model!=model:raise RuntimeError('cached chunk model mismatch')
                _extract_model_output(generation.text,self.detection)
                self.hits.add((model,generation.response_id))
                print('CHUNK REUSED',model,key,flush=True)
                return generation
            transport_errors=(openai.APIConnectionError,openai.APITimeoutError,anthropic.APIConnectionError,anthropic.APITimeoutError)
            for attempt in range(4):
                try:
                    generation=self.generate(model,request)
                    break
                except transport_errors as exc:
                    self.root.mkdir(parents=True,exist_ok=True)
                    with (self.root/'transport-failures.jsonl').open('a') as log:
                        log.write(json.dumps({'time':datetime.now().astimezone().isoformat(),'request_key':key,'model':model,'attempt':attempt+1,'error_type':type(exc).__name__,'error':str(exc)})+'\n')
                    print('CHUNK TRANSPORT RETRY',model,key,attempt+1,flush=True)
                    if attempt==3:raise
                    time.sleep(2**attempt)
            if generation.requested_model!=model:raise RuntimeError('chunk model mismatch')
            _extract_model_output(generation.text,self.detection)
            self.root.mkdir(parents=True,exist_ok=True)
            data=asdict(generation)
            write_json_atomic(path,{'identity':identity,'generation':data,'generation_sha256':digest(data)})
            print('CHUNK SAVED',model,key,flush=True)
            return generation

def install(root):
    """Only the current process is affected; provider payloads and scoring stay exact."""
    from rubric_gen.detection import job_runner
    original_init=job_runner.DetectionJobRunner.__init__
    original_add=job_runner._GeneratedArtifacts.add_cost
    caches=[]
    def init(self,config,run_settings,generate_response,count_tokens,load_payload):
        cache=ChunkCache(root,generate_response,config.detection,run_settings)
        caches.append(cache)
        original_init(self,config,run_settings,cache,count_tokens,load_payload)
    def add_cost(self,model,generation):
        # Reused responses retain authentic usage metadata, but incur no new call cost.
        if any((model,generation.response_id) in c.hits for c in caches):return
        return original_add(self,model,generation)
    job_runner.DetectionJobRunner.__init__=init
    job_runner._GeneratedArtifacts.add_cost=add_cost
