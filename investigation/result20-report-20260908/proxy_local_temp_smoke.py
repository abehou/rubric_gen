"""Exercise the actual proxy/app-server path without models or credentials."""
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time

from rubric_gen.runtime.agents.adapters import _codex_scientific_config
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig

root = Path('runs/babel-result20-current-20260908') / f'proxy-local-smoke-{os.environ["SLURM_JOB_ID"]}'
root.mkdir(exist_ok=False)
root = root.resolve()
live = Path('/home/aydanh/rubric-gen-live') / root.name
live.mkdir(mode=0o700)
workspace = live / 'workspace'
workspace.mkdir()
scratch = workspace / '.agent-tmp'
scratch.mkdir(mode=0o700)
sentinel = live / 'outside.txt'
sentinel.write_text('host sentinel must survive')
state = root / 'codex-home'
state.mkdir(mode=0o700)
(state / 'tmp').mkdir()
(state / 'tmp' / 'original-evidence').write_text('preserve old temporary evidence')
(state / 'sessions').mkdir()
(state / 'sessions' / 'synthetic-preservation-fixture').write_text('not a real session')
executable = CodexSdkSessionDriver._bundled_codex_executable()
(state / 'config.toml').write_text(_codex_scientific_config(AgentRunConfig(executable=executable)))
source = Path('src/rubric_gen/runtime/agents/codex_app_server.py').resolve()
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
environment = {'PATH':os.environ['PATH'], 'PYTHONPATH':str(source.parents[3]), 'PYTHONDONTWRITEBYTECODE':'1'}
program = '''import json,os,pathlib,socket
scratch=pathlib.Path(os.environ['TMPDIR']);scratch.joinpath('scratch.txt').write_text('ok')
pathlib.Path('artifact.txt').write_text('synthetic artifact')
outside=pathlib.Path('../outside.txt')
try: assert outside.read_text() != 'host sentinel must survive'
except OSError: pass
try: outside.write_text('sandbox private')
except OSError: pass
try: s=socket.socket();s.bind(('127.0.0.1',0))
except OSError: pass
else: raise AssertionError('network unexpectedly allowed')
print(json.dumps({'scratch':str(scratch),'network_denied':True}))
'''
started=time.time()
results=[]
for attempt in range(2):
    with (root/f'proxy-{attempt}.stderr').open('w') as errors:
        proxy=subprocess.Popen([sys.executable,'-m','rubric_gen.runtime.agents.codex_app_server',executable,str(workspace),str(state),str(scratch),str(state)],env=environment,cwd=workspace,text=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors)
        def request(identity, method, params):
            proxy.stdin.write(json.dumps({'id':identity,'method':method,'params':params})+'\n');proxy.stdin.flush()
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                if not select.select([proxy.stdout],[],[],1)[0]:continue
                line=proxy.stdout.readline()
                if not line:raise RuntimeError('proxy ended before response')
                value=json.loads(line)
                if value.get('id')==identity:
                    if 'error' in value:raise RuntimeError(value['error'])
                    return value['result']
            raise TimeoutError(method)
        try:
            request(1,'initialize',{'clientInfo':{'name':'rubric-runtime-smoke','version':'1'},'capabilities':{'experimentalApi':True}})
            proxy.stdin.write(json.dumps({'method':'initialized'})+'\n');proxy.stdin.flush()
            result=request(2,'command/exec',{'command':[sys.executable,'-c',program],'cwd':str(workspace),'timeoutMs':20000})
            assert result['exitCode']==0,result
            assert json.loads(result['stdout'])['scratch']==str(scratch),result
            assert sentinel.read_text()=='host sentinel must survive'
            results.append(result)
        finally:
            proxy.terminate();proxy.wait(timeout=10)
    assert not (state/'tmp').is_symlink()
    assert (state/'tmp'/'original-evidence').read_text()=='preserve old temporary evidence'
    assert (state/'sessions'/'synthetic-preservation-fixture').read_text()=='not a real session'
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
result={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'hostname':socket.gethostname(),'elapsed_seconds':time.time()-started,'proxy_sha256':source_hash,'results':results,'scope':'No provider calls; two app-server starts and synthetic command execution; persistent fixture preservation, not real model-session resume'}
(root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
