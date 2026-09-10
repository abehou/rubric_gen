"""No-provider test of local sandbox bookkeeping with persistent task scratch."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from rubric_gen.runtime.agents.adapters import _codex_scientific_config
from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver


def main():
    started = time.time()
    root = Path('runs/babel-result20-current-20260908') / f'sandbox-temp-smoke-{os.environ["SLURM_JOB_ID"]}'
    root.mkdir(exist_ok=False)
    root = root.resolve()
    live_root = Path('/home/aydanh/rubric-gen-live') / f'sandbox-temp-smoke-{os.environ["SLURM_JOB_ID"]}'
    live_root.mkdir(mode=0o700, exist_ok=False)
    executable = CodexSdkSessionDriver._bundled_codex_executable()
    assert executable
    config = _codex_scientific_config(AgentRunConfig(executable=executable))
    # Fresh private synthetic workspaces only; no experiment payload or auth.
    def check(index):
        workspace = live_root / f'workspace-{index:02d}'
        workspace.mkdir()
        sentinel = live_root / f'outside-{index}.txt'
        sentinel.write_text(f'host-sentinel-{index}')
        scratch = workspace / '.agent-tmp'
        scratch.mkdir(mode=0o700)
        state = root / f'state-{index:02d}'
        state.mkdir(mode=0o700)
        (state / 'config.toml').write_text(config)
        with tempfile.TemporaryDirectory(prefix='rg-sandbox-check-', dir='/tmp') as local:
            # Codex's generated helper executable lives in its parent TMPDIR;
            # make only this private runtime directory readable in the sandbox.
            (state / 'config.toml').write_text(config.replace(
                '[permissions.benchmark-task.filesystem]\n',
                '[permissions.benchmark-task.filesystem]\n' + json.dumps(local) + ' = "read"\n',
            ))
            # Only disposable Codex CLI arg0 bookkeeping is relocated.
            (Path(local) / 'cli-tmp').mkdir()
            (state / 'tmp').symlink_to(Path(local) / 'cli-tmp', target_is_directory=True)
            helper_bin = Path(local) / 'bin'
            helper_bin.mkdir()
            (helper_bin / 'codex-linux-sandbox').symlink_to(executable)
            environment = {'PATH': str(helper_bin) + os.pathsep + os.environ['PATH'], 'HOME': str(state), 'CODEX_HOME': str(state), 'TMPDIR': local}
            program = "import json,os,pathlib,socket\nobservations={'cwd':os.getcwd(),'writes':{}}\nfor label,path in [('workspace',pathlib.Path('result.txt')),('scratch',pathlib.Path(os.environ['TMPDIR'],'command.tmp')),('parent',pathlib.Path('../outside-INDEX.txt'))]:\n if label=='parent':\n  try:observations['parent_read']=path.read_text()\n  except OSError as e:observations['parent_read']=type(e).__name__\n try:path.write_text('synthetic');observations['writes'][label]='allowed'\n except OSError as e:observations['writes'][label]=type(e).__name__\ntry:\n s=socket.socket();s.bind(('127.0.0.1',0));observations['network_bind']='allowed'\nexcept OSError as e:observations['network_bind']=type(e).__name__\nprint(json.dumps(observations))\nraise SystemExit(0 if observations['writes']['workspace']=='allowed' and observations['writes']['scratch']=='allowed' and observations['parent_read']!='host-sentinel-INDEX' and observations['network_bind']!='allowed' else 1)\n".replace('INDEX',str(index))
            # The command retains the existing workspace scratch path. Only
            # the sandbox parent gets disposable local temporary storage.
            command = [executable, 'sandbox', '-P', 'benchmark-task', '-C', str(workspace), '--', '/usr/bin/env', f'TMPDIR={scratch}', sys.executable, '-c', program]
            before = time.time()
            run = subprocess.run(command, cwd=workspace, env=environment, text=True, capture_output=True, timeout=45)
            host_unchanged = sentinel.read_text() == f'host-sentinel-{index}'
            return {'index': index, 'host_sentinel_unchanged':host_unchanged, 'exit': run.returncode if host_unchanged else 1, 'seconds': time.time()-before, 'stdout': run.stdout[-12000:], 'stderr': run.stderr[-2000:]}
    results = []
    for count in (1, 8):
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            batch = list(pool.map(check, range(len(results), len(results)+count)))
        results.extend(batch)
        if any(row['exit'] for row in batch):
            break
    result = {'success': len(results)==9 and all(row['exit']==0 for row in results), 'job_id': os.environ['SLURM_JOB_ID'], 'hostname': socket.gethostname(), 'elapsed_seconds':time.time()-started, 'scope':'Synthetic sandbox only; no providers, credentials, scientific inputs, or active workspaces', 'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'results':results}
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
