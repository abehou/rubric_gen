"""Test native checkpoint restoration only in disposable local workspaces."""
import hashlib,json,os,socket,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from rubric_gen.submission_revision.controller_workspace import RevisionWorkspaceManager
from rubric_gen.submission_revision.artifacts import solution_tree_sha256
start=time.time();rows=[]
for row in json.loads(Path('investigation/result20-report-20260908/resume-workspace-metadata.json').read_text()):
    snapshot=Path(row['snapshot']).resolve();experiment=snapshot.parents[2]
    manifest_path=experiment/'manifest.json';state_path=experiment/'state.json'
    originals={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (manifest_path,state_path,snapshot.parent/'snapshot.json')}
    manifest=json.loads(manifest_path.read_text());state=json.loads(state_path.read_text())
    fixture=SimpleNamespace(submission_ids=state['submission_ids'],session_id=state.get('session_id'))
    expected=json.loads((snapshot.parent/'snapshot.json').read_text())['workspace_sha256']
    manager=SimpleNamespace(experiment_dir=experiment,task_dir=Path(manifest['task_dir']))
    with tempfile.TemporaryDirectory(prefix='rubric-checkpoint-restore-',dir='/tmp') as directory:
        workspace=Path(directory)/'workspace';workspace.mkdir();(workspace/'synthetic-unsealed-file').write_text('discardable test fixture')
        before=vars(fixture).copy()
        RevisionWorkspaceManager.restore_last_scored_workspace(manager,fixture,workspace)
        actual=solution_tree_sha256(workspace)
        assert actual==expected,(row['assignment'],actual,expected)
        assert vars(fixture)==before
    assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest for name,digest in originals.items())
    rows.append({'assignment':row['assignment'],'restored_hash':actual,'state_unchanged':True,'original_metadata_unchanged':True})
result={'success':len(rows)==4,'job_id':os.environ['SLURM_JOB_ID'],'hostname':socket.gethostname(),'elapsed_seconds':time.time()-start,'scope':'Native latest-sealed-workspace restore on temporary copies only; no live workspace/session mutations, no providers, not full resume acceptance','rows':rows}
out=Path('runs/babel-result20-current-20260908')/f'checkpoint-restore-smoke-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
