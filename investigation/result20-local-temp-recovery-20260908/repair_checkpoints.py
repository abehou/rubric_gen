"""Preserve and restore explicitly diagnosed checkpoints after terminal ownership."""
import hashlib,importlib.util,json,os,shutil,socket,time
from pathlib import Path
from types import SimpleNamespace
from rubric_gen.submission_revision.controller_workspace import RevisionWorkspaceManager
from rubric_gen.submission_revision.models import RevisionState
from rubric_gen.submission_revision.artifacts import solution_tree_sha256,verify_submission_snapshot
from rubric_gen.submission_revision.study import _exclusive_study_lease
p=Path(__file__).with_name('condition_launch.py');spec=importlib.util.spec_from_file_location('recovery',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
prior={mode:m.old_owner_gate(mode) for mode in m.OLD_JOBS};m.smoke_gate()
root=m.ROOT/'runs/babel-result20-current-20260908'/f'checkpoint-repair-{os.environ["SLURM_JOB_ID"]}';root.mkdir(exist_ok=False)
rows=[];known=json.loads((m.ROOT/'investigation/result20-report-20260908/resume-workspace-metadata.json').read_text())
for mode in ('user-trace','full-trace'):
    exp=m.config_for(mode,'result20');study=Path(exp.dag['revise']['output_dir'])
    with _exclusive_study_lease(study):
        for item in known:
            snapshot=(m.ROOT/item['snapshot']).resolve()
            if not snapshot.is_relative_to(study.resolve()):continue
            experiment=snapshot.parents[2];state_path=experiment/'state.json';manifest_path=experiment/'manifest.json'
            state=RevisionState.from_json(json.loads(state_path.read_text()));manifest=json.loads(manifest_path.read_text());workspace=Path(manifest['live_workspace_dir'])
            assert state.phase=='judge_in_progress' and state.submission_ids[-1]==snapshot.parent.name
            assert str(workspace)==item['live'] and workspace.is_dir() and not workspace.is_symlink()
            assert manifest.get('session_id')==state.session_id
            verify_submission_snapshot(snapshot.parent)
            expected=json.loads((snapshot.parent/'snapshot.json').read_text())['workspace_sha256']
            before=solution_tree_sha256(workspace)
            metadata={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in (state_path,manifest_path,snapshot.parent/'snapshot.json')}
            backup=root/item['assignment'];backup.mkdir()
            shutil.copytree(workspace,backup/'workspace-before',symlinks=True)
            for q in (state_path,manifest_path):shutil.copyfile(q,backup/q.name)
            (backup/'before.json').write_text(json.dumps({'workspace':str(workspace),'hash':before,'expected':expected,'metadata_sha256':metadata},indent=2)+'\n')
            if before!=expected:
                manager=SimpleNamespace(experiment_dir=experiment,task_dir=Path(manifest['task_dir']))
                RevisionWorkspaceManager.restore_last_scored_workspace(manager,state,workspace)
            after=solution_tree_sha256(workspace);assert after==expected
            assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest()==sha for name,sha in metadata.items())
            row={'assignment':item['assignment'],'before':before,'after':after,'backup':str(backup),'session_and_metadata_unchanged':True};rows.append(row)
            (backup/'after.json').write_text(json.dumps(row,indent=2)+'\n')
assert len(rows)==4
result={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'hostname':socket.gethostname(),'prior_owners':prior,'repairs':rows,'scope':'Native latest-sealed checkpoint restoration only; original changed workspaces preserved; full resume validation still required'}
(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'success':True,'job_id':result['job_id'],'repairs':len(rows),'receipt':str(root/'result.json')}))
