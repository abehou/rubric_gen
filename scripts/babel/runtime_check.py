"""Compute-node, non-scientific acceptance of the prepared Babel deployment."""
import importlib.resources
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from dotenv import dotenv_values
from launch import ROOT, check_shared_mount


def main():
    if not os.environ.get('SLURM_JOB_ID') or socket.gethostname().startswith('login'):
        raise RuntimeError('runtime acceptance requires a compute-node Slurm job')
    root=ROOT/'runs/babel-overnight-20260907'/('runtime-'+os.environ['SLURM_JOB_ID'])
    root.mkdir(parents=True,exist_ok=False)
    started=time.time()
    record=dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),python=sys.executable,
        version=sys.version,started=started,commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        resources={key:os.environ.get(key) for key in ['SLURM_JOB_PARTITION','SLURM_CPUS_PER_TASK','SLURM_MEM_PER_NODE']},
        mount=check_shared_mount(),provider_calls=0)
    values=dotenv_values(ROOT/'.env.local')
    record['credentials_present']={key:bool(values.get(key)) for key in ['OPENAI_API_KEY','ANTHROPIC_API_KEY']}
    if not all(record['credentials_present'].values()):raise RuntimeError('configured credentials are missing')
    if (ROOT/'.env.local').stat().st_mode & 0o077:raise RuntimeError('credential file permissions are not private')
    binary=Path(str(importlib.resources.files('codex_cli_bin')))/'bin/codex'
    record['codex_version']=subprocess.check_output([str(binary),'--version'],text=True).strip()
    live=Path(os.environ['BIOMNIBENCH_LIVE_ROOT']);sentinel=live/('runtime-check-'+os.environ['SLURM_JOB_ID'])
    sentinel.write_text('non-scientific runtime check\n');sentinel.unlink()
    (root/'launch.json').write_text(json.dumps(record,indent=2)+'\n')
    commands=[[sys.executable,str(ROOT/'scripts/babel/check.py')],
        [sys.executable,'-m','pytest','-q','tests/test_codex_session_driver.py','-k','app_server_proxy_isolates_non_rpc_output']]
    exits=[]
    for index,command in enumerate(commands):
        with (root/f'check-{index}.log').open('w') as log:
            exits.append(subprocess.run(command,stdout=log,stderr=subprocess.STDOUT).returncode)
        if exits[-1]:break
    record.update(exits=exits,success=len(exits)==2 and not any(exits),elapsed_seconds=time.time()-started)
    (root/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record),flush=True)
    return int(not record['success'])


if __name__=='__main__':raise SystemExit(main())
