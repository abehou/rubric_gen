"""One authorized minimal Gemini access check; no benchmark payload or secrets logged."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from dotenv import dotenv_values
import yaml
from rubric_gen.runtime.llm import StructuredRequest,generate_structured,count_input_tokens
from rubric_gen.runtime.capacity import policy

ROOT=Path(__file__).resolve().parents[2]
if not os.environ.get('SLURM_JOB_ID'):raise SystemExit('Slurm allocation required')
os.umask(0o077)
config=ROOT/'experiments/biomnibench-dev3.yaml'
models=[m for m in yaml.safe_load(config.read_text())['outcome_audit']['models'] if m.startswith('gemini')]
assert models==['gemini-3.8-flash'], 'configured Gemini identity changed'
model=models[0]
key=dotenv_values(ROOT/'.env.local').get('GEMINI_API_KEY')
job=os.environ['SLURM_JOB_ID'];out=ROOT/f'runs/babel-overnight-20260907/gemini-access-{job}';out.mkdir(exist_ok=False)
record=dict(job_id=job,hostname=socket.gethostname(),started_at=datetime.now(timezone.utc).isoformat(),model=model,model_config=str(config),config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),resource_request=dict(partition='preempt',qos='preempt_cpu_qos',cpus=2,memory='8G',time='00:15:00',gpus=0,account=None),policy=policy(),benchmark_payload=False,steps=[])
request=StructuredRequest(instructions='Return exactly the requested JSON object with status ok.',evidence='This is a minimal API connectivity check.',schema_name='rubric_gemini_access',schema={'type':'object','additionalProperties':False,'required':['status'],'properties':{'status':{'type':'string','enum':['ok']}}},max_output_tokens=1024)
start=time.monotonic()
try:
    if not key:raise RuntimeError('GEMINI_API_KEY missing from configured dotenv file')
    os.environ['GEMINI_API_KEY']=key
    response=generate_structured(model,request,timeout_seconds=60)
    assert json.loads(response.text)=={'status':'ok'}, 'unexpected structured response'
    record['steps'].append(dict(stage='generation',success=True,elapsed_seconds=time.monotonic()-start,effective_model=response.effective_model,response_id=response.response_id))
    tokens=count_input_tokens(model,request)
    record['steps'].append(dict(stage='token_count',success=True,input_tokens=tokens))
    record['success']=True
except Exception as exc:
    # The custom Gemini client wraps HTTP errors; never persist a key-bearing URL.
    detail=str(exc)
    if key:detail=detail.replace(key,'[REDACTED]')
    detail=re.sub(r'([?&]key=)[^&\s\"\']+',r'\1[REDACTED]',detail)
    status=re.search(r'HTTP (\d{3})',detail)
    symbolic=next((x for x in ['RESOURCE_EXHAUSTED','API_KEY_INVALID','PERMISSION_DENIED','UNAUTHENTICATED','NOT_FOUND','UNAVAILABLE'] if x in detail),None)
    reason='prepayment_credit_exhaustion' if ('prepay' in detail.lower() and any(x in detail.lower() for x in ['deplet','exhaust','credit'])) else 'provider_error'
    record.update(success=False,error_type=type(exc).__name__,http_status=int(status.group(1)) if status else None,provider_status=symbolic,failure_class=reason,sanitized_detail=detail[:1600])
record['elapsed_seconds']=time.monotonic()-start
(out/'result.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:record.get(k) for k in ['job_id','model','success','error_type','http_status','provider_status','failure_class','elapsed_seconds']}))
